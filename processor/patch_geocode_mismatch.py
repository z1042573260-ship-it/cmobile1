# -*- coding: utf-8 -*-
"""补丁：把 geo_source=region_mismatch（具体地址/项目名查到的坐标与区县不符）的记录，
改为用「区县中心」兜底（geo_source=center_estimate），至少落对区县，而非留空。"""
import json, os, time
from amap_geocode import geocode

OUT = r"D:\googledownload\wangluobu_vscode\data\results\workbuddy2.json"

def city_of(d):
    return d if (d and d != "待核实") else "烟台市"

def main():
    d = json.load(open(OUT, encoding="utf-8"))
    n_fixed = 0
    seen = {}
    for r in d:
        if r.get("geo_source") != "region_mismatch":
            continue
        c = city_of(r.get("district"))
        if c not in seen:
            seen[c] = geocode(c, c)
            time.sleep(0.3)
        g = seen[c]
        if g:
            r["lng"] = g["lng"]; r["lat"] = g["lat"]
            r["geo_source"] = "center_estimate"
            n_fixed += 1
        else:
            r["geo_source"] = "failed"
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"补丁完成：补充 center_estimate {n_fixed} 条（原 region_mismatch 改区县中心兜底）")

if __name__ == "__main__":
    main()
