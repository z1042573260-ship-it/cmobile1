"""
本地 AI 对话代理（开发/演示用）
--------------------------------
大屏 AI 情报助手（chat.js）的前端调用代理：浏览器 → 本代理 → 智谱 GLM。
key 从 .env 读取（config.settings），不暴露给浏览器。

协议（与线上 Cloudflare Worker workers/ai-chat.js 一致）：
  POST /api/ai/chat
  body:  {"messages": [{"role": "system", "content": "..."}, ...]}
  resp:  {"content": "AI 回复文本"}
  错误:  {"error": "..."} + 对应状态码

用法：
  venv\\Scripts\\python scripts/ai_proxy.py
  默认监听 0.0.0.0:5050（局域网手机也可访问，改 http://<电脑IP>:5050）
  然后大屏 frontend/js/chat.js 的 AI_CONFIG.API_BASE = http://localhost:5050
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, request

try:
    from config.settings import ZHIPU_API_KEY, ZHIPU_BASE_URL, ZHIPU_MODEL
except Exception:
    ZHIPU_API_KEY, ZHIPU_BASE_URL, ZHIPU_MODEL = "", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"

PORT = 5050
app = Flask(__name__)

MAX_MESSAGES = 20
MAX_BODY = 20000


@app.after_request
def add_cors(resp):
    """允许大屏静态页（任意来源）跨域调用；预检放行"""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/api/ai/chat", methods=["OPTIONS"])
def preflight():
    return ("", 204)


@app.route("/api/ai/chat", methods=["POST"])
def chat():
    if not ZHIPU_API_KEY:
        return jsonify({"error": "AI 服务未配置（.env 缺少 ZHIPU_API_KEY）"}), 503
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "无效的 JSON"}), 400
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs or len(msgs) > MAX_MESSAGES:
        return jsonify({"error": "messages 必须为 1..20 条数组"}), 400
    if request.content_length and request.content_length > MAX_BODY:
        return jsonify({"error": "请求体过大"}), 400
    # 白名单透传 role/content
    clean = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role, content = m.get("role"), m.get("content")
        if role in ("system", "user", "assistant") and isinstance(content, str):
            clean.append({"role": role, "content": content[:6000]})
    if not clean:
        return jsonify({"error": "messages 内容无效"}), 400

    import requests
    try:
        r = requests.post(
            ZHIPU_BASE_URL.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + ZHIPU_API_KEY, "Content-Type": "application/json"},
            json={"model": ZHIPU_MODEL, "messages": clean, "temperature": 0.3, "max_tokens": 1024, "stream": False},
            timeout=90,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "智谱连接失败: %s" % e}), 502

    if r.status_code == 200:
        try:
            content = r.json()["choices"][0]["message"]["content"]
            return jsonify({"content": content})
        except Exception:
            return jsonify({"error": "智谱响应解析失败"}), 502
    if r.status_code in (401, 403):
        return jsonify({"error": "AI Key 无效"}), 401
    if r.status_code == 429:
        return jsonify({"error": "AI 限流，请稍后再试"}), 429
    return jsonify({"error": "智谱上游错误 HTTP %d" % r.status_code}), 502


if __name__ == "__main__":
    print(f"[AI代理] 监听 http://0.0.0.0:{PORT}/api/ai/chat（模型: {ZHIPU_MODEL}）")
    print(f"[AI代理] 大屏 chat.js AI_CONFIG.API_BASE = http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
