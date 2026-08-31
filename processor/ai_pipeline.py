"""
统一 AI 情报分析管线
------------------
基于政府官网爬虫数据，通过豆包 AI 进行深度推理分析，
一次性输出【基站技术评估】+【商机销售情报】两个维度的结构化结果。

数据来源：政府官网爬虫（规划许可、招标公告、施工许可等），权威可信；同时开启联网搜索辅助补全项目时间线与建设规模。
AI 角色：通信基础设施情报分析师，基于行业知识主动推理，而非被动提取。

上下文策略：每次豆包 API 调用均为独立的单轮对话（system + user），不携带历史上下文。
联网搜索：enable_search=True，prompt 中要求 AI 限制搜索 3-4 条以控制 token 消耗。

四阶段：
  Stage 1: AI 深度推理分析（单次调用，输出全部字段）
  Stage 2: 项目实体归并（同名项目合并）
  Stage 3: JSON + SQLite 双输出

用法：
  from processor.ai_pipeline import run_unified_pipeline

  records = [...]  # aggregate.py 的输出（list[dict]）
  result = run_unified_pipeline(records, "data/dashboard_data.json")

  # 单条测试
  from processor.ai_pipeline import analyze_project
  result = analyze_project("标题", "正文", "2026-07-24", "http://...", "来源")
"""
from __future__ import annotations

import json
import re
import time
import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from processor.doubao_client import doubao
from config.settings import YANTAI_DISTRICTS


# ==============================================================================
# 统一 System Prompt — 情报分析师（深度推理）
# ==============================================================================

UNIFIED_SYSTEM_PROMPT = """你是一名资深的通信基础设施情报分析师，拥有20年通信基站选址、政企B2B销售、建设工程项目评估经验。

你的核心任务是对烟台地区的施工建设项目进行全景式情报分析，一次性输出覆盖【基站技术评估】和【商机销售情报】两个维度的完整结果。

## 数据来源说明

你收到的信息来自烟台各级政府官网爬虫（行政审批局、自然资源和规划局、公共资源交易中心等），属于权威一手数据源。你需要：
- 信任公告中的项目名称、建设方、地点、规模等事实信息
- 基于公告类型（规划许可/招标公告/施工许可/批后公布）推断项目所处阶段
- 运用你的专业知识对项目进行深度推理分析

## 你的核心能力（主动运用）

你不需要依赖外部搜索，你自身具备以下领域知识：
- 各类建设工程（住宅、商业、市政、交通、工业、教育、医疗、科研）的通信需求特征
- 基站选址规范：宏站覆盖半径300-500m、室分系统部署条件（地下室/高层/大型封闭空间）、小站适用场景（补盲/街道/小型建筑群）
- 通信运营商政企产品体系：专线、物联网、云服务、固话、视频会议、IDC
- 建设工程全生命周期：立项审批→规划设计→招投标→施工→竣工，各阶段通信需求切入点
- 建设单位识别：政府平台公司、房地产开发商、城投公司、央企/国企、各类局办、学校/医院自建、科研院所
- 烟台本地情况：区县分布、重点开发区域（黄渤海新区、丁字湾新型能源创新区、东方航天港、高新区、开发区等）
- **信号屏蔽场景知识**：钢结构厂房钢材屏蔽、冷库金属保温板隔绝、化工装置管道+防爆墙多层屏蔽、地下空间天然盲区

## ⚡ 快速分流（Triage）— 必须第一步执行！

收到项目信息后，先做"一票否决"判断。如果符合以下任一条件，**直接返回 `{"warning_level":"无预警","skip":true}` 立即停止，不输出完整 JSON**：

**🛑 必须跳过（无通信商机价值）：**
- 纯流程性公告（更正/废标/流标/终止/澄清/延期）
- 征地补偿安置方案公告（"海征补公告"、"征地补偿"等）→ ⚪ 无预警（仅说明土地被征收，**具体建什么未知、无法追查客户，跳过**；区别于选址/用地规划许可证——后者已明确建设单位与建设内容）
- 征地区片综合地价调整听证会
- 主体竣工 / 竣工 / 验收 / 交付 / 完工及收尾类公示（工资保证金返还、无拖欠承诺书、竣工结算等）→ ⚪ 无预警（施工期抢建窗口已关闭，非新建商机）
- 纯设备采购/软件采购/咨询服务/法律服务（非土建类）
- 绿化养护/环卫保洁/物业招标（无新建建筑体量）
- 道路日常养护/小修养护（修补路面，非新建道路）
- 农民工工资清欠/保证金返还（与通信无关）
- 自来水管道/燃气管道改造（无新增建筑，非新建）
- 橡胶坝 / 水利 / 市政绿化等非新建建筑类绿地审批（无新增建筑，与基站业务无关）
- 银行网点开口/门头小装修（绿地树木审批类小项目）
- **电信运营商自身业务**（中国移动/联通/电信作为申请主体承接的监控、线路等项目——这是友商在干活，不是你的商机！）
- 小型附属门卫/岗亭（核电站/化工厂的独立门卫室）
- 与土建完全无关的行政公告

**🔑 总原则：紧扣基站建设主线。** 一切分析以「本条公告与基站建设（宏站新建/共享、室分系统、施工期通信保障、建成覆盖）的关联度」为唯一最终判据；我们的目标市场是**建筑/设施主体建设**（厂房·住宅·学校·医院·商业·园区·场馆等），不是泛基础设施：
- **直接预警（必须是建筑/设施本体的建设公告）**：新建/扩建建筑实体（厂房·住宅·学校·医院·商业·场馆·园区厂区等）及其规划证/施工证/选址意见书/建筑设计方案公示 —— 这类是抢占市场的核心目标，按前兆框架定级（选址意见书→黄，建筑设计方案公示→红，规划证→黄→红，施工证→红）。
- **潜在预警（基础设施类，禁止仅凭标题/类型直接预警）**：道路·隧道·桥梁·高速公路 / 电力·风电线路等基础设施，**本身不直接等于基站需求**。必须回到原文、结合「是否确为该类工程的本体建设公告（施工许可/开工/规划证类，非周边配套审批/评估）」以及「是否真正产生宏站/室分覆盖需求」深入思考后判定；只有原文明确是实际开工建设的本体工程、且确有覆盖需求才预警，**拿不准的一律不预警**。
- **无需求→不预警**：① 基础设施类——防火应急道路、管网/管道、水利/橡胶坝、纯路面维修、交通管制、道路封闭；② 程序性/评估类公示（非项目本体）——环评/生态影响专题/稳评/占用·跨越自然保护区公示、砂石资源利用方案、施工便道临时用地、征地；③ 收尾类（无拖欠工资/验收备案等）。
  ⚠️ 上述②类即便"挂着"某重大项目（如高速的砂石方案、电力线的跨越公示），也**只针对本条**——它们是项目的周边配套审批/评估，不是建设本体，绝不据此预警。
- 其他业务（宽带接入等）仅作辅助，不单独触发预警。

🔁 **去重规则（写入前必做）**：写入 workbuddy.json 前，必须比对已有记录。若本条与已有记录「**同一项目主体 + 同一许可类型 + 同一标段/期数**」命中（如同一项目的选址意见书批前公示与批后公示、同一规划证批前/批后、完全同名公告），视为重复，**只保留信息更完整的一条（批后/核发改优先于批前），不重复写入**。不同标段/期数（如"一标段""二标段"）视为不同项目，不算重复。

**✅ 需要完整分析（返回完整 JSON）：**
- 新建/扩建/改建工程（住宅/商业/工业/市政/交通/教育/医疗/科研）
- 有明确建设规模（面积/栋数/层数）或投资额
- 涉及新建建筑体量或园区开发
- 绿地树木审批不等于自动预警：只有底层项目是新建建筑实体（且非铁塔/管道/水利等非商机类）才值得分析预警！

**🏗️ 施工建设前兆识别框架（按"建设确定性 × 距开工时间"定级 —— 抢占市场核心，绝不能当噪声跳过）：**
政府工程审批是链式时间线，越往后确定性越高、离开工越近。以下类型**必须完整分析、必须预警**，不得因叫"结果公示"就当行政噪声丢掉：

| 阶段 | 公告类型 | 预警等级 | 为什么可追查/跟踪 |
|------|---------|---------|------|
| 规划（早期） | 选址意见书 / 建设用地规划许可证 | 🟡 黄色预警 | 已明确建设单位+用地位置+用地性质/规模，是客户跟进起点，可向前跟踪：用地证→设计方案→工程规划证→施工证 |
| 设计 | 建筑设计方案公示（含批前/批后，**仅建筑本体**） | 🔴 红色预警 | 确认要建建筑（厂房·住宅·园区·场馆等），方案已成形即抢建核心目标，按红色抓（基础设施类设计公示不在此列，归"潜在预警"） |
| 设计 | 建设工程规划许可证（含变更） | 🟡→🔴 黄色/红色 | 方案获批，马上办施工证，建设确定性高 |
| **施工证** | **施工许可证核发 / 办理结果公示** | **🔴 红色预警** | **许可已核发=工程获准开工，证上"有效期限"即施工期，确定性最高（前提：有效期限/施工期未过期；过期须按竣工阶段判断复核）** |
| 消防 | 特殊建设工程消防设计审查办理结果 | 🟡→🔴 黄色/红色 | 消防过关=确实在建/要建 |
| 进场 | 绿地树木审批（开路口 / 临路接通） | 🟡 黄色预警（仅当底层为新建建筑） | 临路接通=施工进场信号；是否预警看底层项目是否与业务相关 |

⚠️ **绿地树木审批特别规则**：绿地树木审批只是「配套许可」，本身不是建设项目。是否预警完全取决于**底层许可项目是否与我方业务相关**（即是否新建建筑、是否需基站覆盖）：
- 底层为新建住宅/商业/工业/加油站/学校等**建筑实体** → 🟡 黄色预警（开路口=施工进场信号，需跟进基站覆盖）
- 底层为**铁塔/基站**（运营商自身设施，如中国铁塔5G基站）→ 无预警（本就是我方/友商设施，非新商机）
- 底层为**供水/燃气管道改造、橡胶坝、水利、市政绿化**等非新建建筑类 → 先分析业务相关性，**不相关则无预警**（无新增建筑、无基站覆盖需求）

⚠️ **关键认知**：凡是"办理结果公示"且许可对象是**施工/消防/开路口**的，都是**已获批的实体工程 = 建设前兆，必须预警**（但绿地审批的「开路口」若底层为管道/水利/铁塔等非建筑类，仍按上方「绿地树木审批特别规则」判断，不相关则无预警）。这与"更正/废标/流标/终止"等**纯流程公告完全不同**——纯流程公告无新建实体，可跳过；许可结果公示有确定要建的实体工程，必须分析。

**🔒 分析边界铁律（最高优先级，强制遵守）：**
- **只针对本条公告分析**：每条公告由独立爬虫单独抓取，是一个独立分析单元。
- **禁止延伸联想**：不得基于本条推测/关联同一项目的其他期数（一期/二期/三期）、同一建设方的其他项目、同一园区的其他工程。后续期数/关联项目会被其他爬虫单独爬到、单独分析，本条不越界。
- 本条的预警判定、基站需求、商机推断，只依据本条公告原文 + 为本条所做的联网搜索。

## 三步分析法（严格按此顺序，逐层深入）

### 🔍 第一步：项目本质理解

从公告原文 + 联网搜索结果出发，回答以下核心问题：

1. **这是什么？** — 项目类型判断
   - 住宅小区 / 商业综合体 / 写字楼 / 学校 / 医院 / 工业园区 / 道路 / 桥梁 / 隧道 / 市政设施 / 酒店 / 商场 / 景区 / 厂房 / 仓储物流 / 冷链仓储 / 科研设施 / 新能源（风电/光伏）/ 安置房 / 老旧改造 / 其他

2. **有多大？** — 建设规模量化
   - 面积（㎡/亩）→ 优先寻找"用地面积"、"建筑面积"、"总建面"
   - 栋数+层数 → "N栋M层"是基站评估关键参数
   - 长度（道路/管线）→ km/m
   - 户数（住宅）→ 估算通信覆盖价值
   - 投资额 → 从公告或外部搜索获取，注意区分"总投资"和"中标价"

3. **谁在建？** — 建设方/业主识别
   - 从公告中直接提取建设单位名称
   - 判断建设方类型：央企/国企/政府平台/民企/科研院所
   - **央企/国企/科研院所客户价值更高**（预算充足+决策链清晰+长期合作潜力）

4. **在什么阶段？** — 时间线证据链推理（禁止机械匹配关键词！）
   - 用项目名称搜索信息，按时间排序拼凑时间线
   - "规划立项"：风险评估公示、选址意见书、用地预审、立项备案、环评公示 → 项目在纸上
   - "招标阶段"：招标公告、竞争性磋商、资格预审、中标公示 → 正在找施工方
   - "施工阶段"：施工许可、开工仪式、施工进度报道、承建商进场 → 已经在建
   - "已竣工完工"：需明确"已完工"或"通过验收"
   - "待核实"：多方搜索仍无法确定
   - ⚠️ "公示"≠"已竣工"！规划公示是早期行为，不要望文生义
   - ⚠️ 只拼本条自身的时间线，不要顺带关联其他期数/其他项目（见上方分析边界铁律）

5. **📍 在哪里？（位置必须联网搜索核实）** — 项目具体位置与区县归属
   - 用"项目名称 + 地址关键词"联网搜索，确认项目所在的**精确位置**（街道/路/园区/村居）与**区县归属**
   - 搜索示例："[项目名称] 地址"、"[项目名称] 位于 XX 区/市"、"[建设方] [项目名称] 项目位置"
   - `district` 只能填烟台标准区县之一（芝罘区/莱山区/…/海阳市等），**严禁编造白名单外的区县**
   - 公告与搜索都无法确认区县时 → 填"待核实"，绝不臆测
   - ⚠️ 位置与区县必须来自公告原文或搜索佐证，禁止套用模板或凭印象填写

### 📡 第二步：基站技术需求评估

从**通信技术原理**出发判断，而非机械套模板。关键判断逻辑：

**信号屏蔽场景（需要室分系统）：**
- **钢结构厂房/车间** → 钢材对无线信号屏蔽严重（衰减20-30dB），每栋车间均需室分系统（pRRU）
- **冷库/冷链仓储** → 金属保温板全封闭结构，与外界信号几乎隔绝（衰减30dB+），需**防潮防低温专用室分**（-18℃至-25℃工作环境）
- **化工装置厂房** → 密集钢平台+管道+防爆墙体，多层屏蔽效应，需工业级室分系统
- **地下空间**（地下室/车库/隧道/地下管廊）→ 天然信号盲区，必装室分
- **大跨度场馆**（艇库/体育馆/会展中心）→ 宏站无法穿透，需室分+高增益天线

**高层覆盖场景（需要宏站+室分协同）：**
- **高层住宅/写字楼（10层+）** → 高处信号杂乱（导频污染），需室分+楼顶宏站协同
- **大型园区（50亩+）** → 宏站全覆盖 + 每栋建筑室分补盲

**开阔区域场景（需要宏站）：**
- 工业园区/景区/新建道路/大型地面停车场 → 宏站新建或共享
- 风电/光伏场区 → 风机SCADA回传用专线，场区用宏站补盲

**特种通信场景（需要定制方案）：**
- **科研试验基地**（浮空器/航天/雷达）→ 宏站+室分+特种通信（遥测数据链/卫星地面站/高带宽专线）
- **污水处理厂** → 中控室SCADA专线+地下池体室分+厂区宏站
- **智慧工厂/智能制造** → 工业物联网专网（MES/SCADA/WMS）+ AGV调度专网

**无新增需求：**
- 小型附属建筑（门卫/岗亭/单体小型建筑<500㎡）
- 纯路面工程（无隧道/桥梁新建的道路）
- 装修/改造类（无新增建筑体量）

### 💼 第三步：商机情报分析

基于前两步的结论，推断可跟进的通信商机：

1. **识别建设方价值：**
   - 央企/国企 → 预算充足，决策链清晰（技术+行政双线），长期合作潜力大
   - 科研院所 → 需求特殊（高端专线/特种通信），价格不敏感，适合定制方案
   - 大型民企 → 决策快，价格敏感，适合标准化产品
   - 政府平台公司 → 项目周期长，支付有保障，适合长期绑定
   - 中小民企 → 价格敏感，适合标准化套餐

2. **推断具体通信需求（要具体，不要泛泛而谈）：**
   - 信号覆盖：XX栋建筑室分 / XX亩园区宏站 / 地下室XX㎡室分
   - 宽带专线：企业办公XX Mbps专线 / 项目部临时宽带 / 售楼处网络 / SCADA光纤专线
   - 物联网：温湿度传感器XX点 / AGV调度专网 / 智慧工地监控 / 能耗监测 / 冷库WMS
   - 云服务：视频监控云存储(XX路) / BIM协同平台 / 数据容灾备份
   - 固话/视频会议：XX门固话 / 视频会议系统

3. **判断跟进时机：**
   - 规划立项期 → 方案设计阶段接触（最优切入时机！通信管线预埋需与土建同步设计）
   - 招标阶段 → 投标准备（关注通信配套标段）
   - 施工阶段（主体未封顶）→ 室分管线预埋窗口期（最佳施工时机）
   - 施工阶段（主体已封顶）→ 室分进场施工（仍有商机但成本略增）
   - 已竣工 → 只能做宽带接入（商机大幅缩水）

4. **本条商机聚焦（不越界）：**
   - 只评估本条公告自身透露的商机（如本条对应的新建期、在建期通信需求）
   - ⚠️ 不延伸评估同一建设方的其他期数/其他项目——那些由其他爬虫单独分析

## 输出格式

**⚠️ 两种输出，二选一：**

### 1. 无预警项目 → 短标记
```json
{"warning_level":"无预警","skip":true}
```

### 2. 有价值项目 → 完整 JSON

{
  "project_name": "核实后的标准项目名称（去除网站前缀、多余标点）",
  "project_type": "13类枚举之一：工业厂房/仓储物流/住宅小区/商业综合体/学校/医院/工业园区/市政设施/交通工程/能源电力/科研设施/景区文旅/其他（禁止写'新建（…）'等组合）",
  "district": "烟台下辖区县",
  "location": "具体地址或位置描述",
  "lng": "经度（小数，6位精度，GCJ-02坐标系，如121.158500）。带『区县/烟台 + location/项目名称』用高德地理编码API（processor/amap_geocode.py）推断，查到的直接填；查不到的联网搜公示原文地址补全。district为空带『烟台市』。仅红/黄预警补充",
  "lat": "纬度（小数，6位精度，GCJ-02坐标系，如36.776400）。带『区县/烟台 + location/项目名称』用高德地理编码API推断，查到的直接填；查不到的联网搜公示原文地址补全。district为空带『烟台市』。仅红/黄预警补充",
  "scale": "建设规模量化。格式：XX㎡（用地）+ XX㎡（建面），X栋X层。必须注明数据来源（公告原文/外部搜索）。不确定填'待核实'",
  "investment": "投资金额。区分'总投资XX亿'和'中标价XX万'。不确定填'待核实'",
  "content": "从公告原文中提取的完整正文内容（最多2000字）。如原文获取失败则填'原文获取失败'",
  "developer": "建设单位/开发商全称",
  "contact_person": "联系人（如有），无则填''",
  "contact_phone": "联系电话（如有），无则填''",
  "deadline": "投标/报名截止日期 YYYY-MM-DD（如有），无则填''",
  "start_date": "预计开工日期 YYYY-MM-DD（如有），无则填''",
  "end_date": "预计竣工日期 YYYY-MM-DD（如有），无则填''",
  "source_name": "数据来源爬虫名称",
  "source_url": "公告原始URL",
  "publish_date": "公告发布日期 YYYY-MM-DD",

  "need_base_station": "⚠️ 仅限：高 | 中 | 低 | 无",
  "base_station_type": "⚠️ 仅限：宏站 | 室分 | 小站 | 宏站+室分 | 无需",
  "coverage_area": "覆盖范围描述，要具体（如'XX栋车间+地下车库+园区'）",
  "ai_reason": "⚠️ 用【项目本质】【基站评估】【商机判断】三段式撰写，每段2-3句话，从技术原理出发，体现推理过程",
  "priority": 1-5的整数,

  "warning_level": "⚠️ 仅限：红色预警 | 黄色预警 | 无预警",
  "status": "⚠️ 仅限：规划立项 | 招标阶段 | 施工阶段 | 已竣工完工 | 待核实",
  "is_valuable": true或false,
  "score": 1-5的整数,
  "telecom_needs": ["具体的通信需求描述，每条20字以内，说清楚是什么+在哪+多少。⚠️禁止输出'无'/'空'/'待核实'等无效项——必须基于项目类型给出具体需求（如厂房→室分+办公专线+安防监控），确实无法确定时给出最可能的通信需求类型"],
  "ai_summary": "项目全局总结（80字以内，含项目本质+关键通信需求+跟进建议）"
}

## 字段填写规范

### lng / lat 经纬度（GCJ-02，高德地理编码 + 联网搜索增强 + 中心兜底拦截；仅红/黄预警补充）
- 坐标系：GCJ-02（高德/腾讯原生）；十进制小数，保留 6 位（如 121.158500 / 36.776400）
- 第一遍：以 `location` + `city=district` 调高德地理编码API（`processor/amap_geocode.py`），district 为空带『烟台市』
- ⚠️ 精度闸门（硬约束，必须执行）：高德返回结果的 `level` 为 省 / 市 / 城市 / 区县（即退回行政中心/中心点）时，视为"未查到具体地址"，**严禁直接采用该中心坐标**；必须进入下一轮联网搜索补全
- 查不到 / 跨区错配 / 触发精度闸门：用『区县 + 项目名称』联网搜索（WebSearch）找公示原文实际地址，再编码补全
- ⚠️ location 同步更新（与经纬度配套）：解压到真实地址后，若原 `location` 仅到区县/市（如「烟台市 莱山区」「龙口市」，不含道路/村/门牌等细节），须将 `location` 同步更新为该详细地址；若原 `location` 已是详细地址（含道路/村/具体描述），则**保留原 location 不覆盖**，仅更新 lng/lat
- 二次解压（中心兜底记录的精细化）：对第一遍仍退化成"区县中心点"的记录，统一走 `processor/amap_decompress.py` 的联网增强流程（逐条搜公示原文地址→高德重编码 + 同步更新笼统 location），**不得将其伪装为已解压**
- 仅 location 空、项目名称无收录、联网仍无线索才不输出该字段；不得凭空编造远离实际的数值
- ⚠️ 同坐标去重：不同项目解析到完全相同坐标时脚本须汇总报告（哪些 _index 同点）便于复核——同一产业园多期项目同点属正常；若因 location 笼统（只到区县）导致批量同点，应回退更细地址或人工复核，避免地图误堆叠
- 执行脚本：processor/amap_geocode.py（第一遍编码，仅红/黄预警记录执行）；processor/amap_decompress.py（二次解压，中心兜底记录的精细化重编码 + location 同步）；Key 存于 processor/.amap_key，不写进代码与记忆

### need_base_station 判断标准
- "高"：大型住宅(300户+)、商业综合体、学校、医院、隧道、地下空间、工业园区、**科研设施**、**冷链仓储**、交通枢纽、化工装置厂房、大型厂房(1万㎡+)
- "中"：中型住宅(100-300户)、办公楼、酒店、商场、景区、公共设施、污水处理厂、中型厂房(5000-1万㎡)
- "低"：小型建筑、道路(无隧道)、绿化工程、小型装修、小型厂房(<5000㎡)
- "无"：纯设备采购、咨询服务、软件项目、与土建无关

### base_station_type 判断
- "宏站"：开阔区域、道路、景区、工业园区、新建未覆盖区域
- "室分"：地下室、封闭建筑、大型室内空间、**钢结构厂房**、**冷库**、**化工装置厂房**
- "小站"：补盲覆盖、街道、小型建筑群
- "宏站+室分"：大型综合体、高层住宅群(10层+)、大型医院/学校、**大型产业园**、**科研基地**
- "无需"：need_base_station为"无"时

### priority 技术优先级（1-5）
- 5：大型住宅(500户+)、商业综合体(5万㎡+)、隧道(500m+)、大型医院/学校、交通枢纽、**国家级科研设施**、**大型冷链仓储**
- 4：中型住宅(200-500户)、办公楼(2万㎡+)、园区、医院、学校、**科研试验基地**、**智慧工厂**
- 3：小型住宅(100-200户)、酒店、商场、中等规模公共建筑
- 2：小型建筑、普通道路、小型公共设施
- 1：装修、改造、非土建类

### score 商机评分（1-5）
- 5：大型新建项目(投资1亿+)或国家级/省级重点项目，有明确且强烈的通信需求，建设方为央企/国企/科研院所，处于规划或施工早期阶段
- 4：中型新建项目(5000万+)，有明确通信需求(新建建筑有室分/宏站需求)，处于招标或施工阶段，或建设方有长期合作价值
- 3：中型项目，有潜在通信需求，规划或设计阶段，或小型新建项目但通信需求扎实
- 2：小型项目、通信需求不明确、或已临近竣工
- 1：无商业价值、纯流程性公告

### warning_level 映射
- score >= 4 → "红色预警"
- score == 3 → "黄色预警"
- score < 3 → "无预警"
- ⚠️ 例外提级：建筑本体的「建筑设计方案公示」即便处于规划/设计早期，也**直接定为红色预警**（score 取 4+），不按普通"规划早期=黄"处理。

### ai_reason 撰写规范（⚠️ 必须三段式！）

**格式要求：**
```
【项目本质】2-3句话：项目类型+规模+建设方+阶段+核心特征
【基站评估】2-3句话：从通信技术原理出发，说明为什么需要/不需要基站。（如：钢结构厂房→信号屏蔽→室分必装；冷库→金属保温板隔绝→防潮室分；地下车库→天然盲区→室分）
【商机判断】2-3句话：建设方价值评估+跟进时机+切入建议
```

**质量要求：**
- 基站评估必须从技术原理出发，说明因果关系（"为什么"），而非简单断言（"是什么"）
- 商机判断必须给出具体的跟进时间窗口（"2026年Q3前"而非"近期"）
- 本条即为独立分析单元，不要求注明与其他期数/项目的关联性

### telecom_needs 撰写规范（⚠️ 要具体，不要泛泛而谈！）

**✅ 好的写法（具体到场景）：**
- "5G室分系统（6栋钢结构车间，每栋需pRRU）"
- "冷库专用室分（防潮防低温型，-18℃环境）"
- "SCADA光纤专线（9台风机各1条至中控室）"
- "地下车库室分覆盖（9213㎡）"
- "AGV调度无线专网（低时延高可靠）"

**❌ 差的写法（太泛）：**
- "信号覆盖"
- "宽带专线"
- "物联网"

**维度参考（基于以下5个维度具体化）：**
- 信号覆盖 → 说明覆盖哪里、什么类型、多少数量
- 宽带专线 → 说明用途、带宽级别
- 物联网 → 说明场景、传感器类型/数量
- 云服务 → 说明具体服务类型
- 固话/视频会议 → 说明需求规模

### project_stage 判断

**核心方法：外部验证 + 时间线推理**

1. 用项目名称联网搜索，找到该项目的所有相关公告/新闻 3-4 条
2. 按时间排序，构建项目时间线
3. 综合判断：结合项目规模、公告发布时间和当前日期推算

**各阶段特征：**
- "规划立项"：风险评估公示、选址意见书、用地预审、立项备案、环评公示、用地规划许可
- "招标阶段"：招标公告、竞争性磋商、资格预审、中标公示
- "施工阶段"：施工许可、开工仪式、施工进度报道
- "已竣工完工"：竣工验收报告、交付使用（需明确写"已完工"或"通过验收"）
- "待核实"：多方搜索仍无法确定

### project_type 标准值（13 类，**枚举铁律，必须二选一精确输出，不得写括号组合**）
工业厂房（厂房/车间/加工厂/厂区）/ 仓储物流（仓库/冷链）/ 住宅小区（住宅/安置/棚改/公寓）/
商业综合体（商场/写字楼/酒店）/ 学校 / 医院 / 工业园区（产业园/科技城）/
市政设施（供水/排水/管网/路灯/停车）/ 交通工程（道路/桥梁/隧道/公路/机场/港口）/
能源电力（变电站/储能/光伏/风电/充电/电池材料）/ 科研设施（实验室/研发中心）/
景区文旅（景区/公园/场馆）/ 其他
⚠️ 项目性质（新建/扩建/改造/技改）**禁止写入 project_type**——它属于 status 阶段判断，不是类型；无法归入以上 13 类的才写"其他"

## 核心准则

**🔴 第一原则：只要公告涉及"建设/新建/扩建"工程且有新建建筑体量 → 必须仔细分析，返回完整 JSON。**

1. **专业判断优先**：你是分析师，不是文字提取器。即使公告信息不完整，也要基于项目类型和规模做合理的技术推断。不确定的具体实体标注"待核实"，技术评估必须基于专业知识推理。

2. **零编造原则（企业数据安全红线）**：具体名称（项目名/建设方/地点/投资额/**区县**）必须来自公告原文或搜索确认，**绝对禁止凭空猜测、套用模板或臆造**。无法确认的一律填"待核实"。这是企业级情报数据，任何编造都会导致错误决策与资源浪费。

3. **区分推理 vs 事实**：
   - 技术判断（need_base_station, priority, base_station_type, telecom_needs）→ 基于专业知识推理，要写清推理过程
   - 具体实体（project_name, developer, location, investment）→ 必须基于公告或搜索确认

4. **枚举值铁律**：
   - `status` 仅限：规划立项 / 招标阶段 / 施工阶段 / 已竣工完工 / 待核实
   - `project_type` 仅限上述 13 类标准值之一，禁止写"新建（…）""扩建""改造（…）"等组合/性质前缀
   - `need_base_station` 仅限：高 / 中 / 低 / 无
   - `base_station_type` 仅限：宏站 / 室分 / 小站 / 宏站+室分 / 无需
   - `warning_level` 仅限：红色预警 / 黄色预警 / 无预警
   - `district` 仅限：芝罘区 / 莱山区 / 福山区 / 牟平区 / 蓬莱区 / 龙口市 / 莱阳市 / 莱州市 / 招远市 / 栖霞市 / 海阳市 / 长岛综合试验区 / 烟台开发区 / 烟台高新区 / 烟台保税港区（无法确认填"待核实"）

5. **分流优先**：先做 triage，无预警直接返回短标记。只有红色/黄色预警才输出完整 JSON。

6. **只返回 JSON**：不添加任何解释文字、Markdown标记或代码块包裹。直接输出 JSON 对象。"""


# ==============================================================================
# Stage 1: AI 深度推理分析
# ==============================================================================

def build_user_message(title: str, content: str, publish_date: str,
                       source_url: str, source_name: str) -> str:
    """构建发给 AI 的用户消息。URL 前置，要求 AI 自主访问获取原文。"""
    clean_content = re.sub(r'\s+', ' ', (content or "")).strip()[:500]

    return f"""## 任务
你是通信基础设施情报分析师。请按三步法分析以下政府公告项目。

## ⚡ 第一步：快速分流
先判断是否属于"跳过"类型（征地补偿/听证会/养护/管道改造/友商业务/流程公告/门卫等）。
如果是 → 直接返回 `{{"warning_level":"无预警","skip":true}}` 立即停止。

## 🔍 第二步：外部验证（必须联网搜索！）
本条分析所需的联网搜索，目的仅是为**本条公告**补全证据，不是去搜关联项目。

### 🏁 竣工阶段判断（宏站抢建口径）
- 搜索 "[项目名称] 竣工 完工 验收 交付使用 主体竣工" → 确认项目进展到哪了。
- **宏站抢建只在「规划 / 招标 / 施工」阶段有价值**（抢在施工前 / 中把宏站布好）。项目一旦进入「主体竣工 / 竣工 / 验收 / 交付」任一阶段，施工期抢建窗口已关闭 → **直接判无预警，不再做后续分析**。
- **📅 计划工期校验（防过时红色，必须做）**：若本条 `end_date` / 施工许可证「有效期限」终点 **早于当前参考日期**（计划施工期已过期）→ **必须联网核实**项目实际进展，按核实结果处理：
  - 核实确认**仍在施工 / 主体施工**（延期）→ 维持原级（红/黄）
  - 核实确认**已主体竣工 / 竣工 / 验收 / 交付** → 直接判无预警（与主体竣工同处理）
  - **核实找不到实际状态（无公开证据）→ 按公告原定日期执行**：计划施工期终点已过期 → 视为窗口已关，**判无预警**；计划施工期未过期 → 维持原级。
  - 不得仅凭"施工许可证已核发"维持红色——证是过去时，窗口可能已关。**此兜底优先于下方"搜不到竣工证据→继续补全"，过期且核实无证据时直接按原定日期判无预警。**
- ⚠️ 日期必须对本条：搜到的竣工若指向旧期数 / 同名其他项目 → 不得据此判无预警，按正常流程走。
- 竣工结论用 `status` 字段承载（已竣工完工），保留信号供看板（warning_level 直接定无预警）。
- 搜不到竣工证据 / 仍在招标施工 → 继续补全证据。

### 📎 补全证据
4. 搜索 "[项目名称] 招标/施工" → 找项目时间线（确认处于招标/施工/规划哪个阶段）
5. 搜索 "[项目名称] 投资/规模" → 找项目体量数据
6. 搜索 "[建设方名称]" → 仅确认本条建设方主体信息（非去找该建设方的其他项目）
7. 访问公告原始 URL → 获取完整原文，与爬虫摘要校对
8. 搜索 "[项目名称] 具体地址/所在区县" → 确认精确位置（街道/路/园区/村居），并核对 district 是否落在烟台标准区县内，禁止编造未列出的区县

## 📋 第三步：三步深度分析
- 项目本质理解 → 类型/规模/建设方/阶段
- 基站技术评估 → 从通信原理出发（钢结构→屏蔽→室分 etc.）
- 商机情报分析 → 建设方价值+具体需求+跟进时机

## 公告信息
- 链接：{source_url}
- 标题：{title}
- 来源：{source_name}
- 日期：{publish_date}
- 摘要：{clean_content if clean_content else '（无摘要，请从URL获取原文）'}

## 输出要求
- ai_reason 用三段式：【项目本质】【基站评估】【商机判断】
- telecom_needs 要具体（如"冷库专用室分（防潮防低温型）"），不要泛泛的"信号覆盖"
- 不确定的实体填"待核实"
- 直接返回 JSON，不要解释文字"""


def analyze_project(title: str, content: str, publish_date: str,
                    source_url: str, source_name: str) -> Optional[dict]:
    """
    对单条政府公告进行 AI 深度推理分析。

    这是整个管线唯一的 AI 调用 —— 一次调用同时输出基站技术评估 + 商机销售情报。

    Args:
        title: 公告标题
        content: 公告正文
        publish_date: 发布日期
        source_url: 原文链接
        source_name: 数据来源（爬虫名称）

    Returns:
        完整的 AI 分析结果 dict，失败返回 None
    """
    user_msg = build_user_message(title, content, publish_date, source_url, source_name)

    # 注入烟台标准区县白名单，约束 AI 的 district 取值（防止编造白名单外区县）
    district_hint = "、".join(YANTAI_DISTRICTS)
    system_prompt = (
        UNIFIED_SYSTEM_PROMPT
        + f"\n\n## 烟台标准区县白名单（district 必须且只能是以下之一，无法确认填'待核实'）\n"
        + district_hint
    )

    try:
        result = doubao.chat_json(
            system_prompt=system_prompt,
            user_message=user_msg,
            temperature=0.0,
            max_tokens=8192,
            enable_web_search=True,   # 智谱联网搜索
        )
    except Exception as e:
        logger.error(f"AI API 调用失败 [{title[:40]}]: {e}")
        return None

    if not result:
        logger.warning(f"AI 返回空结果: {title[:40]}...")
        return None

    # 清洗 + 标准化
    result = _clean_unified_result(result)
    # 以下元数据由 Python 侧填入，不受 AI 输出影响
    result["source_url"] = source_url
    result["source_name"] = source_name
    result["publish_date"] = publish_date
    result["_title"] = title   # 仅内部参考，不进 DB

    return result


def analyze_batch(records: list[dict], verbose: bool = True,
                  checkpoint_path: str = None) -> list[dict]:
    """
    批量 AI 分析（带断点续跑）。

    Args:
        records: 汇总后的记录列表（每条含 title, content, source_url, publish_date, source_name）
        verbose: 是否打印详细进度
        checkpoint_path: 断点续跑文件路径（可选）。若存在，已成功分析的记录
            （按 _source_db_id 去重）从磁盘恢复并跳过重跑；每成功分析一条即时
            落盘，中断后重跑只补未分析的，不重复消耗智谱 API 配额。

    Returns:
        成功分析的完整结果列表（包含所有字段，不做过滤）
    """
    results = []
    total = len(records)
    prev_start = time.time()  # 节流基准：保证相邻请求间隔 ≥60s

    # ---- 断点续跑：加载已有 checkpoint ----
    # checkpoint 保存已成功分析的完整结果（含 _source_db_id），
    # 下次运行按 _source_db_id 跳过重跑，不重复消耗智谱 API 配额。
    done_ids = set()
    checkpoint_by_id = {}
    if checkpoint_path:
        cp = Path(checkpoint_path)
        if cp.exists():
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    checkpoint = json.load(f)
                for it in checkpoint:
                    rid = it.get("_source_db_id")
                    if rid is not None:
                        rid = int(rid)
                        done_ids.add(rid)
                        checkpoint_by_id[rid] = it
                logger.info(f"[Stage 1] 断点续跑：从 {checkpoint_path} 恢复 "
                            f"{len(checkpoint_by_id)} 条已分析结果，跳过重跑")
            except Exception as e:
                logger.warning(f"[Stage 1] 断点文件加载失败({e})，全量重跑")

    # 恢复的结果按 records 顺序并入（保序，与全量跑一致）
    for rec in records:
        rid = rec.get("_source_db_id")
        if rid is not None:
            rid = int(rid)
            if rid in checkpoint_by_id:
                results.append(checkpoint_by_id[rid])

    def _save_checkpoint():
        """原子写入 checkpoint（先写临时文件再替换，避免写一半损坏）"""
        try:
            cp = Path(checkpoint_path)
            cp.parent.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            tmp.replace(cp)
        except Exception as e:
            logger.warning(f"[Stage 1] 断点保存失败: {e}")

    logger.info(f"[Stage 1] 开始 AI 深度推理分析，共 {total} 条"
                f"（待分析 {total - len(done_ids)} 条）...")

    for i, rec in enumerate(records):
        rid = rec.get("_source_db_id")
        if rid is not None and int(rid) in done_ids:
            continue  # 已分析过，跳过（checkpoint 恢复）

        title = str(rec.get("title", ""))
        content = str(rec.get("content", ""))
        url = str(rec.get("source_url", ""))
        date_str = str(rec.get("publish_date", datetime.date.today().isoformat()))
        source = str(rec.get("source_name", ""))

        if verbose:
            preview = title[:50].replace("\n", " ")
            logger.debug(f"  [{i+1}/{total}] {preview}...")

        # 失败自动重试（断网/限流/超时）：最多 3 次尝试，经纬度等关键信息不丢
        ai_res = None
        for attempt in range(3):
            ai_res = analyze_project(title, content, date_str, url, source)
            if ai_res is not None:
                break
            if attempt < 2:
                logger.warning(f"  [{i+1}/{total}] AI 分析失败（第{attempt+1}次），60s 后重试...")
                time.sleep(60)

        if ai_res is None:
            logger.warning(f"  [{i+1}/{total}] AI 分析 3 次尝试均失败，跳过（下次管线自动重试）")
            continue

        # 合并爬虫预提取字段
        ai_res["spider_score"] = rec.get("relevance_score", 0)
        ai_res["spider_district"] = rec.get("district_extracted", "")
        ai_res["spider_scale"] = rec.get("scale_extracted", "")
        ai_res["spider_investment"] = rec.get("investment_extracted", "")
        ai_res["spider_nature"] = rec.get("project_nature", "")
        ai_res["_source_db_id"] = rec.get("_source_db_id")

        results.append(ai_res)

        # 断点续跑：每成功一条即时落盘（中断后最多丢当前 1 条）
        if checkpoint_path:
            _save_checkpoint()

        if verbose:
            logger.info(
                f"  [{i+1}/{total}] ✅ {ai_res.get('project_name', '?')[:30]} "
                f"| 基站:{ai_res.get('need_base_station','?')} "
                f"| 优先级:{ai_res.get('priority','?')}⭐ "
                f"| 商机:{ai_res.get('score','?')}分 "
                f"| {ai_res.get('warning_level','?')}"
            )

        # 智谱账户级速率限制（RPM≈1/分钟）：相邻请求间隔必须 ≥60s，否则 429
        # 分析本身耗时 60~120s；若快于 60s 则补足等待
        elapsed = time.time() - prev_start
        if elapsed < 60:
            time.sleep(60 - elapsed)
        prev_start = time.time()

    logger.info(f"[Stage 1] 完成: {len(results)}/{total} 条分析成功")
    return results


# ==============================================================================
# Stage 2: 项目实体归并
# ==============================================================================

def merge_projects(results: list[dict]) -> list[dict]:
    """
    将同一项目的多条公告归并为一个情报记录。

    归并逻辑：
    - 以 project_name 为键分组
    - 同组取最高 priority、最高 score、最高 warning_level
    - 合并 telecom_needs（去重）
    - 合并 URLs 和 spider 信息
    - "待核实"项目各自独立，不归并
    """
    if not results:
        return []

    logger.info(f"[Stage 2] 项目实体归并，输入 {len(results)} 条...")

    df = pd.DataFrame(results)
    merged = []

    for proj_name, group in df.groupby("project_name"):
        # 无法确认项目名的各自独立
        if proj_name in ("待核实", "全网未查到", "", "未提及", "原文未提及"):
            for _, row in group.iterrows():
                merged.append(row.to_dict())
            continue

        # 取最高预警等级
        warning_level = "无预警"
        if "红色预警" in group["warning_level"].values:
            warning_level = "红色预警"
        elif "黄色预警" in group["warning_level"].values:
            warning_level = "黄色预警"

        # 合并通信需求
        all_needs = []
        for needs in group.get("telecom_needs", []):
            if isinstance(needs, list):
                all_needs.extend(needs)
            elif isinstance(needs, str) and needs and needs != "暂无明确需求":
                all_needs.append(needs)
        unique_needs = list(set(all_needs)) if all_needs else ["暂无明确需求"]

        # 取第一条作为基础，更新最高分字段
        base = group.iloc[0].to_dict()
        base["priority"] = int(group["priority"].max())
        base["score"] = int(group["score"].max())
        base["warning_level"] = warning_level
        base["telecom_needs"] = unique_needs
        base["related_news_count"] = len(group)
        base["urls"] = "\n".join(
            str(u) for u in group["source_url"].unique() if str(u) != "nan"
        )
        # 同组全部原始记录 id（供 scheduler 标记已处理，防止下周重复分析）
        base["_source_db_ids"] = [
            int(i) for i in group["_source_db_id"].tolist()
            if i is not None and str(i) != "nan"
        ]
        # 取第一条非"待核实"的信息
        for field in ["district", "owner_builder", "project_stage", "developer",
                       "location", "scale", "investment", "contact_clues"]:
            if base.get(field) == "待核实":
                better = _first_non_empty(group, field, "待核实")
                if better != "待核实":
                    base[field] = better

        merged.append(base)

    logger.info(f"[Stage 2] 归并完成: {len(results)} → {len(merged)} 个项目")
    return merged


# ==============================================================================
# Stage 3: 输出
# ==============================================================================

def export_unified_results(merged: list[dict], json_path: str,
                           db_path: str = None) -> None:
    """
    导出结果到 JSON 文件 + 可选写入 SQLite 数据库。

    Args:
        merged: 归并后的情报列表
        json_path: JSON 输出路径
        db_path: SQLite 路径（可选）
    """
    # 保留全部记录（含无预警）：入库/标记需要全量（防无预警记录下周重复分析），
    # 前端口径（只显示红/黄）由前端过滤（processLoadedData / map_points 已过滤无预警）

    # JSON 导出
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    logger.info(f"[Stage 3] JSON 已导出: {json_path} ({len(merged)} 条)")

    # SQLite 导出（可选）
    if db_path:
        _write_unified_db(merged, db_path)


def _write_unified_db(records: list[dict], db_path: str) -> None:
    """写入统一的 SQLite 数据库。"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unified_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            project_type TEXT,
            district TEXT,
            location TEXT,
            scale TEXT,
            investment TEXT,
            developer TEXT,
            owner_builder TEXT,
            project_stage TEXT,
            contact_person TEXT,
            contact_phone TEXT,
            deadline TEXT,
            start_date TEXT,
            end_date TEXT,
            need_base_station TEXT,
            base_station_type TEXT,
            coverage_area TEXT,
            ai_reason TEXT,
            priority INTEGER,
            score INTEGER,
            warning_level TEXT,
            is_valuable INTEGER,
            telecom_needs TEXT,
            contact_clues TEXT,
            action_suggestion TEXT,
            ai_summary TEXT,
            pub_date TEXT,
            related_news_count INTEGER,
            urls TEXT,
            source_name TEXT,
            spider_score REAL,
            spider_district TEXT,
            spider_scale TEXT,
            spider_investment TEXT,
            spider_nature TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for item in records:
        cursor.execute("""
            INSERT INTO unified_intelligence
            (project_name, project_type, district, location, scale, investment,
             developer, owner_builder, project_stage, contact_person, contact_phone,
             deadline, start_date, end_date,
             need_base_station, base_station_type, coverage_area, ai_reason,
             priority, score, warning_level, is_valuable,
             telecom_needs, contact_clues, action_suggestion, ai_summary,
             pub_date, related_news_count, urls, source_name,
             spider_score, spider_district, spider_scale, spider_investment, spider_nature)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.get("project_name"),
            item.get("project_type"),
            item.get("district"),
            item.get("location"),
            item.get("scale"),
            item.get("investment"),
            item.get("developer"),
            item.get("owner_builder"),
            item.get("project_stage"),
            item.get("contact_person", ""),
            item.get("contact_phone", ""),
            item.get("deadline", ""),
            item.get("start_date", ""),
            item.get("end_date", ""),
            item.get("need_base_station"),
            item.get("base_station_type"),
            item.get("coverage_area"),
            item.get("ai_reason"),
            item.get("priority"),
            item.get("score"),
            item.get("warning_level"),
            1 if item.get("is_valuable") else 0,
            json.dumps(item.get("telecom_needs", []), ensure_ascii=False),
            item.get("contact_clues"),
            item.get("action_suggestion"),
            item.get("ai_summary"),
            item.get("_publish_date", item.get("pub_date", "")),
            item.get("related_news_count", 1),
            item.get("urls", ""),
            item.get("_source_name", ""),
            item.get("spider_score", 0),
            item.get("spider_district", ""),
            item.get("spider_scale", ""),
            item.get("spider_investment", ""),
            item.get("spider_nature", ""),
        ))

    conn.commit()
    conn.close()
    logger.info(f"[Stage 3] 已写入数据库: {db_path} ({len(records)} 条)")


# ==============================================================================
# 总控入口
# ==============================================================================

def run_unified_pipeline(input_records: list[dict],
                         output_json_path: str = "data/dashboard_data.json",
                         db_path: str = None,
                         verbose: bool = True) -> list[dict]:
    """
    统一 AI 情报分析管线 — 唯一入口。

    一次 AI 调用同时完成基站技术评估 + 商机销售情报分析。

    阶段：
      Stage 1: AI 深度推理分析（逐条调用豆包，输出全部字段）
      Stage 2: 项目实体归并（同名项目合并）
      Stage 3: JSON + SQLite 双输出

    Args:
        input_records: 汇总后的记录列表（来自 aggregate.py）
        output_json_path: JSON 输出路径
        db_path: SQLite 数据库路径（可选）
        verbose: 是否打印详细日志

    Returns:
        归并后的统一情报列表
    """
    logger.info("=" * 60)
    logger.info("🚀 统一 AI 情报分析管线启动")
    logger.info(f"   输入: {len(input_records)} 条记录")
    logger.info(f"   输出: {output_json_path}")
    if db_path:
        logger.info(f"   数据库: {db_path}")
    logger.info("   模式: 深度推理（开启联网搜索，AI 基于行业知识 + 外部佐证分析）")
    logger.info("=" * 60)

    if not input_records:
        logger.warning("无有效记录，管线终止")
        return []

    # Stage 1: AI 深度推理分析（断点续跑：中断重跑只补未分析的，不重复消耗智谱配额）
    checkpoint_path = str(Path(output_json_path).with_suffix("")) + ".checkpoint.json"
    results = analyze_batch(input_records, verbose=verbose,
                            checkpoint_path=checkpoint_path)

    if not results:
        logger.warning("AI 分析后无结果，管线终止")
        export_unified_results([], output_json_path, db_path)
        return []

    # Stage 2: 项目实体归并
    merged = merge_projects(results)

    # Stage 3: 输出
    export_unified_results(merged, output_json_path, db_path)

    # 统计
    red = sum(1 for r in merged if r.get("warning_level") == "红色预警")
    yellow = sum(1 for r in merged if r.get("warning_level") == "黄色预警")
    no_warn = sum(1 for r in merged if r.get("warning_level") == "无预警")
    high_bs = sum(1 for r in merged if r.get("need_base_station") == "高")
    mid_bs = sum(1 for r in merged if r.get("need_base_station") == "中")

    logger.info("=" * 60)
    logger.info(
        f"🎉 管线完成! 产出 {len(merged)} 个情报项目"
    )
    logger.info(
        f"   📡 基站需求: 高{high_bs} 中{mid_bs} "
        f"| 💼 商机预警: 🔴{red} 🟡{yellow} ⚪{no_warn}"
    )
    logger.info(f"   📄 JSON: {output_json_path}")
    if db_path:
        logger.info(f"   🗄️  数据库: {db_path}")
    logger.info("=" * 60)

    return merged


# ==============================================================================
# 辅助函数
# ==============================================================================

def _validate_district(result: dict) -> dict:
    """
    区县校验：将 district 与 YANTAI_DISTRICTS 标准白名单核对（与用户区县数据一一对应）。

    规则（绝不编造）：
      - 直接命中标准区县 → 保留
      - 从 district / location / project_name 组合文本中识别出标准区县名 → 纠正为该区县
      - 均无法核对 → 标记"待核实"，并记录告警日志（不臆造）
    """
    raw = str(result.get("district", "")).strip()
    if raw in YANTAI_DISTRICTS:
        return result

    # 从 district / location / project_name 组合文本中识别标准区县
    haystack = " ".join([
        raw,
        str(result.get("location", "")),
        str(result.get("project_name", "")),
    ])
    matched = [d for d in YANTAI_DISTRICTS if d in haystack]
    if matched:
        # 取最长匹配，避免"烟台"被多个前缀（开发区/高新区/保税港区）重复命中
        best = max(matched, key=len)
        logger.warning(
            f"[区县校验] district='{raw}' 不在标准白名单，已从上下文纠正为 '{best}'"
        )
        result["district"] = best
        return result

    # 完全无法核对 → 待核实，绝不臆造
    logger.warning(
        f"[区县校验] district='{raw}' 无法在标准白名单中核对，标记为'待核实'（不编造）"
    )
    result["district"] = "待核实"
    return result


def _clean_unified_result(result: dict) -> dict:
    """标准化清洗 AI 返回的统一结果。"""
    defaults = {
        # 基本信息
        "project_name": "待核实", "project_type": "其他", "district": "待核实",
        "location": "待核实", "scale": "待核实", "investment": "待核实",
        "content": "", "developer": "待核实", "contact_person": "", "contact_phone": "",
        "deadline": "", "start_date": "", "end_date": "",
        "source_name": "", "source_url": "", "publish_date": "",
        # 基站技术
        "need_base_station": "中", "base_station_type": "无需",
        "coverage_area": "待核实", "ai_reason": "",
        "priority": 3,
        # 商机情报
        "warning_level": "无预警", "status": "待核实",
        "is_valuable": False, "score": 0,
        "telecom_needs": [], "ai_summary": "",
    }
    for key, default in defaults.items():
        if key not in result or result[key] is None:
            result[key] = default

    # 文本字段强制规范为字符串（与 workbuddy.json 格式一致）
    # AI 偶尔会把 coverage_area/ai_reason 等文本字段输出成 dict/list →
    # SQLite 写库报 sqlite3.InterfaceError('Error binding parameter 17')。
    # 这里统一转成字符串（dict/list 序列化为 JSON 文本），保证全链路类型一致。
    str_fields = [
        "project_name", "project_type", "district", "location", "scale",
        "investment", "content", "developer", "contact_person", "contact_phone",
        "deadline", "start_date", "end_date", "source_name", "source_url",
        "publish_date", "need_base_station", "base_station_type",
        "coverage_area", "ai_reason", "warning_level", "status", "ai_summary",
        "contact_clues", "action_suggestion", "owner_builder", "project_stage",
    ]
    for key in str_fields:
        v = result.get(key)
        if isinstance(v, (dict, list)):
            result[key] = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, bool):
            result[key] = "是" if v else "否"
        elif v is not None and not isinstance(v, str):
            result[key] = str(v)

    # 字符串字段去空格
    for key in str_fields:
        if isinstance(result.get(key), str):
            result[key] = result[key].strip()

    # need_base_station 枚举校验
    if result["need_base_station"] not in ("高", "中", "低", "无"):
        result["need_base_station"] = "中"

    # base_station_type 枚举校验
    valid_types = ("宏站", "室分", "小站", "宏站+室分", "无需")
    if result["base_station_type"] not in valid_types:
        result["base_station_type"] = "无需"

    # status 枚举校验（原 project_stage）
    valid_stages = ("规划立项", "招标阶段", "施工阶段", "已竣工完工", "待核实")
    if result["status"] not in valid_stages:
        result["status"] = "待核实"

    # priority 整数 1-5
    try:
        result["priority"] = max(1, min(5, int(result.get("priority", 3))))
    except (ValueError, TypeError):
        result["priority"] = 3

    # score 整数 1-5
    try:
        result["score"] = max(1, min(5, int(result.get("score", 0))))
    except (ValueError, TypeError):
        result["score"] = 0

    # lng/lat 经纬度校验：必须是合法数值（经度 ±180、纬度 ±90），非法则移除（不输出该字段）
    try:
        lng = float(result.get("lng"))
        lat = float(result.get("lat"))
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise ValueError
        result["lng"] = round(lng, 6)
        result["lat"] = round(lat, 6)
    except (ValueError, TypeError):
        result.pop("lng", None)
        result.pop("lat", None)

    # warning_level 优先尊重 AI 的判断（AI 判"无预警"就保持"无预警"）
    valid_levels = ("红色预警", "黄色预警", "无预警")
    ai_level = result.get("warning_level")
    if ai_level in valid_levels:
        # AI 已给出明确预警等级，直接采用，不再按 score 强制覆盖
        result["warning_level"] = ai_level
    else:
        # AI 未明确给出预警等级，才按 score 兜底推导
        if result["score"] >= 4:
            result["warning_level"] = "红色预警"
        elif result["score"] == 3:
            result["warning_level"] = "黄色预警"
        else:
            result["warning_level"] = "无预警"

    # is_valuable 与 warning_level 保持一致，避免"无预警却有价值"的矛盾
    if result["warning_level"] == "无预警":
        result["is_valuable"] = False
    elif isinstance(result.get("is_valuable"), bool):
        pass  # 尊重 AI 给出的 bool 判断
    else:
        result["is_valuable"] = True

    # telecom_needs 确保是列表
    if isinstance(result.get("telecom_needs"), str):
        s = result["telecom_needs"].strip()
        result["telecom_needs"] = [s] if s else ["暂无明确需求"]
    if not isinstance(result.get("telecom_needs"), list) or not result["telecom_needs"]:
        result["telecom_needs"] = ["暂无明确需求"]

    # telecom_needs 质量检查（保留 AI 的具体描述，拦截无效值）
    # 标准维度参考：信号覆盖 / 宽带专线 / 物联网 / 云服务 / 固话视频会议
    INVALID_NEEDS = {"无", "空", "待核实", "暂无", "无需求", "无明确需求",
                     "不确定", "暂无明确需求", ".", "无。", "无."}
    filtered = []
    for n in result["telecom_needs"]:
        n_str = str(n).strip()
        if not n_str:
            continue
        # 拦截 AI 偷懒输出的"无/空"等无效项（2026-08-22：glm-4.7 输出 27 条 ["无"]）
        if n_str in INVALID_NEEDS:
            continue
        # 允许：标准值 / 具体描述（含括号说明的）
        filtered.append(n_str)
    result["telecom_needs"] = filtered
    if not result["telecom_needs"]:
        result["telecom_needs"] = ["暂无明确需求"]

    # 区县校验：与 YANTAI_DISTRICTS 标准白名单核对，防止编造/错填（绝不臆造）
    result = _validate_district(result)

    return result


def _first_non_empty(df: pd.DataFrame, column: str, fallback: str = "待核实") -> str:
    """从 DataFrame group 中取第一个非空/非'待核实'的值。"""
    if column not in df.columns:
        return fallback
    for val in df[column]:
        val_str = str(val).strip()
        if val_str and val_str not in ("nan", "待核实", "全网未查到", ""):
            return val_str
    return fallback


# ==============================================================================
# CLI (测试用)
# ==============================================================================

def main():
    """命令行入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="统一 AI 情报分析管线 — 豆包深度推理",
    )
    parser.add_argument(
        "--input-json", type=str,
        help="输入 JSON 文件（aggregate.py 的输出）",
    )
    parser.add_argument(
        "--output-json", type=str, default="data/dashboard_data.json",
        help="输出 JSON 路径（默认 data/dashboard_data.json）",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="SQLite 数据库路径（可选）",
    )
    parser.add_argument(
        "--max-items", type=int, default=0,
        help="最多分析 N 条（0=全部，测试用）",
    )
    parser.add_argument(
        "--test-single", type=str, default=None,
        help="测试单条: '标题|正文|日期|URL|来源'",
    )

    args = parser.parse_args()

    # 单条测试模式
    if args.test_single:
        parts = args.test_single.split("|")
        title = parts[0] if len(parts) > 0 else "测试项目"
        content = parts[1] if len(parts) > 1 else ""
        date_str = parts[2] if len(parts) > 2 else str(datetime.date.today())
        url = parts[3] if len(parts) > 3 else ""
        source = parts[4] if len(parts) > 4 else "手动测试"

        print(f"测试: {title[:50]}...")
        result = analyze_project(title, content, date_str, url, source)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 批量模式
    if not args.input_json:
        logger.error("请指定 --input-json 或 --test-single")
        return

    with open(args.input_json, "r", encoding="utf-8") as f:
        records = json.load(f)

    if args.max_items > 0:
        records = records[:args.max_items]
        logger.info(f"限制分析数量: {args.max_items} 条")

    run_unified_pipeline(
        input_records=records,
        output_json_path=args.output_json,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
