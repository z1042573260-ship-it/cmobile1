# 对话分析型智能体 · 接入设计方案

> 适用范围：`wangluobu_vscode` 项目（烟台基站工程情报系统）
> 文档目的：把"能对着项目数据对话、做分析总结"的智能体落地到现有系统，给出架构、工具清单、数据归一要求、前置阻塞与改动清单。
> 状态：📋 方案文档（待你拍板后进入编码）

---

## 1. 目标定位（先对齐"智能体"是什么）

你要的不是"自动跑管线的工具 agent"，而是 **对话分析型智能体**：

- ✅ 用户在前端开一个聊天窗，用自然语言提问
- ✅ 智能体**针对你当前项目里的数据**（190 条工程情报）做分析、筛选、汇总、对比、趋势判断
- ✅ 例如："莱山区有哪些红色预警？""投资方待核实的有多少条？""高新区和海阳市谁基站需求更急？""给我一份本周高优先级清单"
- ❌ 不负责"自动爬取 / 自动写库"——那是 `ai_pipeline.py` + crawler 的主干职责（全自动链路），智能体只做**查询 + 分析 + 总结**这一层

**一句话定位**：在现有 `webapp` 看板里加一个"AI 问答"入口，后端接 LLM，LLM 通过工具按需查数据库 / 读 `workbuddy.json`，再组织自然语言回答。

```
用户(前端聊天窗)  ──自然语言──▶  /api/agent/chat
                                  │
                                  ▼
                        Agent 后端 (routes/agent.py)
                          ├─ 组装 system prompt（角色 + 数据字典说明）
                          ├─ 调 LLM（带 function calling 工具声明）
                          ├─ LLM 决定调用哪个工具
                          ├─ 执行工具 → 查 DB 或读 workbuddy.json
                          └─ 把工具结果回灌 LLM → 生成中文回答
                                  │
                                  ▼
                           前端渲染回答（含引用了哪些项目/字段）
```

---

## 2. 推荐架构

### 2.1 接入点：新增 `webapp/routes/agent.py` 蓝图

| 项 | 内容 |
|---|---|
| 蓝图名 | `agent_bp` |
| 路由 | `GET /agent` → 聊天页面；`POST /api/agent/chat` → 对话接口 |
| 鉴权 | 复用 `@login_required`（与 report/dashboard 一致） |
| 依赖 | 复用 `database/models.py` 的 `Project`、复用 `processor/doubao_client.py` 的 `DoubaoClient`（或新建一个更通用的 `LLMClient`） |
| 注册 | 在 `webapp/app.py` 第 48 行附近 `from webapp.routes.agent import agent_bp`，并在 54 行后 `app.register_blueprint(agent_bp)` |

### 2.2 前端：新增 `frontend/agent.html` + 入口

- 新增 `frontend/agent.html`：左侧/右侧一个聊天面板，输入框 + 消息流，可折叠
- 在 `frontend/index.html`（看板首页）加一个"🤖 AI 问答"按钮或顶部导航项，点击打开 `agent.html`
- JS 用 `fetch('/api/agent/chat', {method:'POST', body: JSON})` 交互，支持流式（SSE）可选，先做非流式

### 2.3 LLM 调用层（统一封装，解决 key 失效问题）

现状：`config/settings.py` 里 DeepSeek 中转站 key 实测 **401 Invalid token**，豆包 key 已注释（额度用完）。
设计：把 LLM 调用抽象成 `processor/llm_client.py`（或扩展 `doubao_client.py`），**从 `settings` 读取可配置的 `BASE_URL / API_KEY / MODEL`**，支持 OpenAI 兼容格式 + function calling。这样你**恢复任意一个可用 key 即可上线**，代码不用再改。

```python
# processor/llm_client.py（新增，示意）
from openai import OpenAI
from config.settings import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

def chat_with_tools(system_prompt, messages, tools):
    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    return client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role":"system","content":system_prompt}, *messages],
        tools=tools,
        tool_choice="auto",
    )
```

> ⚠️ **前置阻塞**：当前两个 key 均不可用，function calling（工具调用）无法实测。文档先给出完整设计，等你提供可用 key 后再落地验证（见 §6）。

---

## 3. 数据挂载：两种方案对比

智能体要"知道"190 条数据，才能回答。两种挂载方式：

| 方案 | 做法 | 成本（按当前体量） | 优点 | 缺点 |
|---|---|---|---|---|
| **A. 全量塞进 system prompt** | 把精简后的 190 条直接写进 system prompt | 精简 14 字段 ≈ **79K tokens**；全量 31 字段 ≈ **244K tokens** | 实现极简，无需工具，LLM 直接"看全貌" | 每次对话都烧 79K+ token；数据更新需重建 prompt；长上下文易丢精度 |
| **B. 工具调用 + 按需查库（推荐）** | system prompt 只放"数据字典说明 + 工具清单"，LLM 自己决定查什么 | 单次查询返回几十条 ≈ **1–5K tokens** | 省 token、准、实时（查库即最新）、可解释（能说"基于哪几条"） | 需要写工具函数 + 保证数据可被结构化查询 |

**结论：推荐方案 B（工具调用）** 作为生产形态；方案 A 可作为"零工具"的快速原型验证（当你 key 恢复后想先跑通再说）。

### 3.1 当前数据体量实测（用于成本评估）

| 视图 | 字段 | 字符数 | 约合 token |
|---|---|---|---|
| 全量（31 字段） | 全部 | 244,355 | ~244K |
| 精简（14 字段） | project_name/type/district/location/warning_level/investment/scale/developer/need_base_station/base_station_type/coverage_area/ai_summary/priority/score | 79,331 | ~79K |
| 目录级（6 字段） | project_name/district/location/lng/lat/warning_level | 31,152 | ~31K |

> 数据来源：`data/results/workbuddy.json`（190 条，红色预警 64 / 黄色预警 126）。

---

## 4. 工具清单（方案 B 的核心）

后端实现一组工具函数，每个对应一个 `function` 声明，LLM 按需调用。全部**复用现有 `Project` 模型 / `workbuddy.json`**，不新增数据结构。

| 工具 | 入参 | 行为 | 对应数据 |
|---|---|---|---|
| `query_by_district` | district（如"莱山区"） | 按区县筛选项目 | `district` |
| `query_by_warning` | level（红/黄） | 按预警级别筛选 | `warning_level` |
| `query_by_type` | project_type（如"住宅小区"） | 按工程类型筛选 | `project_type` |
| `query_by_need` | need（高/中/低/无/有） | 按基站需求概率筛选 | `need_base_station` |
| `query_by_status` | status 关键词 | 按阶段筛选（需先做 §5 归一） | `status` |
| `query_by_investment` | min/max（数值，万元） | 按投资额区间筛选（需先做 §5 抽取数值） | `investment` |
| `get_project_detail` | project_name / id | 返回单条完整字段 | 全字段 |
| `summarize` | 筛选条件 | 聚合统计：各区县数量、红黄比、平均评分、待核实占比 | 聚合 |
| `compare` | district A vs B（或 type A vs B） | 两组对比：谁更急、谁投资更大、谁需求更多 | 聚合 |
| `list_pending` | 无 / top N | 列高优先级+未处理项目（processed_status=0 且 priority≥4） | 排序 |

**实现要点**：
- 优先查 MySQL `Project` 表（经 `database/models.py`）；
- 当数据库不可用（pymysql 缺失 / 表未建）时，**自动回退读 `workbuddy.json`**，保证智能体"有数据就能答"；
- 每个工具返回**结构化 JSON + 一句人类可读摘要**，便于 LLM 二次组织语言。

```python
# 示例：query_by_district 伪代码
def query_by_district(district: str):
    rows = Project.query.filter(Project.district == district).all()
    if not rows:
        rows = [p for p in load_json() if p.get("district") == district]
    return [r.to_dict() for r in rows]   # 或 json 回退
```

---

## 5. 数据一致性归一（必须做，否则智能体答不准）

实测 `workbuddy.json` 存在多处写法混杂，智能体按字段查询会漏数据。**归一清单**（建议在 `ai_pipeline.py` 导出阶段固化，或单独写个 `normalize.py` 跑一遍）：

### 5.1 `district` 区县写法归一

当前变体：`高新区(23)` / `烟台高新区(1)` / `烟台开发区(1)` / `烟台市(1)` 与规范写法并存。
建议映射：

| 原始 | 归一为 |
|---|---|
| 高新区 / 烟台高新区 | 烟台高新区 |
| 烟台开发区 | 烟台开发区 |
| 烟台市（无区县） | 留空或归到具体区县（需回看 location） |

> 规范区县清单见 `config/settings.py` 的 `YANTAI_DISTRICTS`，共 15 个。

### 5.2 `need_base_station` 取值归一（🔴 关键 bug）

当前分布：`有(184)` / `中(2)` / `高(2)` / `低(1)` / `无(1)`。
但 `webapp/routes/report.py` 第 39–41 行过滤的是 `["高","中"]` → **报告页只显示 4 条，184 条"有"被漏掉**。

两种修法（二选一，需你定）：
- **(a)** 把 `有` 统一映射成 `高` 或 `中`（语义上"有"≈需要基站）；
- **(b)** 把 report.py 的过滤改成包含 `有`：`Project.need_base_station.in_(["高","中","有"])`，并相应调整 `warning_label()` 映射。

> 智能体工具也依赖这个值，建议和报告页**统一口径**。

### 5.3 `investment` 数值抽取

157/190 含"待核实"（如 `"投资约5亿元（待核实）"`），无法直接比大小。
建议新增一个派生字段 `investment_value`（万元，整数；无法解析则 `None`），工具 `query_by_investment` 用它。抽取规则：正则提金额 + 单位换算（亿→万）。

### 5.4 `status` 阶段归一

当前 `status` 是**自由文本长句**（如"规划阶段（建设工程规划许可证已批）""施工阶段（施工许可证已核发）"），约 60+ 种写法。
建议派生一个 `stage` 枚举字段：`规划立项 / 规划阶段 / 招标阶段 / 施工阶段 / 已竣工 / 招商储备 / 规划变更`，用关键词映射。智能体按阶段筛选时查 `stage` 而非原始 `status`。

---

## 6. 前置阻塞（必须解决才能跑通）

| # | 阻塞 | 现状 | 影响 | 解决方式 |
|---|---|---|---|---|
| 1 | **LLM key 失效** | DeepSeek 中转站返回 `401 Invalid token`；豆包 key 额度用完已注释 | 智能体、ai_pipeline 全部跑不通；function calling 无法验证 | 你提供一个可用 key（DeepSeek 官方 / 豆包 / OpenAI 兼容均可），写入 `settings.py` 的 `LLM_*` |
| 2 | **pymysql 缺失 / DB 不可用** | `import pymysql` 失败；`yantai_projects` 库是否建好未知 | 工具查库失败，需回退 json | 装依赖 `pip install pymysql flask-sqlalchemy`；确认 MySQL 已启动且库已导入 |
| 3 | **report.py 过滤错配** | 过滤 `["高","中"]`，数据是 `"有"` | 报告页几乎空白（仅 4 条） | 按 §5.2 修 |

> 以上阻塞都不影响"写代码"，只影响"联调验证"。文档给出的代码可先写完，等你恢复 key + 装依赖后一次性验证。

---

## 7. 改动文件清单

### 新增
| 文件 | 作用 |
|---|---|
| `processor/llm_client.py` | 统一 LLM 调用（OpenAI 兼容 + function calling），从 settings 读 key |
| `webapp/routes/agent.py` | 智能体蓝图：`/agent` 页面 + `/api/agent/chat` 接口 + 工具调度 |
| `webapp/agent_tools.py` | 工具函数实现（§4 清单），DB 优先、json 回退 |
| `frontend/agent.html` | 聊天窗页面 |
| `frontend/js/agent.js` | 前端交互（调接口、渲染消息） |
| `docs/AGENT_DESIGN.md` | 本文档 |

### 修改
| 文件 | 改动 |
|---|---|
| `webapp/app.py` | 注册 `agent_bp` 蓝图 |
| `config/settings.py` | 新增 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 配置项（保留 DeepSeek/豆包兼容） |
| `frontend/index.html` | 加"AI 问答"入口 |
| `webapp/routes/report.py` | 修 `need_base_station` 过滤（§5.2） |
| `processor/ai_pipeline.py` 或 新增 `processor/normalize.py` | 导出时固化 district/need_base_station/investment/stage 归一（§5） |

---

## 8. 对话循环与记忆设计

- **多轮上下文**：`/api/agent/chat` 维护每条会话的 `messages` 列表（前端传 `session_id`，后端用字典/Redis 暂存，或最简单：前端每次把历史一起发回）。
- **system prompt 内容**：
  1. 角色："你是烟台基站工程情报系统的分析助手"
  2. 数据字典说明（字段含义、取值枚举、单位）
  3. 工具使用约定（何时调哪个工具、如何引用项目名）
  4. 回答风格（中文、先给结论再给依据、不确定就明说）
- **工具结果回灌**：LLM 返回 `tool_calls` → 后端执行 → 把结果作为 `tool` 角色消息回灌 → 再次调 LLM 生成最终自然语言。
- **可解释性**：回答里附"参考项目：XXX、YYY"，前端可点击跳到 `/projects/*` 明细。

---

## 9. 落地步骤（拍板后执行顺序）

1. **你提供可用 LLM key** → 写入 `settings.py`，解阻塞 #1
2. 装依赖（`pymysql` 等），确认 DB → 解阻塞 #2
3. 写 `processor/llm_client.py` + 跑通一次带 function calling 的最小对话
4. 写 `webapp/agent_tools.py`（工具函数，DB 优先 json 回退）
5. 写 `webapp/routes/agent.py`（蓝图 + 接口 + 工具调度循环）
6. 写前端 `agent.html` + `agent.js`，在 `index.html` 加入口
7. 在 `app.py` 注册蓝图
8. 做 §5 数据归一（district / need_base_station / investment / stage）
9. 修 `report.py` 过滤（§5.2，解阻塞 #3）
10. 联调：用真实问题测（"莱山区红色预警有哪些""待核实投资的有多少"），核对回答是否基于真实数据

---

## 10. 一句话总结

在现有看板里加一个"AI 问答"入口，后端用统一封装的 LLM 客户端 + function calling 工具（查库/读 json）实现"对着你的 190 条工程数据对话分析"。**代码可现在写，但联调需你先恢复一个可用 LLM key 并装好数据库依赖**；同时建议顺手做 §5 的数据归一（尤其修掉 report.py 只显 4 条的 bug）。

---
*本文档由 WorkBuddy 基于项目实测生成（workbuddy.json 190 条 / 红64 黄126 / 31 字段）。*
