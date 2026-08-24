# -*- coding: utf-8 -*-
"""下载 ArcGIS 街道瓦片 → 拼接成各区县/烟台整体离线底图 js/district-tiles/*.jpg"""
import json, math, os, time, io
import urllib.request
from PIL import Image

BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'
OUT = os.path.join(os.path.dirname(__file__), '..', 'js', 'district-tiles')
os.makedirs(OUT, exist_ok=True)
HDR = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def lon2x(lng, z): return (lng + 180.0) / 360.0 * (1 << z)   # 瓦片号（非像素）
def lat2y(lat, z):
    lat = lat * math.pi / 180.0
    return (1.0 - math.log(math.tan(lat) + 1.0 / math.cos(lat)) / math.pi) / 2.0 * (1 << z)

def fetch_tile(z, x, y):
    url = BASE.format(z=z, y=y, x=x)
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except Exception:
            time.sleep(1)
    return None

def stitch(name, minLng, maxLng, minLat, maxLat, z):
    out = os.path.join(OUT, name + '.jpg')
    if os.path.exists(out):
        print(name, '已存在，跳过', flush=True)
        return
    x0, x1 = math.floor(lon2x(minLng, z)), math.floor(lon2x(maxLng, z))
    y0, y1 = math.floor(lat2y(maxLat, z)), math.floor(lat2y(minLat, z))
    cols, rows = x1 - x0 + 1, y1 - y0 + 1
    if cols * rows > 500:
        print(name, '瓦片过多', cols, 'x', rows, '跳过', flush=True)
        return
    img = Image.new('RGB', (cols * 256, rows * 256))
    ok = 0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            data = fetch_tile(z, x, y)
            if data:
                t = Image.open(io.BytesIO(data)).convert('RGB')
                img.paste(t, ((x - x0) * 256, (y - y0) * 256))
                ok += 1
            time.sleep(0.06)
    if ok == 0:
        print(name, '全部失败', flush=True)
        return
    img.save(os.path.join(OUT, name + '.jpg'), quality=88)
    print(name, 'OK', cols, 'x', rows, '成功', ok, flush=True)

# 各区县 bbox（z=13，街道细节可见小区）
d = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'js', 'yantai.json'), encoding='utf-8'))
for f in d['features']:
    name = f['properties']['name']
    t = f['geometry']['type']
    polys = f['geometry']['coordinates'] if t == 'MultiPolygon' else [f['geometry']['coordinates']]
    lngs, lats = [], []
    for p in polys:
        for ring in p:
            for pt in ring:
                lngs.append(pt[0]); lats.append(pt[1])
    print('下载', name, 'z=13', flush=True)
    stitch(name, min(lngs), max(lngs), min(lats), max(lats), 13)

# 烟台整体（z=11）
print('下载 烟台整体 z=11', flush=True)
stitch('yantai', 119.6, 122.7, 36.6, 38.5, 11)
print('完成', flush=True)
