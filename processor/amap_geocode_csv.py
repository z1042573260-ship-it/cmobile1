# -*- coding: utf-8 -*-
"""CSV 版高德地理编码：读 CSV -> 给每行补 lng/lat (GCJ-02) -> 写 *_geocoded.csv
用法: python amap_geocode_csv.py <输入.csv> [--district 列名] [--location 列名] [--name 列名]
列名自动识别：district/区县/区, location/地址/位置, project_name/项目名称/项目

查询策略（四级降级，尽量搜到，最后才兜底）：
  1) location 含具体街道/路口/地标 -> 用 location + city=district 编码
  2) location 空/待核实/只含区县名 -> 用「区县 + 项目名称」编码（district 为空则带「烟台市」大前缀）
  3) 高德两级都查不到/跨区 -> （agent 层 WebSearch 增强，把搜到的地址回填重编码）
  4) 仍无 -> 回退「区县中心 + 微抖动」兜底（geo_source=区县中心兜底），保证每条都有大致点
"""
import csv, json, urllib.parse, urllib.request, time, os, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = open(os.path.join(HERE, ".amap_key"), encoding="utf-8").read().strip()
BASE = "https://restapi.amap.com/v3/geocode/geo"
SLEEP = 0.4
MAX_RETRY = 5

# 烟台各区县近似中心(GCJ-02, 6位)；district 空 -> 用烟台市中心
CENTER = {
    "海阳市": (121.180000, 36.770000), "龙口市": (120.340000, 37.650000),
    "高新区": (121.430000, 37.510000), "烟台高新区": (121.430000, 37.510000),
    "莱州市": (119.940000, 37.180000), "牟平区": (121.610000, 37.390000),
    "莱山区": (121.460000, 37.510000), "福山区": (121.270000, 37.490000),
    "烟台市": (121.450000, 37.460000), "莱阳市": (120.710000, 36.970000),
    "栖霞市": (120.850000, 37.290000), "芝罘区": (121.390000, 37.540000),
    "烟台开发区": (121.170000, 37.560000), "招远市": (120.410000, 37.360000),
    "蓬莱区": (120.750000, 37.810000),
}
DEFAULT_CITY = "烟台市"
JITTER = 0.003  # 中心微抖动 ±0.003° (~±300m)，避免同区县全重合成一点

CUT_MARKS = [" 用地性质", " 项目概况", " 建设规模", " 调整内容", " 拟用地面积",
             " 公示时间", "（", "(", "\n", "；", ";"]
VAGUE_MARKS = ["待核实", "具体位置", "城区", "境内", "市区", "详见", "见附"]


def clean_addr(loc):
    if not loc:
        return ""
    s = loc
    for m in CUT_MARKS:
        i = s.find(m)
        if i > 0:
            s = s[:i]
    return s.strip().rstrip("，,。.、 ")


def norm_district(d):
    """返回有效的区县名；空/无效则回退烟台市"""
    d = (d or "").strip()
    if d in CENTER:
        return d
    for k in CENTER:
        if k in d:
            return k
    return DEFAULT_CITY


def loc_is_useful(addr, district):
    if not addr:
        return False
    if any(m in addr for m in VAGUE_MARKS):
        return False
    norm = addr.replace("山东省", "").replace("山东", "").replace("烟台市", "").replace("烟台", "").strip()
    if norm == district or norm in ("", "海阳市", "海阳", "龙口市", "莱州市", "牟平区", "莱山区",
                                     "福山区", "芝罘区", "蓬莱区", "招远市", "栖霞市", "莱阳市"):
        return False
    return True


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
                        "city": g.get("city")}
            if data.get("status") == "0" and "CUQPS" in (data.get("info") or ""):
                time.sleep(1.5 * (attempt + 1)); continue
            return None
        except Exception:
            if attempt < MAX_RETRY - 1:
                time.sleep(1.0 * (attempt + 1)); continue
            return None
    return None


def region_ok(rec_district, g):
    if not g:
        return False
    d, c = (g.get("district") or ""), (g.get("city") or "")
    if rec_district and (rec_district in d or rec_district in c):
        return True
    if rec_district == "烟台市" and "烟台" in c:
        return True
    return False


def center_fallback(district, seed):
    """区县中心 + 微抖动兜底"""
    base = CENTER.get(norm_district(district), CENTER[DEFAULT_CITY])
    random.seed(seed)
    lng = round(base[0] + random.uniform(-JITTER, JITTER), 6)
    lat = round(base[1] + random.uniform(-JITTER, JITTER), 6)
    return {"lng": lng, "lat": lat, "level": "区县中心兜底", "district": norm_district(district)}


def detect(headers, candidates):
    for c in candidates:
        if c in headers:
            return c
    return None


def main():
    if len(sys.argv) < 2:
        print("用法: python amap_geocode_csv.py <输入.csv>"); sys.exit(1)
    path = sys.argv[1]
    dist_arg = loc_arg = name_arg = None
    for a in sys.argv[2:]:
        if a.startswith("--district="): dist_arg = a.split("=", 1)[1]
        elif a.startswith("--location="): loc_arg = a.split("=", 1)[1]
        elif a.startswith("--name="): name_arg = a.split("=", 1)[1]

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)

    dk = dist_arg or detect(headers, ["district", "区县", "区", "区域", "city"])
    lk = loc_arg or detect(headers, ["location", "地址", "位置", "place", "项目地址"])
    nk = name_arg or detect(headers, ["project_name", "项目名称", "项目", "name"])
    if not lk:
        print("未找到地址列。现有列:", headers); print("请用 --location=列名 指定"); sys.exit(1)
    print(f"识别列 -> district={dk}  location={lk}  name={nk}")

    out_headers = list(headers)
    for col in ("lng", "lat", "geo_level", "geo_source"):
        if col not in out_headers:
            out_headers.append(col)
    out_path = os.path.splitext(path)[0] + "_geocoded.csv"
    filled = fb_center = empty = rejected = 0
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_headers)
        w.writeheader()
        for i, row in enumerate(rows):
            city = norm_district(row.get(dk, "") if dk else "")
            proj = (row.get(nk, "") if nk else "").strip()
            addr = clean_addr(row.get(lk, ""))
            g = None; source = ""
            if loc_is_useful(addr, city):
                g = geocode(addr, city)
                if g: source = "location"
            if not g:
                nameq = (city + " " + proj).strip()
                g2 = geocode(nameq, city)
                if g2:
                    g = g2; source = "区县+项目名称"
            if g and region_ok(city, g):
                rec = dict(row)
                rec["lng"] = g["lng"]; rec["lat"] = g["lat"]
                rec["geo_level"] = g.get("level"); rec["geo_source"] = source
                filled += 1
            else:
                # 高德两级失败/跨区 -> 区县中心 + 抖动兜底（agent 层可再用 WebSearch 增强覆盖）
                cf = center_fallback(city, i + 1)
                rec = dict(row)
                rec["lng"] = cf["lng"]; rec["lat"] = cf["lat"]
                rec["geo_level"] = "区县中心兜底"
                if g:
                    rec["geo_source"] = "跨区错配->中心兜底(" + (g.get("district") or "") + ")"
                    rejected += 1
                else:
                    rec["geo_source"] = (source + " 查不到->中心兜底") if source else "查不到->中心兜底"
                    empty += 1
                fb_center += 1
            time.sleep(SLEEP)
            w.writerow(rec)
    print(f"完成 -> {out_path}")
    print(f"准坐标 {filled} 行 | 中心兜底 {fb_center} 行(查不到{empty}/跨区{rejected}) | 共 {len(rows)} 行")


if __name__ == "__main__":
    main()
