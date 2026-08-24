# -*- coding: utf-8 -*-
# 仅把 _index=88 这一条的 lng/lat 写入 workbuddy.json（先备份，不动其他记录）
import json, sys, os, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amap_geocode as A

p = r"D:/googledownload/wangluobu_vscode/data/results/workbuddy.json"
bak = p + ".bak"
if not os.path.exists(bak):
    shutil.copy2(p, bak)
    print("已备份 ->", bak)
else:
    print("备份已存在（跳过）:", bak)

d = json.load(open(p, encoding="utf-8"))
target = next((r for r in d if r.get("_index") == 88), None)
assert target, "未找到 _index=88"

dist = target.get("district", "")
addr = A.clean_addr(target.get("location", ""))
g = A.geocode(addr, dist)
print("高德查询:", addr, "| city:", dist)
if not g:
    print("❌ 高德查不到，未修改"); sys.exit(0)
if not A.region_ok(dist, g):
    print("⚠️ 跨区错配，未修改:", g); sys.exit(0)

# 在 location 之后插入 lng/lat（保持 29 字段顺序）
new = {}
for kk, vv in target.items():
    new[kk] = vv
    if kk == "location":
        new["lng"] = g["lng"]; new["lat"] = g["lat"]
target.clear(); target.update(new)

json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("✅ 已写入 workbuddy.json")
print("  _index=88 |", target.get("project_name"))
print("  lng =", new.get("lng"), "| lat =", new.get("lat"))
keys = list(new.keys())
i = keys.index("location")
print("  字段片段(含新增):", {k: new[k] for k in keys[i:i+3]})
