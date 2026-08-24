# -*- coding: utf-8 -*-
"""增强补全：仅对 workbuddy.json 中【当前缺失 lng/lat 的红/黄预警】记录补坐标。
- 复用 amap_geocode 的 geocode + 修正后的 region_ok（功能区兼容）
- city 统一用『烟台市』以提升命中
- 高德仍 None 的，用联网搜到的权威坐标(GCJ-02, 腾讯地图)兜底
"""
import json, urllib.parse, urllib.request, time, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from amap_geocode import geocode, region_ok, clean_addr, SLEEP

# 高德查不到、但联网搜到的权威坐标(GCJ-02)：
COORD_OVERRIDE = {
    # 海阳中心渔港（海核路南、寨前村南）——腾讯地图中心点
    120: (121.311635, 36.705924), 166: (121.311635, 36.705924),
    175: (121.311635, 36.705924), 176: (121.311635, 36.705924),
    # 万木森林幼儿园（乐山街东、南修家村）——腾讯地图 POI
    125: (121.202192, 36.774952), 174: (121.202192, 36.774952), 182: (121.202192, 36.774952),
    # 紫薇学府二期（海盛路北、垛山街西）——腾讯地图小区中心
    100: (121.182780, 36.768427),
    # 万华化学绿电产业园一期磷酸铁锂（海滨西路南、碧桂园东）——万华绿电产业园园区坐标
    136: (121.062746, 36.626723), 145: (121.062746, 36.626723),
    # 万华新一代电池材料产业园一期分散式风电（地块二，绿电中路西）——同园区坐标
    94: (121.062746, 36.626723),
    # 牟平区2025年建设用地（牟征预公告4007号）大窑街道东吕格庄村
    187: (121.658576, 37.417959),
    # 丰金·云海安澜（高新区滨海路南、海博路西）——腾讯地图 POI
    275: (121.497114, 37.454196),
}

# 高德用 location 查不到、改用联网搜到的精确地址再编码
WEB_ADDR = {
    271: "山东省烟台市高新区西谭家泊村辛安河污水处理厂",
    304: "山东省烟台市高新区",
    305: "山东省烟台市高新区",
}

def backfill_empty(json_path):
    d = json.load(open(json_path, encoding="utf-8"))
    empties = [r for r in d if r.get("warning_level") in ("红色预警", "黄色预警")
               and "lng" not in r]
    filled = rejected = override = still_empty = 0
    for r in empties:
        dist = r.get("district", "")
        idx = r.get("_index")
        addr = clean_addr(r.get("location", ""))
        g = geocode(addr, "烟台市") if addr else None
        if (not g or not region_ok(dist, g)) and idx in WEB_ADDR:
            g = geocode(WEB_ADDR[idx], "烟台市")
        if g and region_ok(dist, g):
            new = {}
            for kk, vv in r.items():
                new[kk] = vv
                if kk == "location":
                    new["lng"] = g["lng"]; new["lat"] = g["lat"]
            if "location" not in new:
                new["lng"] = g["lng"]; new["lat"] = g["lat"]
            new["geo_source"] = "高德+区域兼容"
            r.clear(); r.update(new)
            filled += 1
            time.sleep(SLEEP)
            continue
        if idx in COORD_OVERRIDE:
            lng, lat = COORD_OVERRIDE[idx]
            new = {}
            for kk, vv in r.items():
                new[kk] = vv
                if kk == "location":
                    new["lng"] = lng; new["lat"] = lat
            if "location" not in new:
                new["lng"] = lng; new["lat"] = lat
            new["geo_source"] = "联网搜索增强(腾讯GCJ-02)"
            r.clear(); r.update(new)
            override += 1
            continue
        still_empty += 1

    json.dump(d, open(json_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"增强完成：高德补 {filled} | 联网兜底 {override} | 仍空 {still_empty} | 处理 {len(empties)} 条")

if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else r"D:/googledownload/wangluobu_vscode/data/results/workbuddy.json"
    backfill_empty(p)
