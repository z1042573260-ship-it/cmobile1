"""
全库数据归档修复（2026-08-19）
--------------------------------
workbuddy 导入后大屏数据质量修复，幂等可重复跑：

1. project_type 归档为 13 类规范（工业厂房/仓储物流/住宅小区/商业综合体/
   学校/医院/工业园区/市政设施/交通工程/能源电力/科研设施/景区文旅/其他）
   - 无法命中的（含"待核实"）→ "其他"，同时生成未归档清单供人工确认
2. district 归一化：烟台高新区→高新区、烟台开发区→开发区（前端短名体系）
3. publish_date 归一化：2026.02.06 → 2026-02-06（时间趋势月份桶统一）

注：status（阶段）保留 AI 完整描述入库（详情页展示），大屏分组的 5 类阶段
归档在 export_dashboard_db.py 与前端 js.js 两层做（stage_of 映射）。

用法：
  python scripts/archive_project_types.py
输出：归档后统计 + data/results/unclassified_types.json + .xlsx（未归档清单）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pymysql
except ImportError:
    print("[ERROR] 需要 pymysql：pip install pymysql")
    sys.exit(1)

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    from config.settings import DATABASE_URL
except Exception:
    DATABASE_URL = "mysql+pymysql://root:1234@localhost:3306/yantai_projects"

# ---- 13 类规范（与 ai_pipeline.py 提示词、前端渲染一致）----
STANDARD_TYPES = [
    "工业园区", "能源电力", "工业厂房", "医院", "住宅小区", "商业综合体",
    "学校", "仓储物流", "市政设施", "交通工程", "科研设施", "景区文旅", "其他",
]

# 匹配顺序即优先级：先命中的先归（项目类型字段 → 项目名 → 正文兜底）
TYPE_RULES = [
    ("工业园区", re.compile(r"产业园|工业园区|科技城|产业基地|产业园区|园区")),
    ("能源电力", re.compile(r"电力|变电站|储能|光伏|风电|能源|电池|充电|天然气|供热|新能源")),
    ("工业厂房", re.compile(r"厂房|车间|工业|加工|厂区|制造业|生产|织造|工业建筑")),
    ("医院",     re.compile(r"医院|医疗|门诊|卫生|健康中心")),
    ("住宅小区", re.compile(r"住宅|安置|棚改|小区|公寓|保障房|安居")),
    ("商业综合体", re.compile(r"商业|商场|综合体|写字楼|酒店|商铺")),
    ("学校",     re.compile(r"学校|校区|教育|教学楼|幼儿园|学院")),
    ("仓储物流", re.compile(r"仓储|仓库|冷链|物流|配送中心")),
    ("市政设施", re.compile(r"市政|供水|排水|管网|路灯|污水|环卫|供水设施|停车")),
    ("交通工程", re.compile(r"道路|桥梁|隧道|公路|农村路|机场|码头|渔港|港口|交通")),
    ("科研设施", re.compile(r"科研|实验室|研发|检测中心|科创")),
    ("景区文旅", re.compile(r"景区|文旅|旅游|公园|场馆|文化")),
]


def archive_type(project_type: str, project_name: str, content: str) -> tuple[str, str]:
    """返回 (归档类型, 匹配依据字段)。规则命中即定；全部落空 → 其他"""
    texts = {
        "type": project_type or "",
        "name": project_name or "",
        "content": (content or "")[:2000],   # 正文兜底只取前段
    }
    for label, pat in TYPE_RULES:
        for field in ("type", "name", "content"):
            if pat.search(texts[field]):
                return label, field
    return "其他", "fallback"


def parse_db_url(url: str) -> dict:
    core = url.split("://", 1)[1]
    cred, rest = core.split("@", 1)
    user, pwd = cred.split(":", 1)
    host_port, db = rest.split("/", 1)
    host, port = host_port.split(":", 1) if ":" in host_port else (host_port, "3306")
    return {"user": user, "password": pwd, "host": host, "port": int(port), "database": db}


def main():
    cfg = parse_db_url(DATABASE_URL)
    conn = pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=cfg["database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, project_name, project_type, content, district, publish_date FROM projects")
            rows = list(cur.fetchall())
    finally:
        conn.close()

    print(f"[DB] 读取 {len(rows)} 条")

    # ---------- 1. project_type 归档 ----------
    from collections import Counter
    before = Counter((r["project_type"] or "（空）") for r in rows)
    updates, unclassified = [], []
    for r in rows:
        new_t, matched = archive_type(r["project_type"], r["project_name"], r["content"])
        if new_t != r["project_type"]:
            updates.append((new_t, r["id"]))
        # 未归档清单：归档结果为"其他"且原值不是规范类（无法命中的）
        if new_t == "其他" and (r["project_type"] or "").strip() not in STANDARD_TYPES:
            unclassified.append({
                "id": r["id"], "project_name": r["project_name"],
                "原类型": r["project_type"], "归档结果": new_t, "匹配依据": matched,
            })
    print(f"[类型] 需更新 {len(updates)} 条（含 {len(unclassified)} 条归入\"其他\"的未归档记录）")

    # ---------- 2. district 归一化 ----------
    district_map = {"烟台高新区": "高新区", "烟台开发区": "开发区"}
    d_updates = sum(1 for r in rows if r["district"] in district_map)
    print(f"[区县] 归一化 {d_updates} 条：烟台高新区→高新区、烟台开发区→开发区")

    # ---------- 3. publish_date 归一化 ----------
    p_updates = sum(1 for r in rows if r["publish_date"] and "." in r["publish_date"])
    print(f"[日期] 点号式归一化 {p_updates} 条：2026.02.06 → 2026-02-06")

    # ---------- 写库 ----------
    conn = pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=cfg["database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            for new_t, rid in updates:
                cur.execute("UPDATE projects SET project_type=%s WHERE id=%s", (new_t, rid))
            for old, new in district_map.items():
                cur.execute("UPDATE projects SET district=%s WHERE district=%s", (new, old))
            cur.execute(
                "UPDATE projects SET publish_date=REPLACE(publish_date,'.','-') "
                "WHERE publish_date LIKE '%.%'")
        conn.commit()
    finally:
        conn.close()

    # ---------- 重新读取核对 ----------
    conn = pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=cfg["database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT project_type, COUNT(*) c FROM projects GROUP BY project_type ORDER BY c DESC")
            after = dict((r["project_type"], r["c"]) for r in cur.fetchall())
    finally:
        conn.close()

    print("\n===== 归档后类型分布（应 ≤13 类）=====")
    for k, v in sorted(after.items(), key=lambda x: -x[1]):
        mark = "" if k in STANDARD_TYPES else "  <== 非规范!"
        print(f"  {v:3d} | {k}{mark}")

    # ---------- 未归档清单 ----------
    if unclassified:
        out_json = Path(__file__).resolve().parent.parent / "data" / "results" / "unclassified_types.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(unclassified, f, ensure_ascii=False, indent=1)
        print(f"[清单] 未归档 {len(unclassified)} 条 → {out_json}")
        if openpyxl:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "未归档类型"
            ws.append(list(unclassified[0].keys()))
            for u in unclassified:
                ws.append([u["id"], u["project_name"], u["原类型"], u["归档结果"], u["匹配依据"]])
            xlsx = out_json.with_suffix(".xlsx")
            wb.save(xlsx)
            print(f"[清单] Excel → {xlsx}")
    else:
        print("[清单] 无未归档记录")

    print("\n[NEXT] 重跑导出：python scripts/export_dashboard_db.py")


if __name__ == "__main__":
    main()
