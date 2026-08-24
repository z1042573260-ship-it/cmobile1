"""
讯飞星火客户端（OpenAI 兼容端点）
-------------------------------
讯飞星火 Lite 永久免费 + 联网搜索，作为坐标补全的搜索补充模型
（glm-4-flash 无联网搜索，管线"外部验证/地址补全"步骤由本客户端承担）。

端点: https://spark-api-open.xf-yun.com/v1/chat/completions
鉴权: Authorization: Bearer {XFYUN_API_KEY}
联网搜索: web_search: {"enable": true}（实测确认参数格式）
"""
import json
import time
import requests
from typing import Optional
from loguru import logger

from config.settings import XFYUN_API_KEY, XFYUN_API_SECRET, XFYUN_BASE_URL, XFYUN_MODEL


class XfyunClient:
    """讯飞星火客户端（OpenAI 兼容端点，鉴权 Bearer apiKey:apiSecret）"""

    def __init__(self, api_key: str = None, api_secret: str = None, model: str = None):
        self.api_key = api_key or XFYUN_API_KEY
        self.api_secret = api_secret or XFYUN_API_SECRET
        self.base_url = XFYUN_BASE_URL
        self.endpoint = f"{self.base_url}/chat/completions"
        self.model = model or XFYUN_MODEL
        self.session = requests.Session()
        self.session.trust_env = False
        self._api_call_count = 0

    def search_ask(self, question: str, max_tokens: int = 512) -> Optional[str]:
        """带联网搜索的问答（地址/项目信息查询）。

        Args:
            question: 问题（如"永和兴游艇螺旋桨厂 海阳 地址在哪"）
            max_tokens: 输出上限

        Returns:
            回答文本，失败返回 None
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}:{self.api_secret}",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": question}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "web_search": {"enable": True},   # 联网搜索
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.session.post(
                    self.endpoint, headers=headers, json=payload, timeout=120,
                )
                if resp.status_code == 429 and attempt < max_retries - 1:
                    wait = 70
                    logger.warning(f"讯飞 API 限流(429)，{wait}s 后重试 ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except requests.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(10 * (attempt + 1))
                    continue
                logger.error("讯飞 API 请求超时")
                return None
            except requests.RequestException as e:
                if attempt < max_retries - 1 and resp is not None and resp.status_code == 429:
                    time.sleep(70)
                    continue
                logger.error(f"讯飞 API 请求失败: {e}")
                return None

        try:
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"].get("content") or ""
                self._api_call_count += 1
                logger.info(f"讯飞 API 调用 {self._api_call_count} 次 | 回复 {len(content)} 字")
                return content
            logger.error(f"讯飞 API 返回格式异常: {data}")
            return None
        except Exception as e:
            logger.error(f"讯飞 API 异常: {e}")
            return None


# 全局单例
xfyun = XfyunClient()
