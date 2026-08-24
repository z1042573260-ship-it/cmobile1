# -*- coding: utf-8 -*-
"""给 workbuddy2.json 的红/黄预警记录补 GCJ-02 经纬度（复用 amap_geocode）。

地址降级链（任一成功即用）：
  1. 记录内 location（内容摘要解析出的具体地址）
  2. 真实项目名 + 区县
  3. 真实项目名
  4. 区县中心（兜底，geo_source 标 center_estimate）

- city 限定：district 在标准区县内则用 district；待核实则用"烟台市"
- 精度闸门：高德返回 level 为 省/市/区县 视为中心点，geo_source=center_estimate
- region_ok 区域校验：跨市/跨区县错配直接丢弃（坐标留空），district=待核实 不校验
"""
import json, os, time
from collections import Counter
from amap_geocode import geocode, clean_addr, region_ok

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = r"D:\googledownload\wangluobu_vscode\data\results\workbuddy2.json"
COARSE = {"省", "市", "城市", "区县", "国家", "乡镇"}

def city_of(district):
    if not district or district == "待核实":
        return "烟台市"
    return district

def main():
    d = json.load(open(OUT, encoding="utf-8"))
    recs = [r for r in d if r.get("warning_level") in ("红色预警", "黄色预警")]
    cache = {}
    def q(city, addr):
        if not addr:
            return None
        k = (city, addr)
        if k not in cache:
            cache[k] = geocode(addr, city)
            time.sleep(0.35)
        return cache[k]

    filled = precise = center = rejected = 0
    coord_map = {}
    for r in recs:
        c = city_of(r.get("district"))
        loc = clean_addr(r.get("location") or "")
        real = r.get("real_name") or ""
        g = None; used = ""
        if loc:
            g = q(c, loc); used = "loc"
        if not g and real:
            g = q(c, real + " " + c); used = "real+city"
        if not g and real:
            g = q(c, real); used = "real"
        if not g:
            g = q(c, c); used = "city_center"   # 兜底：区县中心
        if not g:
            r["geo_source"] = "failed"
            continue
        if used == "city_center":
            # 兜底中心，level 视为粗，直接存
            r["lng"] = g["lng"]; r["lat"] = g["lat"]; r["geo_source"] = "center_estimate"
            center += 1; filled += 1
        else:
            if r.get("district") != "待核实" and not region_ok(r.get("district"), g):
                r["geo_source"] = "region_mismatch"
                rejected += 1
                continue
            r["lng"] = g["lng"]; r["lat"] = g["lat"]
            lvl = g.get("level") or ""
            if lvl in COARSE:
                r["geo_source"] = "center_estimate"; center += 1
            else:
                r["geo_source"] = "amap"; precise += 1
            filled += 1
        coord_map.setdefault((r["lng"], r["lat"]), []).append(
            (r.get("_index"), r.get("project_name", ""), used))

    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"完成：填充 {filled} | 精确(amap) {precise} | 中心估算 {center} | 区域不符 {rejected} | 红/黄共 {len(recs)} | 查询 {len(cache)} 次")
    print("geo_source 分布:", dict(Counter(r.get("geo_source") for r in d)))
    dups = {k: v for k, v in coord_map.items() if len(v) > 1}
    if dups:
        print(f"\n⚠️ {len(dups)} 组相同坐标（共 {sum(len(v) for v in dups.values())} 条）：")
        for (lng, lat), items in list(dups.items())[:20]:
            print(f"  ({lng},{lat}) x{len(items)}: " + " | ".join(f"{n}({u})" for _, n, u in items[:4]))
    else:
        print("\n✅ 无重复坐标")

if __name__ == "__main__":
    main()
