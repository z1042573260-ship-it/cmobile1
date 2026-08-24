# -*- coding: utf-8 -*-
"""修正施工许可证办理结果公示类误判：原9条无预警 -> 拆表为11个真实工程，全部红色预警。
仅改 workbuddy.json，不碰其他记录。"""
import json

JSON_PATH = r"D:\googledownload\wangluobu_vscode\data\results\workbuddy.json"

# 源行信息（Excel标题 + URL）
SRC = {
    111: ("海阳市行政审批服务局施工许可证办理结果公示（2026年4月3日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_a76a8e540f604a9fba9127103fd4d4b4.html"),
    114: ("海阳市行政审批服务局施工许可证办理结果公示（2026年4月2日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_7ed7963444bc4ca5b02677b1f6b574ee.html"),
    123: ("海阳市行政审批服务局施工许可证办理结果公示（2026年3月26日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_f3a60d670f9d47e1870240076a734779.html"),
    125: ("海阳市行政审批服务局施工许可证办理结果公示（2026年3月25日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_ca438d842ab64920bfe0b0620573cd05.html"),
    132: ("海阳市行政审批服务局施工许可证办理结果公示（2026年03月12日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_dc57c6e08e1a41abb95a9cb915e346f4.html"),
    159: ("海阳市行政审批服务局施工许可证办理结果公示（2026年2月6日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_32df3a2112704e08886d6b95242d1476.html"),
    166: ("海阳市行政审批服务局施工许可证办理结果公示（2026年01月30日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_890ed352a4b94061aa44309279f050c4.html"),
    171: ("海阳市行政审批服务局施工许可证办理结果公示（2026年01月23日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_f7ffaee02df14dfdb585c401a5d3d5d8.html"),
    177: ("海阳市行政审批服务局施工许可证办理结果公示（2026年01月15日）",
          "https://www.haiyang.gov.cn/col/col14046/art/2026/art_cfbf2398a2b74e25ab2403c3946045fd.html"),
}

# 拆表后的真实工程：idx=写回_index（单项目沿用原行号，多项目追加201/202），src=源Excel行
P = [
    dict(idx=111, src=111, permit="370687202604030199", dev="烟台市富淇新材料有限公司",
         name="烟台市富淇新材料有限公司生产车间项目", loc="海阳经济开发区鲁古埠村",
         period="2026.03.28-2026.06.18", appr="2026.04.03", ptype="新建（工业厂房）", bt="宏站"),
    dict(idx=114, src=114, permit="370687202604020101", dev="海阳瑞安置业有限公司",
         name="海阳瑞安置业有限公司扩建车间项目7#车间", loc="海阳市工业园",
         period="2026.03.25-2026.09.01", appr="2026.04.02", ptype="扩建（工业厂房）", bt="宏站"),
    dict(idx=123, src=123, permit="370687202603260101", dev="海阳市徐家店镇岚店村股份经济合作社",
         name="烟台思莱德果蔬汁生产加工项目", loc="海阳市徐家店镇083县道南、永能生物东",
         period="2026.03.25-2026.12.31", appr="2026.03.26", ptype="新建（农产品加工）", bt="宏站"),
    dict(idx=125, src=125, permit="370687202603250299", dev="山东万木森林科技有限公司",
         name="海阳市万木森林幼儿园办公楼", loc="海阳市乐山街东、南修家和龙塘埠棚改安置区北",
         period="2026.03.25-2027.03.25", appr="2026.03.25", ptype="新建（教育公建）", bt="宏站+室分"),
    dict(idx=201, src=125, permit="370687202603250101", dev="海阳市留格庄镇大沟店村集体经济组织",
         name="海阳市宏伟移动式建筑拼装项目1#车间", loc="海阳市留格庄镇大沟店村北",
         period="2026.03.04-2026.04.30", appr="2026.03.25", ptype="新建（移动式建筑拼装）", bt="宏站"),
    dict(idx=132, src=132, permit="370687202603120199", dev="万华化学（海阳）电池材料科技有限公司",
         name="万华化学绿电产业园二期年产20万吨磷酸铁锂项目-2#空压站", loc="海阳市海滨西路南、碧桂园东",
         period="2026.03.07-2026.06.30", appr="2026.03.12", ptype="新建（电池材料工业/配套）", bt="宏站"),
    dict(idx=159, src=159, permit="370687202602060101", dev="海阳市昊瀚置业有限公司",
         name="龙樾府（四）17#楼", loc="海阳市海天路北、乐山街东、马山街西",
         period="2026.01.10-2027.09.30", appr="2026.02.06", ptype="新建（住宅）", bt="宏站+室分"),
    dict(idx=202, src=159, permit="370687202602060201", dev="海阳市昊瀚置业有限公司",
         name="龙樾府（四）19#、22#楼及地下车库（三期B段）", loc="海阳市海天路北、乐山街东、马山街西",
         period="2026.01.10-2027.09.30", appr="2026.02.06", ptype="新建（住宅+地下车库）", bt="宏站+室分"),
    dict(idx=166, src=166, permit="370687202601300101", dev="海阳市义丰水产贸易有限公司",
         name="海阳中心渔港现代海洋渔业项目(1#海产品加工厂、渔获物集散中心厂房）", loc="海阳市海核路南、寨前村南",
         period="2026.01.06-2026.09.05", appr="2026.01.30", ptype="新建（渔业加工厂房）", bt="宏站+室分"),
    dict(idx=171, src=171, permit="370687202601230101", dev="海阳市茂源商贸有限公司",
         name="海阳市茂源商贸厂房扩建项目2#车间扩建", loc="海阳市凤城工业组团",
         period="2026.01.20-2026.05.31", appr="2026.01.23", ptype="扩建（厂房）", bt="宏站"),
    dict(idx=177, src=177, permit="370687202601150101", dev="烟台佳合塑胶科技有限公司",
         name="烟台佳合塑胶科技有限公司东厂区新建车间项目3#车间", loc="海阳市工业园",
         period="2025.12.25-2026.06.15", appr="2026.01.15", ptype="新建（工业厂房）", bt="宏站"),
]

with open(JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)

old_idx = set(SRC.keys()) | {201, 202}  # 含上次运行新增的拆分记录，避免重跑重复
before = len(data)
removed = [d["_index"] for d in data if d.get("_index") in old_idx]
data = [d for d in data if d.get("_index") not in old_idx]

added = 0
for p in P:
    title, url = SRC[p["src"]]
    sd, ed = p["period"].split("-")
    entry = {
        "project_name": p["name"],
        "project_type": p["ptype"],
        "district": "海阳市",
        "location": p["loc"],
        "scale": "待核实",
        "investment": "待核实",
        "content": f"{p['dev']}建设的{p['name']}已取得施工许可证（证号{p['permit']}），施工期{p['period']}，审批时间{p['appr']}。本条为施工许可证办理结果公示，工程获准开工，是通信基站需求释放的确定信号。",
        "developer": p["dev"],
        "contact_person": "待核实",
        "contact_phone": "待核实",
        "deadline": f"施工期{p['period']}，须在施工启动前切入通信配套",
        "start_date": sd,
        "end_date": ed,
        "need_base_station": "有",
        "base_station_type": p["bt"],
        "coverage_area": p["loc"],
        "ai_reason": (
            f"【项目本质】本条为施工许可证办理结果公示，{p['dev']}的{p['name']}已获准开工（施工期{p['period']}）。"
            "施工许可证核发=工程确定性最高阶段，100%进入施工。"
            f"【基站需求】施工期需宏站保障现场及沿线信号，建成后建筑体需{p['bt']}覆盖。"
            "【商机情报】施工许可证是抢占市场的最佳窗口——工程马上开建，应即刻对接建设单位洽谈施工期临时覆盖+建成永久覆盖，红色预警。"
        ),
        "priority": 5,
        "score": 5,
        "warning_level": "红色预警",
        "is_valuable": True,
        "telecom_needs": ["施工期宏站覆盖保障", "建成后建筑体通信配套", "建设单位对接洽谈"],
        "ai_summary": f"{p['name']}施工许可证已核发（{p['period']}），获准开工，红色预警待抢占。",
        "source_name": "海阳市行政审批服务局",
        "source_url": url,
        "publish_date": p["appr"],
        "status": "施工阶段（施工许可证已核发）",
        "_index": p["idx"],
        "_title": title,
    }
    data.append(entry)
    added += 1

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# 验证
with open(JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)
print(f"删除旧误判记录: {removed} (共{len(removed)}条)")
print(f"新增正确记录: {added} 条")
print(f"文件总条数: {before} -> {len(data)}")
# 字段顺序一致性
ref = list(data[0].keys())
bad = [d["_index"] for d in data if list(d.keys()) != ref]
print(f"字段顺序不一致: {bad if bad else '无，全部一致'}")
# 新记录概览
print("\n新增红色预警记录:")
for d in sorted([x for x in data if x.get('_src_index') in SRC], key=lambda x: x['_index']):
    print(f"  [{d['_index']}] {d['warning_level']} | {d['base_station_type']:6} | {d['project_name'][:30]}")
