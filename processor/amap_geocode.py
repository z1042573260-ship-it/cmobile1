# -*- coding: utf-8 -*-
"""高德地理编码：把 workbuddy.json 的 location 转成 lng/lat (GCJ-02)。
- 仅红/黄预警记录补充坐标；无预警不处理
- Key 从同目录 .amap_key 读取（不写死在代码/记忆里）
- 带 city=district 限定，提升准确率并防跨市错配
- QPS 限流自动退避重试；返回结果的行政区须与记录 district 同市才采用
- 坐标存 GCJ-02（高德原生坐标系），6 位小数，置于 location 之后
- 跑完输出「同坐标聚类报告」，列出被多个不同项目共享的坐标，便于复核误堆叠
"""
import json, urllib.parse, urllib.request, time, os

HERE = os.path.dirname(os.path.abspath(__file__))

def _load_key():
    """高德 Key：环境变量 AMAP_KEY 优先（CI/线上用 GitHub Secrets 注入），
    本地兜底读同目录 .amap_key 文件（.amap_key 被 gitignore，不入库）。"""
    env = os.getenv("AMAP_KEY", "").strip()
    if env:
        return env
    key_file = os.path.join(HERE, ".amap_key")
    if os.path.exists(key_file):
        with open(key_file, encoding="utf-8") as f:
            return f.read().strip()
    return ""

KEY = _load_key()
BASE = "https://restapi.amap.com/v3/geocode/geo"
PLACE_BASE = "https://restapi.amap.com/v3/place/text"   # POI 搜索（项目名/园区/企业检索，命中率高于 geocode）
SLEEP = 0.4          # 请求间隔，避免 QPS 限流
MAX_RETRY = 5

# 管线 L278 精度闸门：高德退回行政中心/中心点(level=省/市/城市/区县)严禁采用
COARSE_LEVEL = {"省", "市", "城市", "区县", "省份", "国家"}

# location 里常混入许可附件文字，截取地理前缀
CUT_MARKS = [" 用地性质", " 项目概况", " 建设规模", " 调整内容", " 拟用地面积",
             " 公示时间", "建筑规模", " 建筑", "规划总建筑", "（", "(", "\n", "；", ";"]

def clean_addr(loc):
    if not loc:
        return ""
    s = loc
    for m in CUT_MARKS:
        i = s.find(m)
        if i > 0:
            s = s[:i]
    return s.strip().rstrip("，,。.、 ")

def geocode(address, city):
    if not address:
        return None
    q = urllib.parse.urlencode({"key": KEY, "address": address, "city": city or ""})
    url = BASE + "?" + q
    for attempt in range(MAX_RETRY):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "workbuddy/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("status") == "1" and data.get("geocodes"):
                g = data["geocodes"][0]
                lng, lat = g["location"].split(",")
                return {"lng": round(float(lng), 6), "lat": round(float(lat), 6),
                        "level": g.get("level"), "district": g.get("district"),
                        "city": g.get("city"), "formatted": g.get("formatted_address")}
            if data.get("status") == "0" and "CUQPS" in (data.get("info") or ""):
                time.sleep(1.5 * (attempt + 1))   # 限流退避
                continue
            return None   # 真查不到
        except Exception:
            if attempt < MAX_RETRY - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None
    return None

def place_search(keywords, city):
    """高德 POI 搜索（place/text）：项目名/园区/企业检索，命中率高于 geocode。

    返回 {"lng","lat","name","address","adname","type"} 或 None。
    过滤行政区划类 POI（行政地标/地名地址信息——这类是行政区中心，精度闸门拒绝）。
    """
    if not keywords:
        return None
    q = urllib.parse.urlencode({
        "key": KEY, "keywords": keywords,
        "city": city or "烟台市", "offset": 5, "extensions": "base",
    })
    url = PLACE_BASE + "?" + q
    for attempt in range(MAX_RETRY):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "workbuddy/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("status") == "1" and data.get("pois"):
                for p in data["pois"]:
                    t = p.get("type") or ""
                    if "行政" in t or "地名地址" in t or "道路附属" in t:
                        continue
                    lng, lat = p["location"].split(",")
                    return {
                        "lng": round(float(lng), 6), "lat": round(float(lat), 6),
                        "name": p.get("name"), "address": p.get("address"),
                        "adname": p.get("adname"), "type": t,
                    }
            if data.get("status") == "0" and "CUQPS" in (data.get("info") or ""):
                time.sleep(1.5 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < MAX_RETRY - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None
    return None


def region_ok(rec_district, g):
    if not g:
        return False
    d, c = (g.get("district") or ""), (g.get("city") or "")
    rd = rec_district or ""
    # 功能区兼容：高新区/开发区是功能区，高德返回其所属真实区县（莱山区/福山区/蓬莱区），仍视为命中
    FUNCTIONAL = {
        "高新区": {"莱山区", "福山区"},
        "烟台高新区": {"莱山区", "福山区"},
        "开发区": {"福山区", "蓬莱区"},
        "烟台开发区": {"福山区", "蓬莱区"},
    }
    if rd in FUNCTIONAL:
        return d in FUNCTIONAL[rd] or rd == d or rd in (d, c)
    # 真实区县：必须精确匹配（防止跨区县错配，如海阳项目被匹配到福山/蓬莱）
    if rd and rd == d:
        return True
    if rd == "烟台市" and "烟台" in c:
        return True
    return False

def backfill(json_path):
    d = json.load(open(json_path, encoding="utf-8"))
    # 仅红/黄预警记录补充坐标（无预警不处理）
    recs = [r for r in d if r.get("warning_level") in ("红色预警", "黄色预警")]

    keys, seen = [], set()
    for r in recs:
        k = (r.get("district", ""), clean_addr(r.get("location", "")))
        if k not in seen and k[1]:
            seen.add(k); keys.append(k)

    cache = {}
    for (dist, addr) in keys:
        cache[(dist, addr)] = geocode(addr, dist)
        time.sleep(SLEEP)

    filled = empty = rejected = 0
    coord_map = {}   # (lng, lat) -> [(index, name, location)]
    for r in recs:
        dist = r.get("district", "")
        addr = clean_addr(r.get("location", ""))
        g = cache.get((dist, addr))
        if not g:
            empty += 1; continue
        if not region_ok(dist, g):
            rejected += 1; continue
        # ⚠️ 管线 L278 精度闸门：高德返回 level 为省/市/城市/区县(退回行政中心)严禁采用
        if g.get("level") in COARSE_LEVEL:
            rejected += 1; continue
        # 在 location 之后插入 lng/lat，保持 29 字段顺序
        new = {}
        for kk, vv in r.items():
            if kk in ("lng", "lat"):
                continue   # 坐标由 g 决定，不复制旧值（避免重跑时被中心点覆盖）
            new[kk] = vv
        new["lng"] = g["lng"]; new["lat"] = g["lat"]
        r.clear(); r.update(new)
        filled += 1
        coord_map.setdefault((g["lng"], g["lat"]), []).append(
            (r.get("_index"), r.get("project_name", ""), addr))

    json.dump(d, open(json_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"完成：填充 {filled} 条 | 查不到 {empty} 条 | 区域不符剔除 {rejected} 条 | 红/黄共 {len(recs)} 条")

    # ⚠️ 同坐标去重报告：列出被多个不同项目共享的坐标
    dups = {k: v for k, v in coord_map.items() if len(v) > 1}
    if dups:
        print(f"\n⚠️ 检测到 {len(dups)} 组相同坐标（共 {sum(len(v) for v in dups.values())} 条记录共享）：")
        for (lng, lat), items in dups.items():
            print(f"  ▶ ({lng}, {lat}) 被 {len(items)} 条共享：")
            for idx, name, loc in items:
                print(f"      _index={idx} | {name} | location={loc!r}")
        print("  → 同一产业园多期项目同点属正常；若 location 笼统导致批量同点，应回退更细地址或人工复核。")
    else:
        print("\n✅ 无重复坐标（各项目坐标唯一）")

if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else r"D:/googledownload/wangluobu_vscode/data/results/workbuddy.json"
    backfill(p)
