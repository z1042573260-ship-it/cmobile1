# -*- coding: utf-8 -*-
"""
施工交底 Excel → 前端施工图数据（frontend/data/engineering.json）

用法:
    python scripts/excel_to_engineering.py
    python scripts/excel_to_engineering.py --excel "C:/Users/xxx/Desktop/施工.xlsx"
    python scripts/excel_to_engineering.py --out frontend/data/engineering.json

Excel 列（表头固定，按位置读取，勿改列序）:
    [0] 区县  [1] 级别(干线:红/骨干汇聚:橙/其他:黄)  [2] 目前状态
    [3] 是否交底 [4] 交底日期  [5] 施工起点经纬度  [6] 施工终点经纬度  [7] 道路名称
    [8] 移动交底人电话 [9] 施工方交底人电话 [10] 交底范围描述
    [11] 影响光缆条数 [12] 施工段落公里数 [13] 影响业务最高级别 [14] 施工影响主要业务描述
    [15] 光缆埋深 [16] 施工预计工期 [17] 盯防 [18] 现场盯防电话

坐标清洗支持历史数据全部脏格式:
    全角/半角逗号、空格、换行分隔; g 前缀 (g121.xx); 顿号当小数点 (121、321587E);
    E/N 后缀; 经度纬度反序 (37.5,121.2 → 自动交换)。

输出 JSON 结构与前端约定:
    district_ranking: [{name: 标准区县名, value: 该区县道路条数(含无坐标)}]
    roads[].name/district(标准名)/level(字面色红橙黄)/status(标准状态)/
          start/end([lng,lat], 无坐标或缺半段 = null)/length_km/jiaodi/jiaodi_date/
          cable_count/biz_level/biz_desc
"""
import argparse
import datetime
import json
import os
import re
import sys
from collections import OrderedDict

DEFAULT_EXCEL = os.path.join(os.path.expanduser('~'), 'Desktop', '施工.xlsx')
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'frontend', 'data', 'engineering.json')

# Excel 简称 → 前端标准区县名（必须与 DISTRICT_CENTERS / geojson properties.name 一致）
DISTRICT_MAP = {
    '海阳': '海阳市', '龙口': '龙口市', '莱阳': '莱阳市', '莱州': '莱州市',
    '招远': '招远市', '栖霞': '栖霞市', '蓬莱': '蓬莱区', '芝罘': '芝罘区',
    '福山': '福山区', '牟平': '牟平区', '莱山': '莱山区',
    '开发': '开发区', '高新': '高新区',
}

STATUS_FIX = {'己完工': '已完工'}   # 常见错别字归一
STATUS_OK = ('施工中', '已完工', '未开工', '暂停施工')

# 烟台地理范围（坐标合法性 + 经纬度反序自动交换用）
LNG_MIN, LNG_MAX = 119.5, 123.5
LAT_MIN, LAT_MAX = 36.0, 38.5


def norm_district(name):
    name = str(name or '').strip()
    return DISTRICT_MAP.get(name, name)


def norm_status(st):
    st = str(st or '').strip()
    return STATUS_FIX.get(st, st)


def parse_date(v):
    """交底日期: datetime/序列号/字符串 → 'YYYY.M.D' 字符串"""
    if v is None:
        return ''
    if isinstance(v, datetime.datetime):
        return '%d.%d.%d' % (v.year, v.month, v.day)
    if isinstance(v, datetime.date):
        return '%d.%d.%d' % (v.year, v.month, v.day)
    if isinstance(v, (int, float)):
        # Excel 日期序列号 (1900 系统): 1899-12-30 起算
        try:
            d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))
            return '%d.%d.%d' % (d.year, d.month, d.day)
        except Exception:
            return str(v)
    s = str(v).strip()
    return s


def clean_coord(text):
    """脏坐标文本 → [lng, lat] | None（解析不了返回 None，由调用方决定跳过画线）

    处理: g前缀 / 顿号当小数点 / E N 后缀 / 全角半角逗号·空格·换行分隔 / 经纬度反序
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    # 1) g 前缀（g121.xx / G121.xx）
    s = re.sub(r'^[gG]', '', s.strip())
    # 2) 顿号当小数点（121、321587）
    s = s.replace('、', '.')
    # 3) 去掉 E/N/W/S 后缀（121.39399E → 121.39399）
    s = re.sub(r'[EWSNewsn]\s*$', '', s.strip())
    # 4) 统一分隔
    parts = re.split(r'[\s,，;；]+', s.strip())
    nums = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            nums.append(float(p))
        except ValueError:
            return None   # 含非数字残留 → 放弃整格
    if len(nums) == 2:
        a, b = nums
        # 5) 经纬度反序自动交换（lng∈[119.5,123.5] lat∈[36,38.5]）
        if (LNG_MIN <= a <= LNG_MAX and LAT_MIN <= b <= LAT_MAX):
            return [a, b]
        if (LNG_MIN <= b <= LNG_MAX and LAT_MIN <= a <= LAT_MAX):
            return [b, a]
        return None   # 范围外 → 不可信
    return None       # 少于/多于两数 → 无法构成线段


def text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v == int(v):
        return str(int(v))          # 13.0 → '13'
    return str(v).strip()


def num(v):
    """公里数/光缆条数 → int/float|None"""
    s = text(v)
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else round(f, 3)


def main():
    ap = argparse.ArgumentParser(description='施工交底 Excel → frontend/data/engineering.json')
    ap.add_argument('--excel', default=DEFAULT_EXCEL, help='Excel 路径（默认桌面 施工.xlsx）')
    ap.add_argument('--out', default=DEFAULT_OUT, help='输出 JSON 路径')
    args = ap.parse_args()

    if not os.path.exists(args.excel):
        sys.exit('找不到 Excel: %s' % args.excel)

    import openpyxl
    wb = openpyxl.load_workbook(args.excel, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        sys.exit('Excel 无数据行')
    header = rows[0]

    roads, skipped = [], []
    by_district = OrderedDict()
    for i, r in enumerate(rows[1:], 2):   # 行号从 1 计（表头第1行）
        district = norm_district(header and r[0])
        name = re.sub(r'\s+', ' ', text(r[7]) or text(r[0])).strip() or ('第%d行' % i)
        level = text(r[1])
        status = norm_status(text(r[2]))
        if status not in STATUS_OK:
            status = status or '施工中'
        start = clean_coord(r[5])
        end = clean_coord(r[6])
        length_km = num(r[12])
        cable_count = num(r[11])

        road = {
            'name': name,
            'district': district,
            'level': level,
            'status': status,
            'road': name,
            'start': start,
            'end': end,
            'length_km': length_km,
            'jiaodi': text(r[3]),
            'jiaodi_date': parse_date(r[4]),
            'cable_count': cable_count,
            'biz_level': text(r[13]),
            'biz_desc': text(r[14]),
        }
        if not start or not end:
            skipped.append((i, district, name, '坐标缺失/无法解析'))
        elif length_km and length_km > 0.05:
            # 直线跨度 vs 公里数差异 > 8 倍 → 疑似坐标有误，提示人工核对
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            straight_km = (dx * dx + dy * dy) ** 0.5 * 101.0   # 约 101 km/度
            if straight_km > length_km * 8:
                skipped.append((i, district, name,
                                '跨度 %.1fkm vs 标注 %.2fkm，疑似坐标错误' % (straight_km, length_km)))
                # 跨度 >10km 且与标注长度矛盾（如标注 0.2km 坐标跨 24km）：图上不拉长假线，
                # 前端改画"中点施工点"（coord_conflict 标记）
                if straight_km > 10:
                    road['coord_conflict'] = True
        by_district.setdefault(district, 0)
        by_district[district] += 1
        roads.append(road)

    ranking = [{'name': d, 'value': c}
               for d, c in sorted(by_district.items(), key=lambda kv: -kv[1])]

    out = {
        '_comment': '施工图数据（由 scripts/excel_to_engineering.py 从施工 Excel 生成，勿手改）。'
                    'district 用标准区县名；level=红(干线)/橙(骨干汇聚)/黄(其他)；'
                    'status=施工中/已完工/未开工/暂停施工；start/end=[lng,lat]，无坐标=null（地图不画线仅列表）；'
                    'cable_count=影响光缆条数, biz_level=影响业务最高级别, biz_desc=施工影响主要业务描述。',
        'source_file': os.path.basename(args.excel),
        'generated_at': datetime.date.today().isoformat(),
        'district_ranking': ranking,
        'roads': roads,
    }

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ---------- 摘要输出 ----------
    print('生成 %s' % args.out)
    print('总道路 %d 条 / 区县 %d 个' % (len(roads), len(ranking)))
    for d in ranking:
        print('  %-4s %d 条' % (d['name'], d['value']))
    if skipped:
        print('\n⚠ 未画线（列表仍显示）或需人工核对 %d 条:' % len(skipped))
        for row, d, n, why in skipped:
            print('  行%d %s %s —— %s' % (row, d, n, why))
        print('  提示: 坐标缺失/起终点相同的地图无法画线，请在 Excel 补全/修正坐标后重跑本脚本')
    else:
        print('\n坐标全部可用，无跳过。')


if __name__ == '__main__':
    main()
