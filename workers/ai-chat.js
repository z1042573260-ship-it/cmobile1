// ============================================================================
// AI 对话代理（线上版，Cloudflare Workers，免费）
// ----------------------------------------------------------------------------
// 用法：
//   1. dash.cloudflare.com → Workers & Pages → 创建 Worker
//   2. 删除模板代码，粘贴本文件全文 → 部署
//   3. Settings → Variables and Secrets → 添加 ZHIPU_API_KEY（智谱 key，加密存储）
//   4. 记录 https://<worker名>.workers.dev
//   5. frontend/js/chat.js 的 AI_CONFIG.API_BASE 填该地址
//
// 协议与本地 scripts/ai_proxy.py 一致：
//   POST /api/ai/chat  body: {"messages":[...]}  resp: {"content":"..."}
// ============================================================================
const ZHIPU_URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions';
const MODEL = 'glm-4-flash';
const MAX_MESSAGES = 20;
const MAX_BODY = 20000;

function cors(res) {
  const r = new Response(res.body, res);
  r.headers.set('Access-Control-Allow-Origin', '*');
  r.headers.set('Access-Control-Allow-Methods', 'POST, OPTIONS');
  r.headers.set('Access-Control-Allow-Headers', 'Content-Type');
  return r;
}

function json(status, obj) {
  return cors(new Response(JSON.stringify(obj), {
    status, headers: { 'Content-Type': 'application/json' },
  }));
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response('', { status: 204 });
    if (request.method !== 'POST') return json(405, { error: '仅支持 POST' });
    if (!env.ZHIPU_API_KEY) return json(503, { error: 'AI 服务未配置' });

    let body;
    try { body = await request.json(); }
    catch (e) { return json(400, { error: '无效的 JSON' }); }

    const msgs = body.messages;
    if (!Array.isArray(msgs) || msgs.length < 1 || msgs.length > MAX_MESSAGES) {
      return json(400, { error: 'messages 必须为 1..20 条数组' });
    }
    if (JSON.stringify(body).length > MAX_BODY) return json(400, { error: '请求体过大' });

    // 白名单透传 role/content
    const clean = [];
    for (const m of msgs) {
      if (m && ['system', 'user', 'assistant'].includes(m.role) && typeof m.content === 'string') {
        clean.push({ role: m.role, content: m.content.slice(0, 6000) });
      }
    }
    if (!clean.length) return json(400, { error: 'messages 内容无效' });

    let upstream;
    try {
      upstream = await fetch(ZHIPU_URL, {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + env.ZHIPU_API_KEY,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: MODEL, messages: clean, temperature: 0.3, max_tokens: 1024, stream: false,
        }),
      });
    } catch (e) {
      return json(502, { error: '智谱连接失败' });
    }

    if (upstream.status === 200) {
      try {
        const data = await upstream.json();
        return json(200, { content: data.choices[0].message.content });
      } catch (e) {
        return json(502, { error: '智谱响应解析失败' });
      }
    }
    if (upstream.status === 401 || upstream.status === 403) return json(401, { error: 'AI Key 无效' });
    if (upstream.status === 429) return json(429, { error: 'AI 限流，请稍后再试' });
    return json(502, { error: '智谱上游错误 HTTP ' + upstream.status });
  },
};
