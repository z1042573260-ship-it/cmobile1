/* ============================================================================
 * AI 情报助手（独立组件，2026-08-27）
 * ----------------------------------------------------------------------------
 * 功能：
 *   1. 右下角悬浮聊天窗，只基于项目数据库（DASHBOARD_DATA）回答
 *   2. 回答中 [项目全名] 渲染为可点击胶囊 → 大屏定位 + 弹卡片
 *   3. 多轮对话（最近 4 轮）+ 语音输入（Chrome webkitSpeechRecognition）
 *   4. 安全开关：API_BASE 为占位符/空 → 整个组件不渲染，页面与原来完全一致
 *
 * 用法：
 *   - 本地调试：python scripts/ai_proxy.py（Flask 代理，端口 5050）+ API_BASE=http://localhost:5050
 *   - 线上：Cloudflare Worker（workers/ai-chat.js）+ API_BASE=https://xxx.workers.dev
 *   - 完全不想要：删掉 index.html 里 2 行 + 本文件即可，零残留
 * ========================================================================== */
(function () {
	'use strict';

	// ===== 配置（唯一需要改的地方）=====
	var AI_CONFIG = {
		// 本地代理 / 线上 Worker 地址（两者协议一致：POST {API_BASE}/api/ai/chat，body {messages}，resp {content}）
		// 占位符或空 → 聊天窗不渲染（安全开关）
		API_BASE: 'http://localhost:5050',
		PLACEHOLDER: 'YOUR-WORKER-NAME.workers.dev',
		TIMEOUT_MS: 60000,          // 单次请求超时
		HISTORY_ROUNDS: 4,          // 保留最近 4 轮（8 条）
		MAX_MSG_CHARS: 600,         // 单条消息超长截断
		MAX_HIT: 10,                // 检索命中上限
		POLL_TRIES: 20,             // 地图就绪轮询次数
		POLL_INTERVAL: 500,         // 轮询间隔 ms（共 10 秒）
		MAX_REFS: 5,                // 单条回复最多项目标记数
		CONTEXT_PROJECTS: 15,       // 会话上下文项目池上限（当前命中优先 + 历史累积）
	};

	// ===== 安全开关 =====
	var base = (AI_CONFIG.API_BASE || '').trim();
	if (!base || base.indexOf(AI_CONFIG.PLACEHOLDER) !== -1) {
		// 未配置代理：不渲染任何界面，静默退出，不影响大屏
		return;
	}

	// ===== 工具 =====
	function esc(s) {
		if (s === null || s === undefined) return '';
		return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
	}
	function $(id) { return document.getElementById(id); }
	function el(tag, cls, html) {
		var e = document.createElement(tag);
		if (cls) e.className = cls;
		if (html !== undefined) e.innerHTML = html;
		return e;
	}
	// 阶段/状态归一：完整描述 → 标准阶段（"施工阶段（施工许可证已核发）" → "施工阶段"）
	function stageShort(s) {
		if (!s) return '';
		var b = String(s).split('（')[0].trim();
		if (b === '规划立项' || b === '规划变更') return '规划阶段';
		return b;
	}
	function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

	// ===== 状态 =====
	var history = [];              // [{role, content}] 最近 N 轮
	var contextProjects = [];      // 会话上下文项目池（追问时 AI 仍可引用）
	var listening = false;
	var recog = null;

	// ===== 数据源 =====
	function getPoints() {
		return (window.DASHBOARD_DATA && window.DASHBOARD_DATA.map_points) || [];
	}

	// ===== 检索：本地全字段匹配 + 评分 =====
	// 返回 { mode:'hits'|'summary', hits:[], summary:{} }
	// 中文长句先拆出关键词（区县/红黄/阶段/残留词），再全字段匹配
	// （"芝罘区什么项目" → 拆出"芝罘区"；"龙口市红色预警" → "龙口市"+"红"+"预警"）
	var STOPWORDS = [
		'什么', '哪些', '哪个', '有没有', '有吗', '有哪些', '一个', '一些', '一点',
		'吗', '呢', '了', '的', '项目', '工程', '情况', '信息', '名单', '介绍', '内容',
		'看看', '帮我', '请问', '知道', '下', '中', '和', '与', '给', '有', '是', '超',
		'投资', '建设', '还有', '现在', '最近', '关注', '查询', '查查', '查一下',
	];
	var STAGE_WORDS = ['规划', '招标', '施工', '竣工', '完工', '验收', '待核实', '设计', '监理', '采购', '中标'];
	function splitKeywords(token, districtNames) {
		var out = [], rest = token;
		// ① 区县名（长词优先）
		var names = districtNames.slice().sort(function (a, b) { return b.length - a.length; });
		names.forEach(function (d) {
			if (rest.indexOf(d) !== -1) { out.push(d); rest = rest.split(d).join(''); }
		});
		// ② 红黄预警
		if (rest.indexOf('红') !== -1) { out.push('红'); }
		if (rest.indexOf('黄') !== -1) { out.push('黄'); }
		// ③ 阶段词
		STAGE_WORDS.forEach(function (w) {
			if (rest.indexOf(w) !== -1) { out.push(w); rest = rest.split(w).join(''); }
		});
		// ④ 残留（去停用词后长度≥2 保留，如"产业园""综合体"）
		STOPWORDS.forEach(function (w) { rest = rest.split(w).join(''); });
		rest = rest.replace(/[的了吗呢]/g, '');
		if (rest.length >= 2) out.push(rest);
		return out;
	}
	function searchProjects(query) {
		var pts = getPoints();
		var q = (query || '').trim();

		var districtNames = [];
		if (window.DISTRICT_CENTERS) {
			Object.keys(window.DISTRICT_CENTERS).forEach(function (k) { districtNames.push(k); });
		}
		pts.forEach(function (p) {
			if (p.district && districtNames.indexOf(p.district) === -1) districtNames.push(p.district);
		});

		var wantRed = /红/.test(q), wantYellow = /黄/.test(q);
		var wantDistrict = null;
		districtNames.forEach(function (d) {
			if (wantDistrict) return;
			if (q.indexOf(d) !== -1) wantDistrict = d;
		});

		// 关键词拆分：长句 → 关键词列表（每个都要命中）
		var keywords = [];
		q.split(/[\s,，、]+/).forEach(function (t) {
			if (!t) return;
			splitKeywords(t, districtNames).forEach(function (k) {
				if (keywords.indexOf(k) === -1) keywords.push(k);
			});
		});
		// 残留兜底：如果没拆出任何关键词（纯语气句），按区县/红黄匹配
		if (keywords.length === 0 && (wantDistrict || wantRed || wantYellow)) {
			// 仅靠快捷词过滤
		}

		var hits = [];
		pts.forEach(function (p) {
			var S = [
				p.name, p.district, p.project_type, p.stage, p.warning,
				p.location, p.developer, p.scale, p.investment, p.source_name, p.ai_summary,
			].join('|').toLowerCase();
			var ok = true;
			for (var i = 0; i < keywords.length; i++) {
				if (keywords[i] && S.indexOf(keywords[i]) === -1) { ok = false; break; }
			}
			if (!ok) return;
			// 快捷词校验（用户明确要红/黄时，不匹配则排除）
			if (wantRed && String(p.category || '').indexOf('red') === -1 &&
				String(p.warning || '').indexOf('红') === -1) return;
			if (wantYellow && String(p.category || '').indexOf('yellow') === -1 &&
				String(p.warning || '').indexOf('黄') === -1) return;
			if (wantDistrict && p.district !== wantDistrict) return;

			// 评分排序
			var score = 0;
			var nm = String(p.name || '').toLowerCase();
			keywords.forEach(function (t) {
				if (t && nm.indexOf(t) !== -1) score += 100;
			});
			if (wantDistrict && p.district === wantDistrict) score += 50;
			keywords.forEach(function (t) {
				if (!t) return;
				if (t && String(p.project_type || '').toLowerCase().indexOf(t) !== -1) score += 30;
				if (t && (String(p.warning || '').indexOf('红') !== -1 && /红/.test(t))) score += 20;
			});
			score += (p.priority || 0) * 2;
			p._score = score;
			hits.push(p);
		});

		hits.sort(function (a, b) { return (b._score - a._score) || ((b.priority || 0) - (a.priority || 0)); });
		var top = hits.slice(0, AI_CONFIG.MAX_HIT);
		top.forEach(function (p) { delete p._score; });

		if (top.length > 0) return { mode: 'hits', hits: top };
		// 无命中 → 统计概览
		var red = 0, yellow = 0, distCount = {};
		pts.forEach(function (p) {
			if (String(p.warning || '').indexOf('红') !== -1) red++;
			else if (String(p.warning || '').indexOf('黄') !== -1) yellow++;
			var d = p.district || '未知';
			distCount[d] = (distCount[d] || 0) + 1;
		});
		var distTop = Object.keys(distCount).map(function (k) { return { name: k, v: distCount[k] }; })
			.sort(function (a, b) { return b.v - a.v; }).slice(0, 5)
			.map(function (x) { return x.name + ' ' + x.v + '个'; }).join('、');
		return { mode: 'summary', summary: { total: pts.length, red: red, yellow: yellow, distTop: distTop, query: q } };
	}

	// ===== 上下文块（拼进 system prompt）=====
	function buildContextBlock(projects) {
		var lines = projects.map(function (p, i) {
			var parts = [
				'[' + (p.name || '未命名') + ']',
				p.district || '未知区县',
				String(p.warning || '').indexOf('红') !== -1 ? '红' : '黄',
				stageShort(p.stage) || '待核实',
				p.project_type || '未知类型',
				'发布:' + (p.date || p.publish_date || '待核实'),
				p.investment || '待核实',
				p.scale || '待核实',
				p.developer || '未知',
				'P' + (p.priority || 3),
				String(p.ai_summary || '').slice(0, 80),
			];
			return (i + 1) + '. ' + parts.join(' | ');
		});
		return '【项目上下文】当前会话已检索到的 ' + projects.length + ' 个项目（含发布日期等字段），回答只能引用这些数据；引用项目时必须用 [项目全名]（与 name 一字不差）包裹。用户追问（如"这都是什么时间""投资多少""哪个最大""地点在哪"）时，直接从这些项目中找答案，不要回答"查无信息"。\n' + lines.join('\n');
	}

	function buildSummaryBlock(sum) {
		return '【数据库概览】共 ' + sum.total + ' 个预警项目：红色 ' + sum.red + '、黄色 ' + sum.yellow + '。区县分布 TOP：' + sum.distTop + '。未找到与"' + sum.query + '"匹配的项目，请如实告知用户，并给出以上概览。';
	}

	var SYSTEM_PROMPT = [
		'你是烟台工程建设信息预警平台（基站工程情报系统）的数据库查询助手。',
		'回答规则：',
		'1. 只依据【项目上下文】或【数据库概览】中的数据回答，绝不编造上下文之外的项目、数字或信息。',
		'2. 【项目上下文】中有项目时，用户的追问（时间/投资/地点/比较/筛选）应直接从这些项目数据中回答，不要回答"查无信息"；只有上下文确实没有任何相关内容时，才说明"数据库中没有查到此信息"。',
		'3. 简体中文，要点式回答，优先给结论（预警等级、区县、投资规模、发布日期、建设单位、AI摘要）。不用 markdown 表格。',
		'4. 提到项目时，必须用 [项目全名]（与上下文中的 name 一字不差）包裹，一条回复最多 ' + AI_CONFIG.MAX_REFS + ' 个标记。',
		'5. 被问及数据库之外的问题（天气、时事、闲聊无关内容）时，礼貌说明你只负责项目情报查询。',
	].join('\n');

	// ===== 对话 =====
	function callAI(messages) {
		return fetch(base + '/api/ai/chat', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ messages: messages }),
			signal: AbortSignal.timeout ? AbortSignal.timeout(AI_CONFIG.TIMEOUT_MS) : undefined,
		}).then(function (r) {
			return r.json().then(function (d) {
				if (!r.ok) throw new Error((d && d.error) || ('HTTP ' + r.status));
				return d.content;
			});
		});
	}

	// ===== 渲染：转义 + [项目名] → 胶囊 =====
	function renderChatHTML(text) {
		var safe = esc(text);
		var frag = document.createDocumentFragment();
		var re = /\[([^\[\]]+)\]/g;
		var last = 0, m;
		while ((m = re.exec(safe)) !== null) {
			if (m.index > last) frag.appendChild(document.createTextNode(safe.slice(last, m.index)));
			var b = el('button', 'ai-ref', esc(m[1]));
			b.setAttribute('data-name', m[1]);
			frag.appendChild(b);
			last = m.index + m[0].length;
		}
		if (last < safe.length) frag.appendChild(document.createTextNode(safe.slice(last)));
		return frag;
	}

	function addMsg(role, textOrFrag) {
		var bodyEl = $('ai-chat-body');
		if (!bodyEl) return;
		var div = el('div', 'ai-msg ai-msg-' + role);
		if (typeof textOrFrag === 'string') div.textContent = textOrFrag;
		else div.appendChild(textOrFrag);
		bodyEl.appendChild(div);
		bodyEl.scrollTop = bodyEl.scrollHeight;
		return div;
	}
	function addTyping() {
		var d = el('div', 'ai-typing');
		d.innerHTML = '<i></i><i></i><i></i>';
		$('ai-chat-body').appendChild(d);
		$('ai-chat-body').scrollTop = $('ai-chat-body').scrollHeight;
		return d;
	}

	// ===== 跳转：大屏定位 + 弹卡片（降级链）=====
	function findProjectByName(name) {
		var pts = getPoints();
		var nm = String(name || '').trim();
		for (var i = 0; i < pts.length; i++) {
			if (String(pts[i].name || '').trim() === nm) return pts[i];
		}
		// 前缀匹配（>4 字）
		if (nm.length > 4) {
			for (var j = 0; j < pts.length; j++) {
				var pn = String(pts[j].name || '').trim();
				if (pn.indexOf(nm) === 0 || nm.indexOf(pn) === 0) return pts[j];
			}
		}
		return null;
	}
	function focusProject(proj) {
		if (!proj) return;
		// 若 2D 开着先关闭（与 marquee 点击范式一致）
		if (window.GaodeMap2D && window.GaodeMap2D.isVisible && window.GaodeMap2D.isVisible()) {
			try { window.GaodeMap2D.hide(); } catch (e) {}
		}
		// 1) 3D 弹卡片（轮询等待地图就绪）
		(async function () {
			for (var t = 0; t < AI_CONFIG.POLL_TRIES; t++) {
				if (window.yantaiMapChart && window.yantaiMapChart.focusWarningPin) {
					try {
						if (window.yantaiMapChart.focusWarningPin({ name: proj.name, district: proj.district })) {
							console.log('[AI聊天] 定位成功(3D弹卡):', proj.name);
							return;
						}
					} catch (e) { console.warn('[AI聊天] focusWarningPin 异常:', e); }
				}
				await sleep(AI_CONFIG.POLL_INTERVAL);
			}
			// 2) 降级：2D 坐标定位
			var v = proj.value;
			if (v && v.length >= 2 && window.GaodeMap2D && window.GaodeMap2D.show) {
				try {
					window.GaodeMap2D.show(Number(v[0]), Number(v[1]), 12);
					console.log('[AI聊天] 定位成功(2D坐标):', proj.name);
					return;
				} catch (e) { console.warn('[AI聊天] 2D定位异常:', e); }
			}
			// 3) 降级：下钻区县（仅 geojson 11 区县）
			var GEO_DISTRICTS = ['芝罘区', '福山区', '牟平区', '莱山区', '蓬莱区', '龙口市', '莱阳市', '莱州市', '招远市', '栖霞市', '海阳市'];
			if (proj.district && GEO_DISTRICTS.indexOf(proj.district) !== -1 && window.yantaiMapChart && window.yantaiMapChart._switchDistrict) {
				try {
					window.yantaiMapChart._switchDistrict(proj.district);
					console.log('[AI聊天] 定位成功(下钻区县):', proj.district);
					return;
				} catch (e) { console.warn('[AI聊天] 下钻异常:', e); }
			}
			console.warn('[AI聊天] 定位失败:', proj.name);
			addMsg('ai', '定位失败，请在地图上手动查找该项目。');
		})();
	}

	// ===== 发送 =====
	function sendQuestion() {
		var input = $('ai-chat-input');
		var text = (input.value || '').trim();
		if (!text) return;
		input.value = '';
		addMsg('user', text);

		// 检索当前问题 + 合并会话上下文项目池（追问"这都是什么时间"时，
		// 上轮检索到的项目仍在上下文中 → AI 能直接回答，不依赖穷举关键词）
		var res = searchProjects(text);
		var merged = (res.mode === 'hits' ? res.hits : []).slice();
		contextProjects.forEach(function (p) {
			if (merged.length >= AI_CONFIG.CONTEXT_PROJECTS) return;
			var dup = merged.some(function (m) { return (m.name || '') === (p.name || ''); });
			if (!dup) merged.push(p);
		});
		contextProjects = merged;
		var contextBlock = merged.length
			? buildContextBlock(merged)
			: buildSummaryBlock(res.summary);
		var system = SYSTEM_PROMPT + '\n\n' + contextBlock;

		var msgs = [{ role: 'system', content: system }];
		history.slice(-AI_CONFIG.HISTORY_ROUNDS * 2).forEach(function (m) {
			var c = String(m.content || '');
			if (c.length > AI_CONFIG.MAX_MSG_CHARS) c = c.slice(0, AI_CONFIG.MAX_MSG_CHARS);
			msgs.push({ role: m.role, content: c });
		});
		msgs.push({ role: 'user', content: text.slice(0, AI_CONFIG.MAX_MSG_CHARS) });

		var typing = addTyping();
		callAI(msgs).then(function (content) {
			if (typing.parentNode) typing.parentNode.removeChild(typing);
			history.push({ role: 'user', content: text });
			history.push({ role: 'assistant', content: content });
			if (history.length > AI_CONFIG.HISTORY_ROUNDS * 2 + 2) {
				history = history.slice(-AI_CONFIG.HISTORY_ROUNDS * 2);
			}
			addMsg('ai', renderChatHTML(content));
		}).catch(function (err) {
			if (typing.parentNode) typing.parentNode.removeChild(typing);
			console.warn('[AI聊天] 请求失败:', err);
			addMsg('ai', '⚠️ AI 服务暂时不可用（' + (err.message || '网络错误') + '）。大屏其他功能不受影响。');
		});
	}

	// ===== 语音输入（Chrome webkitSpeechRecognition，中文）=====
	function initSpeech() {
		var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!SR) return false;
		recog = new SR();
		recog.lang = 'zh-CN';
		recog.interimResults = true;
		recog.continuous = false;
		recog.onresult = function (e) {
			var t = '';
			for (var i = e.resultIndex; i < e.results.length; i++) t += e.results[i][0].transcript;
			var input = $('ai-chat-input');
			if (input) { input.value = t; }
		};
		recog.onend = function () { listening = false; updateMic(); };
		recog.onerror = function () { listening = false; updateMic(); };
		return true;
	}
	function toggleSpeech() {
		if (!recog) return;
		if (listening) { recog.stop(); }
		else {
			try { recog.start(); listening = true; updateMic(); } catch (e) { console.warn('[AI聊天] 语音启动失败:', e); }
		}
	}
	function updateMic() {
		var mic = $('ai-chat-mic');
		if (mic) mic.classList.toggle('listening', listening);
	}

	// ===== UI =====
	function buildUI() {
		var root = $('ai-chat');
		if (!root) return;
		root.className = 'ai-chat';

		var head = el('div', 'ai-chat-head');
		head.innerHTML = '<span class="ai-chat-title">AI 情报助手</span><span class="ai-chat-toggle" id="ai-chat-toggle" title="收起">—</span>';
		var body = el('div', 'ai-chat-body');
		body.id = 'ai-chat-body';
		var foot = el('div', 'ai-chat-foot');
		var input = el('input', 'ai-chat-input');
		input.id = 'ai-chat-input';
		input.placeholder = '问：区县 / 类型 / 预警 / 投资规模…';
		input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuestion(); } });
		var mic = el('button', 'ai-chat-mic', '🎤');
		mic.id = 'ai-chat-mic';
		mic.type = 'button';
		mic.title = '语音输入（Chrome）';
		var send = el('button', 'ai-chat-send', '发送');
		send.type = 'button';

		// 事件委托：项目胶囊
		body.addEventListener('click', function (e) {
			var b = e.target && e.target.closest ? e.target.closest('.ai-ref') : null;
			if (!b) return;
			var proj = findProjectByName(b.getAttribute('data-name'));
			if (proj) focusProject(proj);
			else { addMsg('ai', '库中未找到与"' + b.getAttribute('data-name') + '"完全匹配的项目，请在地图上手动查找。'); }
		});

		foot.appendChild(input);
		if (initSpeech()) {
			mic.addEventListener('click', toggleSpeech);
			foot.appendChild(mic);
		}
		send.addEventListener('click', sendQuestion);
		foot.appendChild(send);

		head.querySelector('#ai-chat-toggle').addEventListener('click', function () {
			root.classList.toggle('collapsed');
		});

		root.appendChild(head);
		root.appendChild(body);
		root.appendChild(foot);

		addMsg('ai', '你好，我是 AI 情报助手，只回答本平台项目数据库（' + getPoints().length + ' 个预警项目）中的内容。试试问："芝罘区红色预警项目"、"投资超 10 亿的项目"。回答中 [带方括号] 的项目可点击，直接定位到地图。');

		// 折叠态 FAB（独立于聊天窗，body 下）
		var fab = el('button', 'ai-fab', 'AI');
		fab.id = 'ai-fab';
		fab.title = '打开 AI 情报助手';
		fab.addEventListener('click', function () {
			root.classList.remove('collapsed');
			fab.style.display = 'none';
		});
		document.body.appendChild(fab);
		// 收起时显示 FAB
		new MutationObserver(function () {
			fab.style.display = root.classList.contains('collapsed') ? '' : 'none';
		}).observe(root, { attributes: true, attributeFilter: ['class'] });
		// 初始：聊天窗默认展开（可自行调整）
	}

	// ===== 启动（数据就绪后构建 UI）=====
	function boot() {
		if (document.getElementById('ai-chat-body')) return;   // 防重复
		buildUI();
	}
	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', boot);
	} else {
		boot();
	}

	// ===== 调试接口 =====
	window.AIChat = {
		send: sendQuestion,
		getBase: function () { return base; },
	};
})();
