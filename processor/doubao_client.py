"""
豆包 API 客户端
--------------
封装豆包（火山引擎）API 调用。
通过 HTTP 请求调用豆包大模型进行工程信息分析。
"""
import json
import time
import requests
from typing import Optional
from loguru import logger

from config.settings import ZHIPU_API_KEY, ZHIPU_BASE_URL, ZHIPU_MODEL

# 思考模式开关：None=关闭思考（推荐，速度快、JSON 稳定）；
# 设为数字则开启思考并限制思考 token 预算（如 2048）。
# 2026-08-22 实测：glm-4.7 思考模式在批量长 prompt 下 content 常为空（思考占满），
# 返回思考草稿导致 JSON 解析失败（13/53 失败）→ 关闭思考，直接输出 JSON。
THINKING_BUDGET = None


class DoubaoClient:
    """豆包 API 客户端（含累计 token 计数器，用于监控 500 万免费额度）"""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or ZHIPU_API_KEY
        self.base_url = ZHIPU_BASE_URL
        self.endpoint = f"{self.base_url}/chat/completions"
        self.model = model or ZHIPU_MODEL
        # 创建 session 绕过系统代理（与爬虫一致）
        self.session = requests.Session()
        self.session.trust_env = False
        # 累计 token 计数器
        self._cumulative_prompt_tokens = 0
        self._cumulative_completion_tokens = 0
        self._cumulative_total_tokens = 0
        self._api_call_count = 0

    @property
    def cumulative_usage(self) -> dict:
        """获取累计 token 消耗"""
        return {
            "prompt_tokens": self._cumulative_prompt_tokens,
            "completion_tokens": self._cumulative_completion_tokens,
            "total_tokens": self._cumulative_total_tokens,
            "call_count": self._api_call_count,
        }

    def reset_cumulative_usage(self):
        """重置累计计数器（谨慎使用）"""
        self._cumulative_prompt_tokens = 0
        self._cumulative_completion_tokens = 0
        self._cumulative_total_tokens = 0
        self._api_call_count = 0

    def chat(self, system_prompt: str, user_message: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             enable_web_search: bool = False,
             search_limit: int = 0) -> Optional[str]:
        """
        调用豆包聊天接口（每次调用均为独立的单轮对话，不携带历史上下文）。

        Args:
            system_prompt: 系统提示词（定义 AI 角色）
            user_message: 用户消息（要分析的内容）
            temperature: 随机性（0=确定性，1=创造性）
            max_tokens: 最大输出长度
            enable_web_search: 是否开启联网搜索（豆包会通过 enable_search 访问网页）
            search_limit: 联网搜索返回条数上限（0=不限制，>0 时尽力限制）

        Returns:
            AI 回复文本，失败返回 None
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # 联网搜索：智谱要求 tools 格式（GLM-4-Flash 模型页确认支持网页检索）
        # 顶层 web_search 参数无效 → tools:[{type:"web_search", web_search:{enable:true}}]
        if enable_web_search:
            payload["tools"] = [{
                "type": "web_search",
                "web_search": {"enable": True, "search_engine": "baidu"},
            }]

        # 智谱推理模型（glm 系列）：模型内部仍会推理，THINKING_BUDGET 控制是否
        # 输出思考草稿（reasoning_content）。关闭思考 → 直接输出答案，速度快、
        # JSON 稳定，不会出现思考占满 max_tokens 导致 content 为空。
        if self.model.startswith("glm") and THINKING_BUDGET:
            payload["thinking"] = {
                "type": "enabled",
                "token_budget": THINKING_BUDGET,
            }

        # 智谱模型偶发 429 限流 / 超时 → 指数退避重试（429 等待更长：10/20/40/80/160s）
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=240,
                )
                resp.raise_for_status()
                break
            except requests.Timeout:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt * 10  # 10s, 20s, 40s, 80s
                    logger.warning(f"智谱 API 请求超时，{wait}s 后重试 ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                logger.error("智谱 API 请求超时")
                return None
            except requests.RequestException as e:
                if attempt < max_retries - 1 and resp is not None and resp.status_code == 429:
                    # 账户级 RPM≈1/分钟：指数退避会在同一窗口内反复撞墙，
                    # 固定等待 70s（一个限流窗口）后重试，越过窗口下次必成功
                    wait = 70
                    logger.warning(f"智谱 API 限流(429)，固定等待 {wait}s 后重试 ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                logger.error(f"智谱 API 请求失败: {e}")
                return None

        try:
            data = resp.json()

            # 解析响应（兼容 OpenAI 格式）
            if "choices" in data and len(data["choices"]) > 0:
                message = data["choices"][0]["message"]
                content = message.get("content") or ""
                # 智谱 GLM 推理模型：content 可能为空（max_tokens 被思考过程占满），
                # 兜底返回 reasoning_content，避免静默丢失
                if not content.strip():
                    reasoning = message.get("reasoning_content") or ""
                    if reasoning.strip():
                        content = reasoning
                # 记录 token 消耗（单次 + 累计）
                usage = data.get("usage", {})
                if usage:
                    p = usage.get("prompt_tokens", 0)
                    c = usage.get("completion_tokens", 0)
                    t = usage.get("total_tokens", 0)
                    self._cumulative_prompt_tokens += p
                    self._cumulative_completion_tokens += c
                    self._cumulative_total_tokens += t
                    self._api_call_count += 1
                    logger.info(
                        f"智谱 API 消耗: "
                        f"prompt={p} completion={c} total={t} | "
                        f"累计: {self._cumulative_total_tokens} tokens "
                        f"({self._api_call_count}次)"
                    )
                return content
            else:
                logger.error(f"豆包 API 返回格式异常: {data}")
                return None

        except requests.Timeout:
            logger.error("豆包 API 请求超时")
            return None
        except requests.RequestException as e:
            logger.error(f"豆包 API 请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"豆包 API 异常: {e}")
            return None

    def chat_json(self, system_prompt: str, user_message: str,
                  temperature: float = 0.1, max_tokens: int = 2048,
                  enable_web_search: bool = False,
                  search_limit: int = 0) -> Optional[dict]:
        """
        调用豆包并要求返回 JSON 格式

        在 system_prompt 中需明确要求 AI 返回 JSON。
        """
        response = self.chat(system_prompt, user_message,
                             temperature=temperature, max_tokens=max_tokens,
                             enable_web_search=enable_web_search,
                             search_limit=search_limit)
        if not response:
            return None

        # 尝试从回复中提取 JSON
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            logger.warning(f"无法从豆包回复中解析 JSON: {response[:200]}")
            return None


# 全局单例
doubao = DoubaoClient()
