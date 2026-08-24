import json, urllib.parse, urllib.request

KEY = open(r"D:/googledownload/wangluobu_vscode/processor/.amap_key", encoding="utf-8").read().strip()
print("Key 长度:", len(KEY), "前缀:", KEY[:6], "...")

BASE = "https://restapi.amap.com/v3/geocode/geo"

# 之前 OSM 全 EMPTY / 错配 的样本，验证高德能否命中
tests = [
    ("海阳市凤城街道益海路东兴港路南", "烟台"),
    ("烟台市牟平区姜格庄街道环湾东路", "烟台"),
    ("烟台市牟平区观水镇辽上村", "烟台"),
    ("烟台市高新区学府东路以北航路以东", "烟台"),
    ("烟台市福山区西二路以东金山路以北", "烟台"),
    ("海阳市东村街道北山公园", "烟台"),  # 之前错配到即墨
]

for addr, city in tests:
    q = urllib.parse.urlencode({"key": KEY, "address": addr, "city": city})
    url = BASE + "?" + q
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "workbuddy/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        status = data.get("status")
        if status == "1" and data.get("geocodes"):
            g = data["geocodes"][0]
            print(f"[OK] {addr}\n     坐标={g['location']}  级别={g.get('level')}  行政区={g.get('district')}  地址={g.get('formatted_address')}")
        else:
            print(f"[FAIL] {addr}  status={status}  info={data.get('info')}  count={data.get('count')}")
    except Exception as e:
        print(f"[ERR] {addr}  {type(e).__name__}: {e}")
