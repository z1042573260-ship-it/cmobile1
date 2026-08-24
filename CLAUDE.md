# 建设项目信息爬虫系统

烟台及周边地区的政府公告/招标信息爬虫，自动抓取建设项目公告，通过加权评分筛选出大型建设工程项目。

## 项目结构

```
├── crawler/
│   ├── cms_api.py                     # 大汉JCMS CMS API 共享客户端 ⭐
│   ├── spiders/
│   │   ├── base_spider.py             # 爬虫基类（_get/_post/_build_url/_parse_date/_sleep）
│   │   ├── yantai_districts.py        # 烟台13区县政府公告 ⭐ 主力（466条）
│   │   ├── yantai_bidding.py          # 烟台公共资源交易网
│   │   ├── yantai_planning.py         # 烟台自然资源和规划局
│   │   ├── yantai_investment.py       # 烟台投资促进中心
│   │   ├── shm_news.py                # 上海建工集团新闻
│   │   ├── shandong_transport.py      # 山东省交通运输厅
│   │   └── shandong_zbxx.py           # 山东省招标信息
│   ├── relevance_scorer.py            # 相关性评分引擎（Layer 0/1/2 单例）
│   └── scheduler.py                   # 自动化管线（7个工作中爬虫）
├── scripts/
│   ├── test_spider.py                 # 爬虫调试入口
│   ├── review_data.py                 # 数据审核 + Excel导出
│   ├── aggregate.py                   # 多源汇总去重层（JSON + Excel + DB → 统一JSON）
│   ├── run_pipeline.py                # 🆕 一键管线（汇总→AI分析→JSON+Excel输出，无需DB）
│   ├── export_results.py              # 🆕 AI结果→格式化Excel导出
│   ├── find_api.py                    # CMS API 探测工具
│   └── seed_data.py                   # 种子数据
├── processor/
│   ├── doubao_client.py               # 豆包 API 客户端（OpenAI兼容）
│   ├── ai_pipeline.py                  # ⭐ 统一AI情报分析管线（基站+商机，一次调用）
│   ├── ai_processor.py                # AI技术分析（薄封装，委托给 ai_pipeline）
│   └── business_analyzer.py           # AI商机分析（薄封装，委托给 ai_pipeline）
├── data/spider_test/                  # 爬虫测试结果（JSON + Excel审核表）
├── config/settings.py                 # 全局配置
├── database/                          # SQLAlchemy 数据层
└── notifier/                          # 邮件通知
```

### 共享模块说明

| 模块 | 用途 | 使用者 |
|------|------|--------|
| `crawler/cms_api.py` | 大汉CMS API调用 + 详情页提取 | yantai_districts, yantai_planning, yantai_investment |
| `crawler/spiders/base_spider.py` | 基类：Session管理、URL构建、日期解析、重试 | 全部爬虫 |
| `crawler/relevance_scorer.py` | 三层评分引擎（单例） | 全部爬虫 |
| `scripts/aggregate.py` | 🆕 多源汇总去重（JSON/Excel/DB → 统一JSON） | AI分析管线 |
| `processor/doubao_client.py` | 豆包API客户端 | ai_pipeline, ai_processor, business_analyzer |
| `processor/ai_pipeline.py` | ⭐ 统一AI情报分析（一次调用输出基站+商机） | scheduler, 手动调用 |

## 爬虫清单

### ✅ 正常工作（7个）

| # | 爬虫名称 | 数据源 | 最新结果 | 说明 |
|---|---------|--------|----------|------|
| 1 | `yantai_districts` | 烟台13区县政府公告 | **466条** | 主力爬虫，大汉JCMS CMS API |
| 2 | `yantai_bidding` | 烟台公共资源交易网 | 70条 | 招标公告/中标公示 |
| 3 | `yantai_planning` | 烟台自然资源和规划局 | 43条 | 用地/规划/工程许可 |
| 4 | `yantai_investment` | 烟台投资促进局 | 28条 | 招商项目 |
| 5 | `shm_news` | 上海建工集团 | 25条 | 公司新闻/项目公告 |
| 6 | `shandong_transport` | 山东省交通运输厅 | 4条 | 交通工程招标 |
| 7 | `shandong_zbxx` | 山东省招标信息 | 5条 | 省级招标公告 |

### ❌ 失效（4个）

| # | 爬虫名称 | 原因 | 原网址 |
|---|---------|------|--------|
| 1 | `landchina` | 中国土地市场网反爬升级 | https://www.landchina.com/ |
| 2 | `shandong_approval` | 山东省审批平台改版 | https://tzxm.shandong.gov.cn/ |
| 3 | `yantai_epb` | 烟台生态环境局网站改版 | https://hbj.yantai.gov.cn/ |
| 4 | `ybb` | 云办公平台接口失效 | https://www.ybb.com/ |

## 核心脚本

### `test_spider.py` — 爬虫调试
```bash
python scripts/test_spider.py                    # 列出所有爬虫
python scripts/test_spider.py yantai_districts   # 测试单个爬虫
python scripts/test_spider.py all                # 测试全部爬虫
```
结果保存到 `data/spider_test/<spider_name>_<timestamp>.json`

### `review_data.py` — 数据审核
```bash
python scripts/review_data.py <JSON文件>               # 交互式逐条审核
python scripts/review_data.py <JSON文件> --export-excel # 导出Excel审核表
python scripts/review_data.py <JSON文件> --approve      # 批量写入数据库
```

## 相关性评分引擎（`relevance_scorer.py`）

三层过滤体系：

- **Layer 0**: 流程公告过滤（`is_process_announcement` / `is_result_announcement`）
  - 过滤"更正"、"废标"、"流标"、"终止"、"澄清"等流程性公告
  - "变更"只用招标/采购上下文组合词（招标变更、采购变更、中标变更等），避免误伤"工程变更公告"
- **Layer 1**: 标题加权评分（`score_title`）
  - 正向信号 +5~+1（施工总承包、产业园、开工等）
  - 负向信号 -5~-1（设备采购、法律服务、绿化养护等）
  - 规模信号 +3~+1（亿元、万㎡、公里等）
- **Layer 2**: 详情页内容分析（`extract_content_info`）
  - 提取：规模 / 投资额 / 区县 / 项目性质（新建/扩建/改造）

## yantai_districts 爬虫详情

### 技术架构
- 13区县统一使用大汉JCMS/JPAAS政府CMS
- 通过 `/api-gateway/jpaas-publish-server/front/page/build/unit` API 分页获取列表
- 4种 HTML 列表变体（Variant A/B/C/D），不同区县使用不同选择器

### 13区县配置

| 序号 | 区县 | 域名 | list_variant | date_in_list | 备注 |
|------|------|------|-------------|-------------|------|
| 1 | 海阳市 | haiyang.gov.cn | C | ✅ | 日期在 span.bt-data-time |
| 2 | 福山区 | ytfushan.gov.cn | B | ✅ | |
| 3 | 牟平区 | muping.gov.cn | B | ✅ | |
| 4 | 莱阳市 | laiyang.gov.cn | B | ✅ | |
| 5 | 芝罘区 | zhifu.gov.cn | B | ✅ | |
| 6 | 莱山区 | ytlaishan.gov.cn | B | ✅ | |
| 7 | 栖霞市 | sdqixia.gov.cn | B | ✅ | URL带query参数 |
| 8 | 高新区 | ytgxq.gov.cn | B | ✅ | tagId需fallback |
| 9 | 开发区 | yeda.gov.cn | B | ✅ | URL带query参数 |
| 10 | 招远市 | zhaoyuan.gov.cn | B | ✅ | |
| 11 | 莱州市 | laizhou.gov.cn | A | ✅ | li.bt-main-r-ul-li |
| 12 | 蓬莱区 | penglai.gov.cn | B | ✅ | |
| 13 | 龙口市 | longkou.gov.cn | **D** | ❌ | **列表无日期，需从详情页提取** |

### 已修复的关键Bug

1. **变更关键词误伤**（2026-07-23）
   - `is_process_announcement` 中"变更"单独太宽泛，误伤"建设工程规划许可证变更批后公布"
   - 修复：只用招标/采购上下文的组合词（招标变更、采购变更等）

2. **翻页过早停止**（2026-07-23）
   - `len(articles) < PAGE_SIZE` 在29条时误判为末页，漏掉第4页
   - 修复：改用 `len(articles) == 0` + API total 计算 `max_pages`

3. **tagId 缓存**（2026-07-23）
   - 高新区每页都做 tagId fallback（2次API调用×84页）
   - 修复：首页探测后缓存到 `cfg["_effective_tag_id"]`

4. **龙口日期跨行**（2026-07-23）
   - 龙口详情页 `span.time` 日期被换行符分割（`2026-\n07-\n23`），正则无法匹配
   - 修复：`_parse_date` 和 `_fetch_detail` 匹配前先 `re.sub(r'\s+', '', text)`

### 最新结果（2026-07-23）

| 区县 | 条目 | 高质量 | 中等 | 低质量 |
|------|------|--------|------|--------|
| 海阳市 | 186 | — | — | — |
| 莱州市 | 55 | — | — | — |
| 龙口市 | 46 | 17 | 9 | 20 |
| 开发区 | 44 | — | — | — |
| 高新区 | 44 | — | — | — |
| 芝罘区 | 25 | — | — | — |
| 牟平区 | 22 | — | — | — |
| 莱阳市 | 19 | — | — | — |
| 栖霞市 | 11 | — | — | — |
| 招远市 | 9 | — | — | — |
| 蓬莱区 | 3 | — | — | — |
| 莱山区 | 2 | — | — | — |
| 福山区 | 0 | — | — | — |
| **合计** | **466** | | | |

## 自动化管线（`scheduler.py`）

### 数据流（四层架构）

```
Layer 1: 采集       Layer 2: 汇总         Layer 3: 分析            Layer 4: 输出

7个爬虫              aggregate.py         ai_pipeline.py          JSON → 前端大屏
  ↓                   收集（不去重）       统一AI深度推理            DB → 持久存储
spider.run()          ↓                   一次调用输出:            Excel → 人工审核
  ↓                  merged.json           基站需求 + 商机情报      Email → 邮件通知
list[dict]            ↓                    ↓
                   JSON直传（测试）       unified_intelligence.json
                   或 DB（正式）          unified_intelligence.db
```

### 统一 AI 分析管线（`ai_pipeline.py`）⭐

| | 旧（两条管线，各调一次） | 新（统一管线，一次调用） |
|---|---|---|
| **调用次数** | 2次/项目 | **1次/项目** |
| **AI 角色** | 数据核查员（被动提取） | **情报分析师（深度推理）** |
| **搜索** | mock 假数据 | **不需要**（爬虫=政府官网，权威数据源） |
| **输出** | 分开输出 | 一次输出全部：基站需求 + 商机情报 |
| **温度** | 0.1 / 0.0 不一致 | 统一 0.0 |

### AI Prompt 设计

AI 扮演 20 年经验的通信基础设施情报分析师，三步推理：
1. **项目本质理解** — 从公告推断类型/规模/阶段/建设方
2. **基站技术评估** — 技术原理判断（地下室→室分，高层→宏站+室分，园区→宏站）
3. **商机情报分析** — 推断通信需求、识别建设方、判断跟进时机

### scheduler.py 管线步骤（4步）

```
scheduler.py run_pipeline()
  ├── Step 1: 运行所有爬虫 → DB (raw_projects)
  ├── Step 2: 汇总（不去重，AI 判断） → merged_for_ai.json
  ├── Step 3: AI 统一情报分析 (ai_pipeline.py) → unified_intelligence.json + .db
  └── Step 4: 邮件通知
```

### 测试阶段 JSON 直传（无需DB）⭐ 推荐

```bash
# 一键命令：Excel/JSON → 汇总 → AI 分析
python scripts/run_pipeline.py --from-excel "data/spider_test/*审核表*.xlsx"
python scripts/run_pipeline.py --from-json "data/spider_test/yantai_districts_merged.json"
python scripts/run_pipeline.py --from-json "data/spider_test/*.json" --from-excel "data/spider_test/*审核表*.xlsx"
```

7个爬虫按优先级顺序执行：

```
YantaiDistrictsSpider      # 1: 烟台13区县政府公告（466条，主力）
YantaiPlanningSpider       # 2: 规划许可公示（43条）
YantaiBiddingSpider        # 3: 施工招标（70条）
YantaiInvestmentSpider     # 4: 招商项目（28条）
ShmNewsSpider              # 5: 上海建工集团新闻（25条）
ShandongTransportSpider    # 6: 山东省交通运输厅（4条）
ShandongZbxxSpider         # 7: 山东省招标信息（5条）
```

## 已完成的代码整理（2026-07-24）

1. **提取 `crawler/cms_api.py`** — 3个爬虫中重复的CMS API调用封装为共享模块
2. **`_build_url()` 提到 BaseSpider** — 消除5个爬虫中的重复URL构建逻辑
3. **`_parse_date()` 提到 BaseSpider** — 日期解析统一，继承龙口换行修复
4. **`scheduler.py` 加入 yantai_districts** — 自动化管线补上主力爬虫

## 🆕 统一 AI 情报分析管线（2026-07-24）

1. **创建 `scripts/aggregate.py`** — 多源汇总层
   - 支持 JSON / Excel审核表 / DB 三种输入混用
   - 不做程序去重（数据来源多样，交给 AI 判断）
   - 输出统一JSON + Excel
2. **创建 `processor/ai_pipeline.py`** ⭐ — 统一AI情报分析管线（核心）
   - 一次豆包 API 调用同时输出基站技术评估 + B2B商机情报
   - AI 角色：通信基础设施情报分析师（深度推理，非被动提取）
   - Temperature=0.0，区分"专业推理"和"事实确认"（不确定标注"待核实"）
   - 不需要外部搜索（爬虫数据来自政府官网，本身权威）
   - 30+ 字段完整覆盖两个维度
3. **`processor/ai_processor.py`** / **`processor/business_analyzer.py`** → 改为薄封装
   - 保留旧接口（向后兼容），内部委托给 `ai_pipeline.py`
4. **更新 `scheduler.py`** — 合并 Step 3+4 为单步（统一 AI 分析）
5. **更新 `config/settings.py`** — 补充统一输出路径

## 前端大屏（`frontend/`）

烟台 3D 地图大屏（Three.js，非爬虫）：

- 入口：[index.html](frontend/index.html) → [js/map.js](frontend/js/map.js) → [js/three-map.js](frontend/js/three-map.js)（`YantaiMap3D`，实例暴露为 `window.yantaiMapChart`）
- 地图主体（BaseMap/ExtrudeMap/Line）在 [js/lib/mini3d.js](frontend/js/lib/mini3d.js) 中**统一对投影 y 取反**（`-y`，北=上方）；地图平铺在世界 XZ 平面（`mapGroup.rotation.x = -π/2`）
- **高德街道瓦片引擎** [js/gaode-tiles.js](frontend/js/gaode-tiles.js)（`window.GaodeTiles`）：Web Mercator XYZ 瓦片数学 + 拉取/拼接/缓存，**无需 key**（`webrd0{1-4}.is.autonavi.com` raw 瓦片，CORS `*`）
- **街道贴图 = 高德瓦片窗口**（热力图 `_heatLayer` / 下钻 `_streetLayer`）：
  - **城市总览（dist>12）用静态 `yantai.jpg`**（1 次请求、即时高清，零瓦片延迟）；**贴近（dist≤12）切实时高德瓦片**，按相机视野 `_visibleGeoBBox()` + 距离选 z（`_zoomFromDistance`，上限 15），防抖 200ms 刷新 → **放大自动换更清晰瓦片**；瓦片数上限 256（`_fetchTileCanvas`，返回实际瓦片范围 `res.bbox` 供精确对齐）；失败回退静态
  - `_finishStreetLayer` 支持 `imgRange`：瓦片画布按 pxs 地理定位（平面/遮罩/纹理共用同一映射 → 严格对齐不拉伸）
  - 街道图上**叠加青色区县界限描边**（每区县边界清晰可见）
  - 贴图**淡入过渡**（0.35s）；下钻时贴图平面与区县 GSAP **同步放大**（紧贴 3D 板）
- **预警点交互**（[map.js](frontend/js/map.js) 的 `map_points`，红/黄散点）：点击 → 信息卡片（项目名/区县/类型/阶段/预警等级）→ "查看街道" → 切到 **2D 高德地图**定位到该点街道级
- **2D 在线高德地图**（[js/gaode-map-2d.js](frontend/js/gaode-map-2d.js)，`window.GaodeMap2D`）：Leaflet + 高德瓦片（无需 key），**无独立按钮**，通过预警点卡片"详情"进入；点标记 → 卡片 → "详情" `flyTo(z16)`；**可自由平移/缩放**查工业园/具体街道；"返回 3D"按钮（fixed 顶层）+ 3D 模式按钮点击返回
- **返回定位逻辑**：3D 实例注册 `GaodeMap2D.onEnter/onExit` —— 进入 2D 前捕获相机/目标/下钻状态，返回时恢复 → **回到选中区县**（下钻状态保持，实测相机精确恢复）
- **预警图模式 = 3D 图钉**（`_warningPins`，同坐标去重后 8 个，仅预警图模式显示，隐藏 Sprite 散点）：
  - 样式：倒水滴（ExtrudeGeometry+中心圆孔，无发光壳）+ 地面扩散光圈（Shader 波纹）+ 悬浮胶囊标签（参考柱状图标签样式，**hover 才上浮**，背景半透明，无计数）
  - **尺寸可调**：`this._pinConfig`（pinScale 水滴大小 / rippleSize 光圈直径 / rippleGap 波纹间距 / labelScale 标签缩放），改完 F5 生效
  - **底座贴地图表面**（图钉组 z=0.83=贴图表面，水滴底座 z=0 与波纹同平面，不悬空）；上下微漂浮动画
  - **下钻时区县内图钉 GSAP 动画跟随区县放大**（`_repositionPinsForDrill`，与区县缩放同 duration/ease，点位精确；注意 Box3 世界中心 `center.z=geoY`，本地 y 缩放用 `-center.z + (o.y+center.z)*sxy`）；区县外图钉隐藏；**返回时区县恢复原位后再显示+淡入**（`_flyBackCity` onComplete）
  - **点击用屏幕距离判定**（`_pinAtScreen`，阈值 44px，比 3D 射线稳定）→ 卡片；卡片定位在**图标右侧**；不触发区县下钻
  - 预警图隐藏：Sprite 散点 / 莱山飞线 / 聚焦光圈 / 区县名标签（干净地图）
  - 柱状图/热力图仍用原 Sprite 散点（呼吸/射线逻辑未动）
- 卡片按钮为"详情"（3D Sprite 散点卡片与 2D 标记卡片统一）→ 进入 2D 定位
- 3D 贴图纹理已加**各向异性过滤**（`renderer.capabilities.getMaxAnisotropy()`）
- 三模式切换：柱状图 bar / 热力图 heat / 预警图 warning（`.bottom-menu-item`）；热力图模式 = 高德瓦片街道窗口
- 地图在 XZ 平面：`geoProject(lng,lat) → 世界(x, -y)`；反算 `projection.invert([x, -z])`
- 本地预览：`cd frontend && python -m http.server 8000` → http://localhost:8000

### 已修复的关键Bug

1. **贴图不显示：Y 轴未取反导致高度塌缩**（2026-08-07）
   - `_finishStreetLayer` 用原始投影 y 且假设 `yMax > yMin`，而地图 mesh 用 `-y`
   - 实测 `h = yMax - yMin = -19.73` → `Math.max` 塌成 `1e-6` → 平面 17.4 宽 × 0 高（不可见线），热力图和下钻贴图**全部不显示**
   - 修复：y 取反对齐地图（`yTop = -yNorth`）+ 修正 h 符号 + `pxs` 遮罩映射翻转
   - 注：控制台 `Failed to load resource: 404` 只是 `/favicon.ico`，与贴图无关
2. **`_visibleGeoBBox` 纬度范围取反**（2026-08-07，瓦片窗口期）
   - 投影不取反 Y（纬度越大 y 越小）→ `degPerUnitY` 为负 → 返回的 bbox `minLat > maxLat` → 瓦片窗口高度塌成 1e-6
   - 修复：单位跨度取绝对值（`Math.abs`）
3. **高德瓦片与地图错位**（2026-08-07）
   - 瓦片画布覆盖"网格取整的瓦片范围"（z10 全市 17×10=170 张，aspect 1.70），但贴图平面覆盖"可见 bbox"（aspect 1.79）→ 画布被拉伸压扁 ~5% → 街道与区县边界错位
   - 修复：`_fetchTileCanvas` 返回实际瓦片网格范围 `res.bbox`；`_finishStreetLayer` 新增 `imgRange` 参数，瓦片画布按 pxs 精确定位（不无脑拉伸）——平面/遮罩/纹理共用同一地理映射，严格对齐
   - 缩放防抖 400→200ms，瓦片刷新更跟手（高德手感）
4. **下钻图钉位置偏移**（2026-08-07，预警图 3D 图钉）
   - `_repositionPinsForDrill` 用 Box3 世界中心缩放图钉时误用 `center.y`（高度）做地理轴缩放，且符号反了 → 图钉偏出区县、射线打空
   - 修复：Box3 世界中心 `center.z = geoY`（地图组旋转后 worldZ=-localY=geoY）；本地 y 缩放公式 `-center.z + (o.y + center.z)*sxy`
   - 图钉点击弃用 3D 射线，改走 HTML 胶囊标签 `onclick`（更稳，且不影响柱状图区县下钻射线）

## 截止日期

爬虫使用 `START_DATE = "2026-05-01"` 作为最早爬取日期。所有早于此日期的公告会被跳过。

## 环境要求

- Python 3.7+
- 依赖：scrapy, requests, beautifulsoup4, openpyxl, lxml, loguru
- 不使用系统代理（`session.trust_env = False`）
