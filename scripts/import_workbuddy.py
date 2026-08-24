"""
workbuddy.json（AI 情报分析输出）→ MySQL 导入
--------------------------------------------
从 data/results/workbuddy.json 读取 AI 分析结果，
按 project_name upsert 写入 yantai_projects.projects：
  - 库里没有该 project_name → 插入新记录
  - 已存在 → 更新 AI 分析字段（仅更新 workbuddy 有值的字段，空值不覆盖已有）
  - workbuddy 内部同名重复 → 按文件顺序后者覆盖前者
telecom_needs（list）→ json.dumps 序列化（前端 JSON.parse 读取）
source_name 用 workbuddy 里的真实来源，不硬编码

用法：
  python scripts/import_workbuddy.py
  python scripts/import_workbuddy.py -i data/results/workbuddy.json   # 指定输入
导入后重跑导出保持大屏最新：
  python scripts/export_dashboard_db.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pymysql
except ImportError:
    print("[ERROR] 需要 pymysql：pip install pymysql")
    sys.exit(1)

try:
    from config.settings import DATABASE_URL
except Exception:
    DATABASE_URL = "mysql+pymysql://root:1234@localhost:3306/yantai_projects"

# workbuddy 字段 → 数据库列（_index/_title 为 AI 输出辅助字段，不入库）
FIELD_MAP = [
    "project_name", "project_type", "district", "location", "lng", "lat",
    "scale", "investment", "content", "developer", "contact_person",
    "contact_phone", "deadline", "start_date", "end_date",
    "need_base_station", "base_station_type", "coverage_area", "ai_reason",
    "priority", "score", "warning_level", "is_valuable", "telecom_needs",
    "ai_summary", "source_name", "source_url", "publish_date", "status",
]


def parse_db_url(url: str) -> dict:
    """mysql+pymysql://user:pass@host:port/db?query → dict（支持 ssl_ca）"""
    core = url.split("://", 1)[1]
    cred, rest = core.split("@", 1)
    user, pwd = cred.split(":", 1)
    host_port, db = rest.split("/", 1)
    host, port = host_port.split(":", 1) if ":" in host_port else (host_port, "3306")
    cfg = {"user": user, "password": pwd, "host": host, "port": int(port), "database": db, "ssl": None}
    if "?" in db:
        db, query = db.split("?", 1)
        cfg["database"] = db
        for kv in query.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                if k == "ssl_ca":
                    cfg["ssl"] = {"ca": v}
    return cfg


def normalize(it: dict) -> dict:
    """workbuddy 单条 → 可写库的列值 dict（None/'' 标记为空，upsert 时不覆盖已有值）"""
    out = {}
    for col in FIELD_MAP:
        v = it.get(col)
        if col == "telecom_needs" and isinstance(v, (list, dict)):
            # AI 可能输出数组或对象（dict）——统一 JSON 序列化，dict 值提取为列表
            if isinstance(v, dict):
                v = list(v.values())
            v = json.dumps(v, ensure_ascii=False)
        elif col == "is_valuable":
            v = 1 if v else 0
        elif col in ("lng", "lat") and v is not None:
            try:
                fv = float(v)
                # NaN 无法写入 MySQL → 置空
                v = None if fv != fv else fv
            except (ValueError, TypeError):
                v = None
        elif col == "ai_reason" and isinstance(v, dict):
            # AI 可能把 ai_reason 输出成对象（project_nature/base_station_assessment/
            # business_opportunity_analysis）→ 转三段式文本，与 4.7 格式一致
            parts = []
            for key, label in [("project_nature", "项目本质"),
                               ("base_station_assessment", "基站评估"),
                               ("business_opportunity_analysis", "商机判断")]:
                if v.get(key):
                    parts.append(f"【{label}】{v[key]}")
            v = "\n".join(parts) if parts else json.dumps(v, ensure_ascii=False)
        elif isinstance(v, (dict, list)):
            # AI 可能把文本字段输出成结构化对象 → 统一 JSON 序列化
            v = json.dumps(v, ensure_ascii=False)
        if v == "":
            v = None
        out[col] = v
    return out


def fill_missing_coords(results: list[dict]) -> tuple:
    """严格按 AI 管线经纬度流程：缺失/非法坐标 → 高德地理编码补全（GCJ-02）

    规则（与 processor/amap_geocode.py + amap_decompress.py 一致）：
      1. AI 已有合法 lng/lat（±180/±90，非 NaN）→ 保留
      2. 缺失/非法 → 用 location → 项目名 两级调高德编码：
         - 命中 + level 非粗粒度（省/市/区县等中心点）+ region_ok（区县匹配）→ 补坐标
         - 精度闸门：高德退回行政中心（COARSE_LEVEL）→ 拒绝，不补
         - 查不到 / 跨区 → 不补
      3. 仍缺坐标的记录不入库（大屏需坐标定位，缺则丢定位信息）

    Returns:
        (filled, still_missing) — 补全数 / 仍缺数
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from processor.amap_geocode import geocode, region_ok, clean_addr
        from processor.amap_decompress import COARSE_LEVEL
    except Exception as e:
        print(f"[WARN] 高德模块加载失败，跳过坐标补全: {e}")
        return 0, sum(1 for r in results if r.get("lng") is None or r.get("lat") is None)

    filled = still_missing = 0
    for idx, it in enumerate(results):
        # 已有合法坐标 → 保留
        try:
            lng, lat = float(it.get("lng")), float(it.get("lat"))
            if lng == lng and lat == lat and -180 <= lng <= 180 and -90 <= lat <= 90:
                it["lng"] = round(lng, 6)
                it["lat"] = round(lat, 6)
                continue
        except (TypeError, ValueError):
            pass
        it.pop("lng", None)
        it.pop("lat", None)

        district = it.get("district") or ""
        addr = it.get("location") or ""
        name = (it.get("project_name") or "").strip()
        # 多级地址变体尝试（管线规范：高德查不到继续补全，不直接放弃）
        # ① location + 区县
        g = geocode(clean_addr(addr), district) if addr.strip() else None
        time.sleep(0.6)
        # ② 项目名 + 区县
        if not g and name and name != "待核实":
            g = geocode(clean_addr(name), district)
            time.sleep(0.6)
        # ③ 区县 + 项目名核心词（去掉"项目/工程/建设"等修饰）
        if not g and name and name != "待核实":
            core = re.sub(r'(项目|工程|建设|招标|公告|设计|施工|总承包|(一期|二期|三期|四期))', '', name)
            core = core.strip()[:30]
            if core and core != name:
                g = geocode(clean_addr(core), district)
                time.sleep(0.6)
        # ④ 仅区县 + 地址首段（location 取前 20 字）
        if not g and addr:
            short_addr = addr[:20]
            if short_addr != addr:
                g = geocode(clean_addr(short_addr), district)
                time.sleep(0.6)
        # ⑤ 高德 POI 搜索（项目名/园区/企业检索，命中率高于 geocode，免费同 key）
        if not g and name and name != "待核实":
            from processor.amap_geocode import place_search
            p = place_search(name, district)
            time.sleep(0.6)
            if p:
                # POI 区县校验（adname 与记录 district 匹配，功能区兼容走 region_ok 兜底）
                adname_ok = (district in ("", "烟台市") or p.get("adname") == district
                             or region_ok(district, {"district": p.get("adname")}))
                if adname_ok:
                    g = p
        # ⑥ 百度搜索（免费爬取，无 key）：查项目地址 → 高德重编码
        if not g and name and name != "待核实":
            try:
                from processor.web_search import search_address
                addr_found = search_address(name, district)
                if addr_found:
                    g = geocode(clean_addr(addr_found), district)
                    time.sleep(0.6)
                    if not g:
                        # 地址片段可能过长，用前 20 字再试
                        g = geocode(clean_addr(addr_found[:20]), district)
                        time.sleep(0.6)
            except Exception as e:
                print(f"[WARN] 百度搜索补坐标失败: {e}")
        # 精度闸门 + 区县校验
        if g and g.get("level") not in COARSE_LEVEL and region_ok(district, g):
            it["lng"], it["lat"] = g["lng"], g["lat"]
            filled += 1
        else:
            # ⑦ 虚拟定位兜底（用户要求：查不到也必须有定位，保证下钻可见）：
            # 区县中心坐标 + 微偏移（同区县多个项目错开，避免图钉完全重叠折叠）
            try:
                from processor.amap_decompress import _district_center
                center = _district_center(district)
                if center:
                    # 偏移从 0.004 起（约 400m），避开区县中心原值——防止与真实中心坐标项目
                    # 同 0.0001° 组折叠隐藏（实测 736 与"四好农村路"同点折叠）
                    offset_lng = ((idx + 1) * 0.004) % 0.03
                    offset_lat = ((idx * 7 + 3) % 5) * 0.003
                    it["lng"] = round(center[0] + offset_lng, 6)
                    it["lat"] = round(center[1] + offset_lat, 6)
                    it["geo_source"] = "虚拟定位(区县中心)"
                    filled += 1
                    continue
            except Exception:
                pass
            still_missing += 1
    return filled, still_missing


def upsert_rows(rows: list[dict], db_url: str = None) -> tuple:
    """
    将 AI 分析结果按 project_name upsert 写入 projects 表。
    - 库里没有 project_name → INSERT 新记录
    - 已存在 → 仅更新有值的列（NULL 不覆盖已有），更新时间戳
    - 不影响其他表，不删除任何数据

    供自动化管线（scheduler.py）直接调用，也供 CLI 使用。

    Returns:
        (ins, upd, skip) — 新增 / 更新 / 跳过（无 project_name）
    """
    cfg = parse_db_url(db_url or DATABASE_URL)
    conn = pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=cfg["database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, ssl=cfg.get("ssl"),
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ins = upd = skip = 0
    try:
        with conn.cursor() as cur:
            for it in rows:
                vals = normalize(it)
                if not (vals.get("project_name") or "").strip():
                    skip += 1
                    continue
                # 无预警不入库（硬约束）：大屏/报告只展示红黄预警，
                # 无预警记录由 AI 判断得出，不写入 projects 表（不依赖坐标间接拦截）
                if (it.get("warning_level") or "") == "无预警":
                    skip += 1
                    continue
                # 经纬度是关键定位字段：仅"新项目且缺坐标"不入库（保持待重试，防大屏无定位点）；
                # 已有项目（upsert 更新）缺坐标时保留 DB 旧坐标继续更新其他字段
                # （ON DUPLICATE KEY UPDATE 空值不覆盖已有，坐标自然保留）
                if vals.get("lng") is None or vals.get("lat") is None:
                    cur.execute("SELECT id FROM projects WHERE project_name = %s",
                                (vals["project_name"],))
                    if cur.fetchone() is None:
                        skip += 1
                        print(f"[SKIP] 新项目缺经纬度，暂不入库: {vals.get('project_name', '')[:40]}")
                        continue
                cols = list(FIELD_MAP)
                colsql = ", ".join(cols)
                placeholders = ", ".join(["%s"] * len(cols))
                # 覆盖 = 仅更新有值的列（NULL 不覆盖已有），更新时间戳
                updates = ", ".join(
                    f"{c} = IF(VALUES({c}) IS NULL, {c}, VALUES({c}))" for c in cols
                ) + ", updated_at = %s"
                sql = (
                    f"INSERT INTO projects ({colsql}, created_at, updated_at) "
                    f"VALUES ({placeholders}, %s, %s) "
                    f"ON DUPLICATE KEY UPDATE {updates}"
                )
                params = [vals[c] for c in cols] + [now, now, now]
                cur.execute(sql, params)
                if cur.rowcount == 1:
                    ins += 1
                elif cur.rowcount == 2:
                    upd += 1
        conn.commit()
    finally:
        conn.close()

    print(f"[OK] 导入完成：新增 {ins} 条 / 更新 {upd} 条 / 跳过（无项目名）{skip} 条")
    return ins, upd, skip


def main():
    parser = argparse.ArgumentParser(description="workbuddy.json → MySQL 导入")
    parser.add_argument("-i", "--input", default=str(
        Path(__file__).resolve().parent.parent / "data" / "results" / "workbuddy.json"))
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list) or not rows:
        print(f"[ERROR] {args.input} 不是有效数组")
        sys.exit(1)

    upsert_rows(rows)
    print(f"[NEXT] 重跑导出使大屏数据最新：python scripts/export_dashboard_db.py")


if __name__ == "__main__":
    main()
