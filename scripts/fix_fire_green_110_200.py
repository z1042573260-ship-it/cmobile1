# -*- coding: utf-8 -*-
"""按"施工建设前兆识别框架"重判 workbuddy.json 中误判为无预警的
消防审查(169/173/183) 与 绿地树木审批(112/122/147) 记录。
115(铁塔本身即基站)、130(供水管道改造无新增建筑) 保持原样。"""
import json

JSON_PATH = r"D:\googledownload\wangluobu_vscode\data\results\workbuddy.json"

UPDATES = {
    112: dict(
        warning_level="黄色预警", is_valuable=True, score=3, priority=3,
        need_base_station="有", base_station_type="宏站",
        status="施工阶段（开路口=施工进场信号）",
        location="海阳市海裕路（晓龙明珠项目）",
        developer="山东晓龙集团有限公司",
        coverage_area="海阳市海裕路晓龙明珠项目",
        ai_reason="【项目本质】本条为海阳市工程建设涉及城市绿地、树木审批办理结果公示，许可对象为「晓龙明珠项目开路口」（海裕路），有效期限2026.04.03-2027.04.03。开路口=临路接通，是施工马上开始的进场信号。【基站需求】晓龙明珠为新建建筑项目，需宏站覆盖保障施工期及后续运营信号。【商机情报】开路口审批表明项目已进入施工准备阶段，是抢占市场的早期切入点，纳入跟进列表。",
        ai_summary="晓龙明珠项目获开路口审批（海裕路），施工进场信号，黄色预警待跟进。",
        telecom_needs=["小区宏站覆盖", "施工期通信保障"],
    ),
    122: dict(
        warning_level="黄色预警", is_valuable=True, score=3, priority=3,
        need_base_station="有", base_station_type="宏站",
        status="施工阶段（开路口=施工进场信号）",
        location="海阳市疏港路东（盛强加油站）",
        developer="烟台盛强加油站",
        coverage_area="海阳市疏港路东盛强加油站",
        ai_reason="【项目本质】本条为绿地树木审批办理结果公示，许可对象为「烟台盛强加油站开路口」（疏港路东），有效期限2026.03.26-2027.03.26。开路口=临路接通，施工进场信号。【基站需求】加油站新建/改扩建需宏站覆盖。【商机情报】开路口审批表明项目进入施工准备，可提前切入通信配套。",
        ai_summary="盛强加油站获开路口审批（疏港路东），施工进场信号，黄色预警。",
        telecom_needs=["加油站宏站覆盖", "施工期通信保障"],
    ),
    147: dict(
        warning_level="黄色预警", is_valuable=True, score=3, priority=2,
        need_base_station="有", base_station_type="宏站",
        status="施工阶段（橡胶坝施工）",
        location="海阳市石人泊村南湿地公园（东村河4号橡胶坝）",
        developer="山东仲舜建设工程有限公司",
        coverage_area="海阳市石人泊村南湿地公园东村河4号橡胶坝",
        ai_reason="【项目本质】本条为绿地树木审批办理结果公示，许可对象为「东村河4号橡胶坝施工」（石人泊村南湿地公园），有效期限2026.03.03起。橡胶坝为水利市政新建工程实体。【基站需求】湿地公园/河道区域偏远，需宏站补盲覆盖施工期及后期运维。【商机情报】水利市政新建工程，早期信号，可跟进通信配套。",
        ai_summary="东村河4号橡胶坝施工获绿地审批（石人泊村南湿地公园），水利市政新建，黄色预警。",
        telecom_needs=["偏远区域宏站补盲", "施工期通信保障"],
    ),
    169: dict(
        warning_level="红色预警", is_valuable=True, score=5, priority=5,
        need_base_station="有", base_station_type="宏站+室分",
        status="施工阶段（消防设计审查过审=确实在建）",
        location="海阳市凤兴路北、凤仪路西地块（航天小学A、B地块）",
        developer="海阳市昊海城市开发建设集团有限公司",
        coverage_area="海阳市凤兴路北、凤仪路西航天小学A/B地块",
        ai_reason="【项目本质】本条为特殊建设工程消防设计审查办理结果公示，许可对象为「航天小学（A、B地块）」（海阳市凤兴路北、凤仪路西），证号海审批投资特消准决字[2026]03号。消防设计审查过审=项目确实在建/要建，建设确定性高。【基站需求】学校A、B地块多栋教学楼，需宏站+室分覆盖保障师生通信。【商机情报】航天小学为政府平台公司（昊海城市开发建设集团）开发的大规模教育基建，战略价值高，消防过审表明进入实质建设期，红色预警重点跟进。",
        ai_summary="航天小学A/B地块消防设计审查过审（凤兴路北/凤仪路西），确实在建，红色预警重点跟进。",
        telecom_needs=["校园宏站覆盖", "教学楼室分", "政企专线/教育信息化"],
    ),
    173: dict(
        warning_level="黄色预警", is_valuable=True, score=2, priority=2,
        need_base_station="有", base_station_type="室分",
        status="施工阶段（消防改造施工）",
        location="海阳市榆山街4号（英才幼儿园）",
        developer="海阳市英才幼儿园有限公司",
        coverage_area="海阳市榆山街4号英才幼儿园",
        ai_reason="【项目本质】本条为特殊建设工程消防设计审查办理结果公示，许可对象为「海阳市英才幼儿园有限公司消防改造」（榆山街4号），证号海审批投资特消准决字[2026]02号。属既有建筑消防改造（非新建），消防过审表明改造施工进行中。【基站需求】既有幼儿园改造，室内分布系统可优化覆盖。【商机情报】消防改造为既有建筑升级，价值低于新建，黄色预警低优先级跟进。",
        ai_summary="英才幼儿园消防改造过审（榆山街4号），既有建筑改造，黄色预警低优先级。",
        telecom_needs=["既有建筑室分优化"],
    ),
    183: dict(
        warning_level="黄色预警", is_valuable=True, score=2, priority=2,
        need_base_station="有", base_station_type="宏站",
        status="施工阶段（消防设计审查过审=确实在建/要建）",
        location="海阳市烟海高速路南出口东侧（盛强加油站）",
        developer="烟台盛强加油站",
        coverage_area="海阳市烟海高速路南出口东侧盛强加油站",
        ai_reason="【项目本质】本条为特殊建设工程消防设计审查办理结果公示，许可对象为「烟台盛强加油站」（烟海高速路南出口东侧），证号海审批投资特消准决字[2026]01号。消防过审=加油站确实施工/要建。【基站需求】加油站需宏站覆盖保障运营通信。【商机情报】小型站点，黄色预警低优先级跟进。",
        ai_summary="盛强加油站消防设计审查过审（烟海高速南出口东），确实施工，黄色预警。",
        telecom_needs=["加油站宏站覆盖"],
    ),
}

with open(JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)

updated = 0
for d in data:
    i = d.get("_index")
    if i in UPDATES:
        d.update(UPDATES[i])
        updated += 1

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ 已重判 {updated} 条记录")
print("已更新 _index:", sorted(UPDATES.keys()))
print("未改动（保持原样）: 115(铁塔基站)、130(供水管道改造)")
