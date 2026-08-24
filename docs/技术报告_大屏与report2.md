# 技术报告：烟台基站工程情报系统 — 大屏与 report2 专项分析

> 分析对象：`wangluobu_vscode` 项目前端两大形态
> - **大屏**：`frontend/index.html` + `frontend/js/*`（1920×1080 大屏可视化）
> - **report2**：`frontend/report2.html` + `webapp/routes/report.py`（1200px 响应式分析报告）
>
> 分析日期：2026-08-22 ｜ 数据基准：`frontend/data/dashboard_data.json`（340 条，更新于 2026-08-22 13:03）

---

## 1. 系统架构总览

```
政府/招标网站(7大源)
      │  爬虫采集 (crawler/)
      ▼
原始库 raw_projects  ──AI 研判管线 (processor/ai_pipeline.py)──▶  结构化库 projects (MySQL: yantai_projects)
                                                                      │
                                          ┌───────────────────────────┼───────────────────────────┐
                                          │ 导出脚本 scripts/export_dashboard_db.py                │
                                          ▼                                                          │
                          frontend/data/dashboard_data.json  (= report_data.json，340 条)            │
                                          │                                                          │
                       ┌──────────────────┴──────────────────┐                                       │
                       ▼                                     ▼                                        ▼
              大屏 frontend/index.html              report2 frontend/report2.html          Flask /api/report-data
              (fetch 静态 JSON)                     (4 级数据兜底，优先 Flask API)              (实时查 MySQL)
```

**双前端形态**

| 维度 | 大屏 (index.html) | report2 (report2.html) |
|---|---|---|
| 定位 | 指挥中心大屏可视化 | 业务分析报告 / 跟进管理 |
| 布局 | 固定 1920×1080，三栏+地图 | 响应式 1200px，单栏流式 |
| 数据入口 | 静态 `data/dashboard_data.json` | `data/report_data.json` / `/api/report-data` |
| 交互 | 周期切换、地图下钻 | 搜索、筛选、日历、分页、导出、邮件 |
| 服务对象 | 投屏 / 领导视察 | 一线销售 / 运营跟进 |

**服务形态**：Flask (`webapp/app.py`) 跑在 `0.0.0.0:5000`，注册 `report_bp` 提供 `/report`、`/report2`、`/api/report-data`、`/data/<path>`；大屏与 report2 也可经纯静态服务器（如 8000 端口）预览，此时 `/api/report-data` 不可用 → 前端自动回退静态 JSON。

---

## 2. 大屏（frontend/index.html）技术详解

### 2.1 页面构成
- **头部**：标题"工程建设信息自动化预警平台" + 周期切换（本周 / 本月 / 今年）+ 实时时钟（`setTimeout` 每秒刷新）。
- **左栏**：① 预警实时统计（红/黄/项目总数三数字卡）② 区县预警数据（echart2）③ 预警时间趋势（echart3）。
- **中栏**：地图容器 `#map`（3D 烟台）+ `#map2d`（高德 2D，默认隐藏）。
- **右栏**：① 抓取日志（marquee 跑马灯 + 分页）② 项目类型（echart5）③ 项目阶段分布（echart6）。
- **底部托盘**：流光 SVG 线 + 柱状图/预警图菜单。

### 2.2 适配方案（autofit）
`body` 固定为 `1920×1080`，通过 `transform: scale(scaleX, scaleY)` 将 X/Y **独立拉伸**填满视口（`keepFit()` 监听 `resize`）。
> ⚠️ 非等比缩放：在非常规 16:9 屏幕上会出现轻微形变；优点是"无黑边、完整填充"，契合大屏硬件。

### 2.3 数据契约与加载
- **主数据**：`fetch("data/dashboard_data.json")` → 解析后写入 `window.DASHBOARD_DATA`，驱动统计卡 + 全部图表（`initAllCharts`）。
- **详情库**：`fetch("data/workbuddy.json")`（230 条全字段）→ `window.DASHBOARD_WORKBUDDY`，供地图点击详情卡片匹配全字段。
- **自动刷新**：每 5 分钟轮询 `dashboard_data.json?t=Date.now()`，比较 `meta.updated_at`；变化则 `refreshAllCharts()` + 地图 `reloadPoints()`。
- **兜底**：`getData()` 内嵌一份假数据（仅在 JSON 全部加载失败时启用，避免白屏）。

`dashboard_data.json` 结构（与 `report_data.json` 完全相同，均为 `export_dashboard_db.py` 从 MySQL 导出）：
```json
{
  "meta":   { "updated_at": "...", "total_projects": 340, "source": "MySQL ..." },
  "summary":{ "total": 340, "red_warning": 164, "yellow_warning": 176, "district_count": 16 },
  "warning_pie": [...], "type_pie": [...], "stage_pie": [...],
  "district_ranking": [...], "timeline": [...],
  "map_points": [...], "project_list": [ { name, district, warning, date, priority, ... } ]
}
```

### 2.4 图表（ECharts）
- **echart2 区县预警排名**：红/黄**堆叠柱**，柱顶数字随图例选中态联动（全显=总数 / 只红=红数 / 只黄=黄数）。实现上**缓存 `legendselectchanged` 选中态**到 `_legendSel`，再 `setOption` 重设 `label.formatter`，刻意避开 `myChart.getOption()` 在 formatter 内调用导致白屏的坑。
- **周期过滤**：`filterByPeriod(pl, period)` 按 `publish_date` 切分本周（近 7 天）/ 本月 / 今年，驱动 echart2/echart3/echart5/echart6 随头部周期按钮联动。
- **统计口径双标**：`statDistrict()` 把"开发区"并入"福山区"（仅统计卡/饼图口径）；但柱状图 `buildDistrictRanking()` **不过滤**，保持开发区独立显示 → 同一数据两种口径并存。

### 2.5 地图（双引擎）
| 容器 | 引擎 | 技术栈 |
|---|---|---|
| `#map` | `three-map.js` | Three.js 3D 烟台地图 `YantaiMap3D`，依赖 `mini3d.js` 引擎 + d3-geo 墨卡托投影 + GSAP 动画；`d3.geoMercator().center([121.39,37.52]).scale(300)` |
| `#map2d` | `gaode-map-2d.js` | Leaflet + 高德原始瓦片（`webrd0*.is.autonavi.com`）；运行时动态注入 Leaflet CDN |

- **切换**：由 `three-map.js` 注入"全市地图"按钮，在 3D / 2D 间切换。
- **marker 来源**：`dashboard_data.map_points`（坐标已为 GCJ-02，由 amap 管线补全）。
- **gaode-map-2d 详情卡片**：点击 marker → `flyToPointUp(zoom 16)`（点靠上避开底部卡）+ 右侧信息卡（复用 `.scatter-info-card`），通过 `matchDetail()` 关联 `workbuddy.json` / `project_list` 全字段（区县、类型、阶段、投资、规模、AI 推理等），并提供"查看街道"下钻。

### 2.6 大屏已知问题
1. **底图无 SLA**：依赖公共高德原始瓦片，常限速 → 地图偶发空白/加载慢。
2. **CDN 串行注入**：Leaflet、d3、gsap 运行时从 unpkg 注入，串行等待拖慢首屏。
3. **体积阻塞**：echarts.min.js（1MB）全同步加载，无 `defer`；叠加 Three.js（158KB）+ d3 + gsap → 解析阻塞。
4. **坐标系**：经纬度已统一为 GCJ-02（高德合规），与 `amap_geocode` 管线一致。

---

## 3. report2（frontend/report2.html）技术详解

### 3.1 页面定位
1200px 响应式分析报告，面向"查看 / 筛选 / 跟进 / 导出"场景，非投屏大屏。

### 3.2 页面构成
- **顶部操作条**：搜索框 + 导出 Excel + 发送邮件。
- **筛选区**：区县 / 月份 / 阶段（规划/招标/施工/竣工/待核实）/ 类型。
- **可视化**：折线（月度趋势）、饼图（预警分布）、柱状图（区县排名）+ **日历视图**（按日发布下钻 `filterByDay`）。
- **项目列表**：分页 + 快速标签 + **已处理跟进面板**（`processed_status`，支持批量标记 / 备注）。
- **详情弹窗**：全字段 + AI 推理 / 摘要 / 来源链接。

### 3.3 数据加载链路（4 级兜底）
```
① #embedded-data（当前 HTML 无此元素，实际跳过）
② fetch('/api/report-data')          ← Flask 实时聚合
③ fetch('data/report_data.json')     ← 静态（= dashboard_data.json，340 条）
④ fetch('data/dashboard_data.json')  ← 最终兜底全量
⑤ 空兜底（无假数据，仅显示空态）
```
> ⚠️ **兜底触发条件苛刻**：仅当某级返回 `HTTP 错误` 或 `project_list.length === 0` 才继续下一级。若 `/api/report-data` 返回 **>0 条**（哪怕是 bug 导致的 4 条），即采用并停止 —— 这是下方核心 Bug 的放大器。

### 3.4 数据处理
- `processLoadedData()`：过滤 `warning === '无预警'`，饼图去"无预警"项。
- 搜索、区县/月份/阶段/类型筛选、日历下钻、分页、已处理标记**全部前端实现**，不回服务端。

### 3.5 导出与邮件
- **导出 Excel**：`ExcelJS` 生成多 Sheet，含区县数据柱状图 PNG（`chartBar.getDataURL({pixelRatio:2})`）。
- **发送邮件**：`sendReportEmail()` → `POST /api/report/send-email`，请求体可指定 `report` 模板（`report.html` / `report2.html`）与收件人。

---

## 4. 后端 API（webapp/routes/report.py）

### 4.1 路由
| 路由 | 说明 |
|---|---|
| `/report` | `send_file(frontend/report.html)` |
| `/report2` | `send_file(frontend/report2.html)` |
| `/data/<path>` | 静态 JSON（`frontend/data/`） |
| `/api/report-data` | 从 `Project` 表实时聚合（见 4.2） |
| `/api/report/send-email` | 邮件发送（POST） |

### 4.2 ⚠️ 核心 Bug：`need_base_station` 过滤不匹配
```python
all_projects = Project.query.filter(
    Project.need_base_station.in_(["高", "中"])   # ← 模型定义允许 高/中/低/无
).order_by(...).all()
```
- **模型定义**（`database/models.py` L98）：`need_base_station` 注释为 `高/中/低/无`。
- **实际入库数据**：AI 管线写入的是 **`"有"` / `"无"` / `"待核实"`**（约 184 条 `"有"`）。
- **后果**：`/api/report-data` 在 Flask 环境下几乎查不到记录（仅命中个别 `高`/`中`），report2 拿到约 **4 条**即停，不触发静态兜底 → 报告显示严重缺数，与静态 340 条口径完全割裂。
- **修复建议（推荐方案 C）**：
  ```python
  # A. 最小改动：放宽过滤
  Project.need_base_station.in_(["有", "高", "中"])
  # B. 规范入库：管线写入时把"有"映射为"高"（改动大、需回刷历史）
  # C. 推荐：与导出脚本口径统一，直接按预警级别筛
  Project.warning_level.in_(["红色预警", "黄色预警"])
  ```
  > 方案 C 与 `scripts/export_dashboard_db.py`（按 `warning_level` 统计红/黄）口径一致，且 `warning_level` 字段质量稳定，应作为 report2 唯一权威过滤条件；`need_base_station` 仅保留为展示字段。

### 4.3 聚合输出字段
`summary` / `district_ranking`(Top10) / `timeline`(按月) / `warning_pie` / `type_pie` / `stage_pie` / `project_list`(全字段：`name/district/type/stage/priority/score/warning/investment/scale/date/url/location/content/base_station_type/...`)。

---

## 5. 关键问题汇总与改进建议

| 优先级 | 问题 | 影响 | 建议 |
|---|---|---|---|
| **P0** | `need_base_station in ["高","中"]` 与实际值 `"有"` 不匹配 | report2 在 Flask 模式仅显 ~4 条，与静态 340 条割裂 | 改按 `warning_level in ["红色预警","黄色预警"]` 过滤（方案 C） |
| **P1** | 大屏地图慢/偶发空白 | 公共瓦片无 SLA + CDN 串行 + echarts 同步阻塞 | 自托管 Leaflet + 图表库、`defer` 异步、本地瓦片缓存 |
| **P1** | 双数据源口径不一致 | 大屏 340 / report2 静态 340 / Flask API ~4 | 统一以 `warning_level` 为权威口径，API 与导出脚本一致 |
| **P2** | 统计双口径（开发区并入福山 vs 柱状图独立） | 同一屏数字可能"对不上" | 统一口径并在图例注明 |
| **P2** | report2 `#embedded-data` 死代码 | 注释称"接入数据库后删除"，实际未清理 | 删除死分支，简化加载链 |

**额外建议**：`/api/report-data` 增加 `?period=week|month|year` 参数，使后端聚合与前端的"本周/本月/今年"周期切换对齐，避免前后端统计口径漂移。

---

## 6. 数据契约速查

**前端静态 JSON（`frontend/data/`）**
- `dashboard_data.json` ≡ `report_data.json`（1.4MB，340 条，同时间戳，内容相同）。
- `workbuddy.json`（481KB，230 条全字段，地图详情匹配用）。

**`project_list` 项关键字段（前后端同构）**
`name / district / type / stage / warning / priority / date / url / investment / scale / location / content / base_station_type / coverage_area / ai_reason / ai_summary / is_valuable / processed_status`

**口径备注**：当前 `dashboard_data.json` 显示 `district_count: 16`（含烟台保税港区、黄渤海新区等命名），与新人汇报中"14 区县"为不同数据集（workbuddy2.json 144 条）的统计口径，引用时需注意区分来源。
