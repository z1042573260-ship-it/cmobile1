# -*- coding: utf-8 -*-
"""geocode 跑完后，用修正后的分类逻辑重算 workbuddy2 的分类字段，保留已算好的经纬度。

仅重算分类相关字段（project_type/need_base_station/base_station_type/score/priority/
warning_level/is_valuable/telecom_needs/ai_reason/ai_summary/coverage_area），保留
lng/lat/geo_source/_index/_title/location/source*/publish_date/content/scale/investment 等。
无预警者按导出口径剔除。
"""
import json, os
from build_workbuddy2 import (
    detect_project_type, detect_need_base, detect_base_station_type,
    parse_invest_wan, detect_stage, compute_score, compute_priority, warning_of,
    build_telecom_needs, build_ai_reason, build_ai_summary, build_coverage, PURE_PROCESS,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = r"D:\googledownload\wangluobu_vscode\data\results\workbuddy2.json"

def main():
    d = json.load(open(OUT, encoding="utf-8"))
    new = []
    dropped = 0
    changed_type = 0
    for r in d:
        title = r.get("_title", "")
        content = r.get("content", "") or ""
        scale = r.get("scale", "") or ""
        invest = r.get("investment", "") or "待核实"
        # 纯流程公告分流
        if any(k in title for k in PURE_PROCESS):
            dropped += 1
            continue
        pt = detect_project_type(None, title, content)
        if pt != r.get("project_type"):
            changed_type += 1
        nbs = detect_need_base(pt, scale, title)
        bst = detect_base_station_type(pt, scale, title, content)
        invest_wan = parse_invest_wan(invest)
        stage = detect_stage(title, content)
        score = compute_score(pt, invest_wan, stage, title)
        warning = warning_of(score, title)
        priority = compute_priority(pt, scale, stage)
        is_val = warning != "无预警"
        if not is_val:
            dropped += 1
            continue
        telecom = build_telecom_needs(pt, bst, scale, nbs)
        ai_reason = build_ai_reason(pt, scale, invest, r.get("district", ""), nbs, bst, stage, title)
        ai_summary = build_ai_summary(pt, nbs, bst, r.get("district", ""), stage)
        coverage = build_coverage(scale)
        r.update({
            "project_type": pt,
            "need_base_station": nbs,
            "base_station_type": bst,
            "score": score,
            "priority": priority,
            "warning_level": warning,
            "is_valuable": is_val,
            "telecom_needs": telecom,
            "ai_reason": ai_reason,
            "ai_summary": ai_summary,
            "coverage_area": coverage,
        })
        new.append(r)
    json.dump(new, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    from collections import Counter
    print(f"补丁完成：剔除 {dropped} 条 | 类型被修正 {changed_type} 条 | 保留 {len(new)} 条")
    print("  warning_level:", dict(Counter(x["warning_level"] for x in new)))
    print("  project_type:", dict(Counter(x["project_type"] for x in new)))
    print("  need_base_station:", dict(Counter(x["need_base_station"] for x in new)))
    print("  geo_source:", dict(Counter(x.get("geo_source") for x in new)))

if __name__ == "__main__":
    main()
