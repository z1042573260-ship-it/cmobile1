# -*- coding: utf-8 -*-
"""把 all_spiders_merged_审核表.xlsx 按 AI 管线标准转换成 workbuddy2.json（含经纬度）。

严格套用 processor/ai_pipeline.py 中"字段填写规范 / 判定标准"段落的文档化规则：
- project_type 13类枚举 / need_base_station 高|中|低|无 / base_station_type 5类
- priority 1-5 / score 1-5 / warning_level 由 score 决定 + 建筑设计方案公示提级红
- status 阶段 / ai_reason 三段式 / ai_summary 80字 / telecom_needs 具体 / coverage_area
- 经纬度：复用 amap_geocode（GCJ-02），精度闸门拦中心坐标，诚实标注 geo_source

日期过滤规则（用户指定）：
- yantai_districts（来源含"区县"）: 仅保留 publish_date >= 2026-07-23，剔除之前旧公告
- 其他 6 个爬虫: 保持原样不截取

导出口径：仅保留 红色预警 / 黄色预警（无预警剔除），与 workbuddy.json 一致。
"""
import json, re, os, sys, time
import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = r"D:\googledownload\wangluobu_vscode\data\spider_test\all_spiders_merged_审核表.xlsx"
OUT = r"D:\googledownload\wangluobu_vscode\data\results\workbuddy2.json"
YANTAI_CUT = "2026-07-23"

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
STD_DISTRICTS = ["芝罘区","莱山区","福山区","牟平区","蓬莱区","龙口市","莱阳市","莱州市",
                 "招远市","栖霞市","海阳市","长岛综合试验区","烟台开发区","烟台高新区","烟台保税港区"]

def parse_date(s):
    if not s:
        return None
    m = re.search(r'(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})', str(s))
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None

def _norm_raw(d):
    """把爬虫原始"区县"列归一为标准区县名（失败返回 None）。"""
    if not d:
        return None
    d = str(d).strip()
    for s in STD_DISTRICTS:
        if d == s or d in s or s in d:
            return s
    alias = {"高新区":"烟台高新区","开发区":"烟台开发区","保税港区":"烟台保税港区",
             "莱山":"莱山区","福山":"福山区","牟平":"牟平区","蓬莱":"蓬莱区","芝罘":"芝罘区",
             "龙口":"龙口市","莱阳":"莱阳市","莱州":"莱州市","招远":"招远市","栖霞":"栖霞市","海阳":"海阳市",
             "开发区(黄渤海新区)":"烟台开发区","黄渤海新区":"烟台开发区","烟台市":"烟台市"}
    if d in alias:
        return alias[d]
    m = re.search(r"烟台市?\s*(芝罘|莱山|福山|牟平|蓬莱|龙口|莱阳|莱州|招远|栖霞|海阳)\s*(区|市)?", d)
    if m:
        return {"芝罘":"芝罘区","莱山":"莱山区","福山":"福山区","牟平":"牟平区","蓬莱":"蓬莱区",
                "龙口":"龙口市","莱阳":"莱阳市","莱州":"莱州市","招远":"招远市","栖霞":"栖霞市","海阳":"海阳市"}[m.group(1)]
    return None

def norm_district(d, blob=""):
    # 内容摘要优先反推（比爬虫"区县"列更准，可修正"栖霞项目标成芝罘区"类标错）
    if blob:
        inferred = _infer_district(blob)
        if inferred != "待核实":
            return inferred
    raw = _norm_raw(d)
    return raw or "待核实"

def _infer_district(blob):
    """从标题/摘要文本里匹配烟台标准区县名（用于区县字段缺失时补全）。"""
    if not blob:
        return "待核实"
    for s in STD_DISTRICTS:
        if s in blob:
            return s
    # 功能区
    if "高新区" in blob: return "烟台高新区"
    if "开发区" in blob: return "烟台开发区"
    if "保税港区" in blob: return "烟台保税港区"
    return "待核实"

# ---------------------------------------------------------------------------
# project_type 13 类枚举（ai_pipeline.py 文档标准）
# ---------------------------------------------------------------------------
PT_RULES = [
    ("工业厂房", ["厂房","车间","加工厂","厂区","工厂","制造","生产线","基地","工业园","加工项目","加工车间","精密机械","精密","装备","零部件","电子","科技","新材料","生产基地","食品","制药","化工","电池材料","磷酸铁锂","正极材料","负极材料","钢结构"]),
    ("能源电力", ["变电站","储能","光伏","风电","充电","电池","电力","能源","供电","电厂","发电","核电","燃气","供热","热电","热网","绿电","清洁热","油气","加油","长输","输送管道","管网"]),
    ("科研设施", ["实验室","研发","科研","中试","检测中心","研究院","科创","孵化"]),
    ("学校",     ["学校","小学","中学","学院","大学","校区","幼儿园","教育","职校","高职","党校"]),
    ("医院",     ["医院","卫生院","医疗","疾控","卫生服务中心","康养","养老","卫生"]),
    ("交通枢纽", ["枢纽","机场","港口","火车站","客运站","公交","地铁","轨道","航运"]),
    ("住宅小区", ["住宅","安置","棚改","公寓","小区","楼市","廉租","保障房","拆迁安置","府","楼工程","楼项目","居住","社区"]),
    ("商业综合体",["商场","写字楼","酒店","商业","综合体","大厦","购物中心","商务楼","商铺","办公楼","银行","营业厅","网点"]),
    ("仓储物流", ["仓库","仓储","冷链","物流","配送中心","保税仓","罩棚","仓房","粮库","物资储备"]),
    ("工业园区", ["产业园","科技城","工业区","园区","示范基地","产业港","产业片区"]),
    ("交通工程", ["道路","桥梁","隧道","公路","高速","市政道路","高架","立交","管廊","铁路","轨道","改扩建","农村公路","乡道","街巷","路工程","路段"]),
    ("市政设施", ["供水","排水","管网","路灯","停车","市政","环卫","污水","垃圾","泵站","水厂","公园","绿地","绿化","固废","储备库","储备中心","消防","树木","污泥","中水"]),
    ("景区文旅", ["景区","公园","场馆","文旅","旅游","博物馆","文化馆","体育","健身","图书","游客","广场"]),
]

# 纯流程/非土建类公告 → 管线 triage 直接判无预警剔除
PURE_PROCESS = ["劳务派遣","无拖欠农民工工资","工资承诺书","招标代理","采购代理","中介服务",
                "评估机构","法律服务","审计服务","软件采购","信息系统","养护","绿化养护"]

def extract_real_project(content):
    """通用审批模板（如'绿地、树木审批办理结果公示表'）的真实项目名藏在 content 的
    '项目名称'/'企业名称' 列里；抽出来作为分类主信号。"""
    if not content:
        return ""
    c = str(content)
    for label in ["项目名称", "企业名称", "建设单位"]:
        m = re.search(label + r"\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·．.\-]{2,30})", c)
        if m:
            name = m.group(1).strip("，。；; ")
            # 排除表头噪声
            if name and name not in ("地址", "有效期限", "审批时间", "备注"):
                return name
    return ""

def detect_project_type(nature, title, content=""):
    # 优先用 content 抽出的真实项目名（避免被通用审批模板标题误导）
    real = extract_real_project(content)
    if real:
        for pt, kws in PT_RULES:
            for kw in kws:
                if kw in real:
                    return pt
    blob = " ".join([str(nature or ""), str(title or ""), str(content or "")])
    for pt, kws in PT_RULES:
        for kw in kws:
            if kw in blob:
                return pt
    # 项目性质字段精确匹配
    n = str(nature or "").strip()
    if n:
        for pt, kws in PT_RULES:
            if n in pt or any(k in n for k in kws):
                return pt
    return "其他"

# ---------------------------------------------------------------------------
# need_base_station / base_station_type（ai_pipeline.py 286-297）
# ---------------------------------------------------------------------------
def parse_area_wan(scale):
    """从规模字符串提取建筑面积（万㎡），用于判定大/中/小。"""
    if not scale:
        return None
    # 找 "X万㎡" 或 "X㎡"
    m = re.search(r'([\d.]+)\s*万\s*㎡', str(scale))
    if m:
        return float(m.group(1))
    m = re.search(r'([\d.]+)\s*㎡', str(scale))
    if m:
        v = float(m.group(1))
        if v > 1000:
            return round(v/10000, 2)
    return None

def detect_need_base(pt, scale, title=""):
    t = str(title)
    big_area = parse_area_wan(scale)
    high_kw = ["隧道","地下空间","冷链","交通枢纽","化工装置","大型厂房","工业园区","科研设施",
               "商业综合体","学校","医院","高层住宅","安置区","棚改"]
    mid_kw = ["办公楼","酒店","商场","景区","公共设施","污水处理厂","中型厂房"]
    none_kw = ["设备采购","咨询服务","软件","维保","养护","绿化工程","纯软件"]
    if any(k in t for k in none_kw):
        return "无"
    if any(k in t for k in high_kw) or (big_area and big_area >= 1) or pt in ("商业综合体","学校","医院","工业园区","科研设施","交通枢纽","能源电力"):
        return "高"
    if any(k in t for k in mid_kw) or (big_area and big_area >= 0.5):
        return "中"
    if pt in ("住宅小区","工业厂房","市政设施","交通工程","景区文旅"):
        return "中"
    return "低"

def detect_base_station_type(pt, scale, title="", content=""):
    blob = " ".join([str(title), str(content)])
    if "钢结构" in blob or "冷库" in blob or "化工装置" in blob:
        return "室分"
    if pt in ("商业综合体","学校","医院") :
        return "宏站+室分"
    if pt in ("工业园区","科研设施"):
        return "宏站+室分"
    if pt in ("住宅小区",):
        return "宏站+室分"
    if pt in ("交通工程","景区文旅"):
        return "宏站"
    if pt in ("工业厂房",):
        return "室分"
    if pt in ("市政设施",):
        return "小站"
    if pt == "无" or "设备采购" in blob:
        return "无需"
    return "宏站"

# ---------------------------------------------------------------------------
# 投资 / 阶段 / 评分 / 预警
# ---------------------------------------------------------------------------
def parse_invest_wan(inv):
    if not inv:
        return None
    s = str(inv)
    m = re.search(r'([\d.]+)\s*亿', s)
    if m:
        return float(m.group(1)) * 10000
    m = re.search(r'([\d.]+)\s*万', s)
    if m:
        return float(m.group(1))
    return None

def detect_stage(title, content=""):
    blob = " ".join([str(title), str(content)])
    if re.search(r"竣工|验收|交付使用|主体竣工|完工", blob):
        return "已竣工完工"
    if re.search(r"施工许可|开工|主体施工|在建|施工总承包|土建施工|幕墙施工|消防施工|开路口", blob):
        return "施工阶段"
    if re.search(r"招标|中标|竞争性磋商|资格预审|EPC|发包|采购公告", blob):
        return "招标阶段"
    if re.search(r"规划许可|选址|用地预审|立项|环评|批前公示|批后公布|设计方案|规划方案|社会稳定风险|征收|出让", blob):
        return "规划立项"
    return "待核实"

def compute_score(pt, invest_wan, stage, title):
    t = str(title)
    if "建筑设计方案公示" in t:
        base = 4
    elif stage == "施工阶段":
        base = 4
    elif stage == "招标阶段":
        base = 4
    elif stage == "规划立项":
        base = 3
    else:
        base = 3
    if invest_wan is not None:
        if invest_wan >= 5000:
            base = min(5, base + 1)
        elif invest_wan > 0 and invest_wan < 1000:
            base = max(1, base - 1)
    if pt in ("商业综合体","学校","医院","工业园区","科研设施","交通枢纽","能源电力"):
        base = min(5, base + 1)
    return max(1, min(5, base))

def compute_priority(pt, scale, stage):
    big_area = parse_area_wan(scale) or 0
    if pt in ("商业综合体","学校","医院","交通枢纽","能源电力") or big_area >= 5:
        return 5
    if pt in ("工业园区","科研设施","住宅小区") or big_area >= 2:
        return 4
    if pt in ("工业厂房","市政设施","景区文旅","交通工程"):
        return 3
    return 2

def warning_of(score, title):
    if "建筑设计方案公示" in str(title):
        return "红色预警"
    if score >= 4:
        return "红色预警"
    if score == 3:
        return "黄色预警"
    return "无预警"

# ---------------------------------------------------------------------------
# 叙述字段（遵循 ai_pipeline.py 三段式 / 80字 / 具体需求 格式标准）
# ---------------------------------------------------------------------------
def build_telecom_needs(pt, bst, scale, nbs):
    needs = []
    if nbs == "无" or bst == "无需":
        return needs
    if "室分" in bst:
        if pt == "工业厂房":
            needs.append("5G室分系统（钢结构车间，每栋需pRRU覆盖）")
        elif pt == "商业综合体":
            needs.append("商业体室分覆盖（每层商场+地下车库+电梯厅）")
        elif pt == "医院" or pt == "学校":
            needs.append("医疗/教学楼室分（人员密集，多频段吸顶天线）")
        else:
            needs.append("室内分布系统（封闭建筑信号盲区覆盖）")
    if "宏站" in bst:
        if pt in ("工业园区","交通枢纽","景区文旅","交通工程"):
            needs.append("园区/区域宏站补盲（开阔地新建基站）")
        else:
            needs.append("周边宏站补盲（建筑遮挡信号外溢）")
    if not needs:
        needs.append("信号覆盖（按建筑类型补充宏站/室分）")
    return needs

def build_ai_reason(pt, scale, invest, district, nbs, bst, stage, title):
    area = parse_area_wan(scale)
    area_s = f"约{area}万㎡" if area else "待核实"
    # 基站评估技术原理
    tech = {
        "工业厂房": "钢结构厂房金属屋面与框架对移动通信信号强屏蔽，内部必须部署室分（pRRU+馈线）才可能满足覆盖；",
        "商业综合体": "大型综合体楼层多、人员密集且隔断复杂，仅靠室外宏站无法穿透，需宏站+室分协同；",
        "住宅小区": "高层住宅群建筑遮挡严重，需宏站覆盖周边+室分解决电梯与地下车库盲区；",
        "医院": "医院墙体厚、设备多，信号衰减大，诊室与病房需室分保障急救通信；",
        "学校": "教学楼与宿舍密集，上下课时段并发高，需室分容量保障；",
        "交通枢纽": "开阔枢纽无遮挡但覆盖半径大，宜宏站补盲并兼顾室内换乘区；",
        "工业园区": "园区面积大、厂房分散，需宏站+室分组合实现全域覆盖；",
        "科研设施": "科研基地精密仪器多、屏蔽要求高，需宏站+室分并考虑电磁兼容；",
        "市政设施": "路灯/管廊等线性设施宜小站补盲，关键节点加宏站；",
        "交通工程": "道路隧道为天然信号盲区，需室分/泄漏电缆贯穿；",
        "其他": "按建筑本体结构评估，存在信号遮挡盲区需补充覆盖。",
    }.get(pt, "按建筑本体结构评估，存在信号遮挡盲区需补充覆盖。")
    reason = "【项目本质】"
    reason += f"{district}的「{str(title)[:40]}」属于{pt}，建设规模{area_s}，"
    if invest and invest != "待核实":
        reason += f"投资{invest}，"
    reason += f"当前处于{stage}。\n"
    reason += "【基站评估】" + tech
    if bst == "无需":
        reason += "经判定无土建体量或纯设备类，无需基站配套。\n"
    else:
        reason += f"据此项目本体需配置「{bst}」，与{pt}的通信需求匹配。\n"
    reason += "【商机判断】"
    if stage in ("规划立项","招标阶段"):
        reason += "项目尚处前中期，是宏站/室分抢建窗口期，建议本季度内对接建设方获取图纸、"
    elif stage == "施工阶段":
        reason += "项目已进场施工，室分与配套管线须随主体同步预埋，建议立即跟进避免错失窗口；"
    else:
        reason += "项目临近竣工，新建窗口收窄，建议核实实际进展后评估存量覆盖合作；"
    reason += f"建设方为{pt}类客户，存在长期运维与扩容价值，可优先列入重点跟进名单。"
    return reason

def build_ai_summary(pt, nbs, bst, district, stage):
    s = f"{district}{pt}，通信需求评级「{nbs}」，建议配置{bst}。"
    if nbs in ("高","中"):
        s += f"处于{stage}，应抢在土建窗口内完成基站配套对接。"
    else:
        s += "需求一般，持续观察。"
    return s[:80]

def build_coverage(scale):
    if not scale:
        return "待核实"
    return str(scale)[:60]

def extract_addr(content):
    """从内容摘要里尽量抠出具体地址（管线口径：禁止模板文字入库，找不到返回""，调用方填"待核实"）。"""
    if not content:
        return ""
    c = str(content)
    # 表头/模板噪声词：地址标签后若紧跟这些词，说明"地址"是表头列名而非真实标签
    HEADER_WORDS = ['有效期限','审批时间','备注','证号','序号','企业名称','项目名称',
                    '许可证号','用地性质','建设规模','公示时间','公示期','核发日期',
                    '有效期至','意见受理','监督单位','联系','邮编','附图','年度',
                    '用地单位','项目编号','招标方式','合同预估','信息来源','发布日期']
    # 去掉常见公示模板头部（法规引用、欢迎语）
    c = re.sub(r'(为提高城市规划的透明度[^。]{0,80}。|根据《中华人民共和国城乡规划法[^。]{0,120}。|欢迎广大市民(提出宝贵意见|参与[^。]{0,60}。))', '', c)
    # 1) 显式标签（标签后非表头词才算）
    for label in ["建设地点","项目位置","拟建位置","拟选址","用地位置","具体位置","选址","坐落","座落","位于"]:
        for m in re.finditer(label + r"\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9号路街巷乡村镇区栋层室园侧东西南北中，、\-0-9]{3,60})", c):
            a = m.group(1).strip("，、。 ；;")
            if len(a) >= 3 and not any(h in a[:12] for h in HEADER_WORDS):
                return a
    # 2) 表格型公告："地址"是列名时抓列值（值多为"XX路XX侧"式短地址）
    m = re.search(r"地址\s+([\u4e00-\u9fa5A-Za-z0-9号路街巷乡村镇区栋层室园侧东西南北中，、\-]{3,40}?)\s+(?:有效期限|审批时间|备注|证号|序号)", c)
    if m:
        a = m.group(1).strip("，、。 ")
        if len(a) >= 3 and not any(h in a[:12] for h in HEADER_WORDS):
            return a
    # 3) 锚定"位于/坐落于 XX路/街/村/园区"
    m = re.search(r"(?:位于|坐落于)[^\u4e00-\u9fa5]*([\u4e00-\u9fa5]{2,18}(?:路|街|大道|镇|乡|村|园区|工业区|街道|巷|路与|街与|大道与)[^\s，。；]{0,16})", c)
    if m:
        a = m.group(1).strip()
        if not any(h in a for h in HEADER_WORDS):
            return a
    return ""

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    ws = wb["爬虫数据审核"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    idx = {str(h).strip("'"): i for i, h in enumerate(header)}
    def col(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else None

    out = []
    _idx = 0
    total = drop_old = 0
    for r in rows:
        if not r or not any(c not in (None, "") for c in r):
            continue
        total += 1
        source = col(r, "来源")
        pub = parse_date(col(r, "发布日期"))
        # ---- 日期过滤 ----
        if source and "区县" in str(source):
            if pub and pub < YANTAI_CUT:
                drop_old += 1
                continue
        # ---- 基础字段 ----
        title = (col(r, "标题") or "").strip()
        nature = col(r, "项目性质")
        scale = col(r, "规模") or ""
        invest = col(r, "投资额") or "待核实"
        content = col(r, "内容摘要(前200字)") or ""
        url = col(r, "URL") or ""
        spider_score = col(r, "评分")

        # ---- 纯流程/非土建公告分流（管线 triage：直接判无预警剔除）----
        title_low = str(title)
        if any(k in title_low for k in PURE_PROCESS):
            continue

        blob = " ".join([title, str(content or "")])
        district = norm_district(col(r, "区县"), blob)
        pt = detect_project_type(nature, title, content)
        nbs = detect_need_base(pt, scale, title)
        bst = detect_base_station_type(pt, scale, title, content)
        invest_wan = parse_invest_wan(invest)
        stage = detect_stage(title, content)
        score = compute_score(pt, invest_wan, stage, title)
        warning = warning_of(score, title)
        priority = compute_priority(pt, scale, stage)
        is_val = warning != "无预警"
        telecom = build_telecom_needs(pt, bst, scale, nbs)
        ai_reason = build_ai_reason(pt, scale, invest, district, nbs, bst, stage, title)
        ai_summary = build_ai_summary(pt, nbs, bst, district, stage)
        coverage = build_coverage(scale)
        real = extract_real_project(content)
        addr = extract_addr(content)

        rec = {
            "_index": _idx,
            "_title": title,
            "ai_reason": ai_reason,
            "ai_summary": ai_summary,
            "base_station_type": bst,
            "contact_person": "",
            "contact_phone": "",
            "content": content,
            "coverage_area": coverage,
            "deadline": "",
            "developer": "",
            "district": district,
            "end_date": "",
            "investment": invest,
            "is_valuable": is_val,
            "lat": None,
            "lng": None,
            "location": addr or "待核实",
            "need_base_station": nbs,
            "priority": priority,
            "project_name": title,
            "real_name": real,
            "project_type": pt,
            "publish_date": pub or "",
            "scale": scale,
            "score": score,
            "source_name": source,
            "source_url": url,
            "start_date": "",
            "status": stage,
            "telecom_needs": telecom,
            "warning_level": warning,
        }
        # 仅保留红/黄预警（管线导出口径）
        if warning in ("红色预警", "黄色预警"):
            out.append(rec)
            _idx += 1

    # 写盘（先不带经纬度，第二步补充）
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"分类完成：读取 {total} 条 | 区县<7.23 剔除 {drop_old} 条 | 保留红/黄 {len(out)} 条")
    from collections import Counter
    print("  warning_level:", dict(Counter(x["warning_level"] for x in out)))
    print("  project_type:", dict(Counter(x["project_type"] for x in out)))
    print("  need_base_station:", dict(Counter(x["need_base_station"] for x in out)))
    print("  district:", dict(Counter(x["district"] for x in out)))
    print(f"  已写出: {OUT}")

if __name__ == "__main__":
    main()
