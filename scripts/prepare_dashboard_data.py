"""
AI分析结果 → 大屏仪表盘数据准备
--------------------------------
读取 AI 统一情报分析 JSON，计算各项统计，
输出大屏可直接读取的 dashboard_data.json。

用法：
  python scripts/prepare_dashboard_data.py data/unified_intelligence.json
  python scripts/prepare_dashboard_data.py data/unified_intelligence.json -o frontend/data/dashboard_data.json
  python scripts/prepare_dashboard_data.py --mock 22   # 从 for_ai.json 生成22条模拟数据
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 烟台13区县名称映射（用于数据匹配）
YANTAI_DISTRICTS = [
    "芝罘区", "福山区", "牟平区", "莱山区", "蓬莱区",
    "龙口市", "莱阳市", "莱州市", "招远市", "栖霞市", "海阳市",
    "开发区", "高新区",
]

# 各区县在 GeoJSON 中的大致中心坐标 [lng, lat]
DISTRICT_COORDS = {
    "芝罘区": [121.38, 37.53],
    "福山区": [121.25, 37.49],
    "牟平区": [121.60, 37.38],
    "莱山区": [121.44, 37.50],
    "蓬莱区": [120.75, 37.80],
    "龙口市": [120.51, 37.64],
    "莱阳市": [120.71, 36.97],
    "莱州市": [119.94, 37.18],
    "招远市": [120.40, 37.35],
    "栖霞市": [120.83, 37.30],
    "海阳市": [121.17, 36.78],
    "开发区": [121.22, 37.55],
    "高新区": [121.48, 37.47],
}

# —— 模拟数据使用的项目类型/阶段/通信需求 ——
MOCK_TYPES = ["住宅", "厂房", "学校", "商业综合体", "道路桥梁", "医院", "办公楼", "产业园区", "市政管网", "公园绿化"]
MOCK_STAGES = ["规划立项", "招标阶段", "施工阶段", "已竣工完工"]
MOCK_TELECOM = ["信号覆盖", "宽带专线", "物联网", "云服务", "固话/视频会议", "数据中心"]


def compute_centroid(coordinates):
    """从 GeoJSON polygon/multipolygon 计算中心点"""
    if not coordinates:
        return [0, 0]
    # 展平坐标
    flat = coordinates
    while isinstance(flat[0][0], (list, tuple)):
        flat = flat[0]
    lngs = [p[0] for p in flat]
    lats = [p[1] for p in flat]
    return [sum(lngs) / len(lngs), sum(lats) / len(lats)]


def compute_geo_centroids(geo_path: str) -> dict:
    """从 GeoJSON 文件计算每个区县的中心坐标"""
    with open(geo_path, "r", encoding="utf-8") as f:
        geo = json.load(f)

    centroids = {}
    for feat in geo["features"]:
        name = feat["properties"]["name"]
        coords = feat["geometry"]["coordinates"]
        if feat["geometry"]["type"] == "Polygon":
            centroids[name] = compute_centroid(coords)
        elif feat["geometry"]["type"] == "MultiPolygon":
            # 取第一个 polygon
            centroids[name] = compute_centroid(coords[0])
    return centroids


def prepare_dashboard_data(results: list[dict], geo_json_path: str = None) -> dict:
    """将 AI 分析结果转换为大屏数据格式"""
    if not results:
        return {}

    # 计算 GeoJSON 中心坐标（若可用）
    centroids = {}
    if geo_json_path and Path(geo_json_path).exists():
        centroids = compute_geo_centroids(geo_json_path)

    # ---- 基础统计 ----
    total = len(results)
    red_warning = sum(1 for r in results if "红色" in str(r.get("warning_level", "")))
    yellow_warning = sum(1 for r in results if "黄色" in str(r.get("warning_level", "")))
    valuable = sum(1 for r in results if r.get("is_valuable"))

    # 覆盖区县
    district_set = set()
    for r in results:
        d = r.get("district", "")
        if d and d != "待核实":
            district_set.add(d)
    district_count = len(district_set)

    # ---- 各区县项目数量排名 ----
    district_counts = {}
    for r in results:
        d = r.get("district", "未知")
        if d == "待核实":
            d = "未知"
        district_counts[d] = district_counts.get(d, 0) + 1
    district_ranking = sorted(
        [{"name": k, "value": v} for k, v in district_counts.items()],
        key=lambda x: x["value"], reverse=True
    )

    # ---- 预警等级分布 ----
    warning_dist = {"红色预警": red_warning, "黄色预警": yellow_warning, "无预警": total - red_warning - yellow_warning}
    warning_pie = [{"name": k, "value": v} for k, v in warning_dist.items() if v > 0]

    # ---- 项目类型分布 ----
    type_counts = {}
    for r in results:
        t = r.get("project_type", "其他")
        if not t or t == "待核实":
            t = "其他"
        type_counts[t] = type_counts.get(t, 0) + 1
    type_pie = sorted(
        [{"name": k, "value": v} for k, v in type_counts.items()],
        key=lambda x: x["value"], reverse=True
    )

    # ---- 项目阶段分布 ----
    stage_counts = {}
    for r in results:
        s = r.get("project_stage", "待核实")
        if not s or s == "待核实":
            s = "其他"
        stage_counts[s] = stage_counts.get(s, 0) + 1
    stage_pie = [{"name": k, "value": v} for k, v in stage_counts.items()]

    # ---- 时间趋势（按发布日期） ----
    date_counts = {}
    red_date_counts = {}
    yellow_date_counts = {}
    for r in results:
        d = r.get("_publish_date", "") or r.get("publish_date", "")
        if d:
            d = d[:7]  # YYYY-MM
            date_counts[d] = date_counts.get(d, 0) + 1
            warning = str(r.get("warning_level", ""))
            if "红色" in warning:
                red_date_counts[d] = red_date_counts.get(d, 0) + 1
            elif "黄色" in warning:
                yellow_date_counts[d] = yellow_date_counts.get(d, 0) + 1
    timeline = sorted(
        [{"date": k, "value": v} for k, v in date_counts.items()],
        key=lambda x: x["date"]
    )
    red_timeline = sorted(
        [{"date": k, "value": v} for k, v in red_date_counts.items()],
        key=lambda x: x["date"]
    )
    yellow_timeline = sorted(
        [{"date": k, "value": v} for k, v in yellow_date_counts.items()],
        key=lambda x: x["date"]
    )

    # ---- 地图散点（含坐标） ----
    map_points = []
    for r in results:
        district = r.get("district", "")
        warning = r.get("warning_level", "")
        if "红色" in str(warning):
            category = "red"
        elif "黄色" in str(warning):
            category = "yellow"
        else:
            continue  # 无预警不在地图上显示

        # 获取坐标：优先数据库真实经纬度（projects.lng/lat），缺失回退区县中心
        coord = None
        rlng, rlat = r.get("lng"), r.get("lat")
        if rlng is not None and rlat is not None:
            try:
                coord = [float(rlng), float(rlat)]
            except (TypeError, ValueError):
                coord = None
        if not coord:
            coord = centroids.get(district) or DISTRICT_COORDS.get(district)
        if not coord:
            # 尝试模糊匹配
            for dname, c in {**centroids, **DISTRICT_COORDS}.items():
                if district in dname or dname in district:
                    coord = c
                    break
        if not coord:
            coord = [121.39, 37.52]  # 默认烟台中心

        map_points.append({
            "name": r.get("project_name", "")[:20],
            "value": coord + [r.get("priority", 1)],
            "district": district,
            "category": category,
            "project_type": r.get("project_type", ""),
            "stage": r.get("project_stage", ""),
            "warning": warning,
        })

    # ---- 项目列表（表格用） ----
    project_list = []
    for r in sorted(results, key=lambda x: x.get("priority", 0), reverse=True):
        project_list.append({
            "name": r.get("project_name", ""),
            "district": r.get("district", ""),
            "type": r.get("project_type", ""),
            "stage": r.get("project_stage", ""),
            "priority": r.get("priority", 0),
            "warning": r.get("warning_level", ""),
            "investment": r.get("investment", ""),
            "scale": r.get("scale", ""),
            "date": r.get("_publish_date", ""),
            "url": r.get("_source_url", ""),
            "ai_summary": r.get("ai_summary", ""),
        })

    return {
        "meta": {
            "updated_at": "",
            "total_projects": total,
            "source": "AI统一情报分析管线",
        },
        "summary": {
            "total": total,
            "red_warning": red_warning,
            "yellow_warning": yellow_warning,
            "valuable": valuable,
            "district_count": district_count,
        },
        "warning_pie": warning_pie,
        "type_pie": type_pie,
        "stage_pie": stage_pie,
        "district_ranking": district_ranking,
        "timeline": timeline,
        "red_timeline": red_timeline,
        "yellow_timeline": yellow_timeline,
        "map_points": map_points,
        "project_list": project_list,
    }


def generate_mock_data(count: int) -> list[dict]:
    """从 for_ai.json 中取前 count 条，模拟 AI 分析字段"""
    for_ai_path = Path(__file__).resolve().parent.parent / "data" / "for_ai.json"
    if not for_ai_path.exists():
        print(f"[ERROR] for_ai.json 不存在: {for_ai_path}")
        return []

    with open(for_ai_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    random.shuffle(raw)
    raw = raw[:count]

    mock_results = []
    for r in raw:
        district = r.get("district_extracted", "") or random.choice(YANTAI_DISTRICTS[:11])
        score = r.get("relevance_score", 0)

        # 根据评分模拟 AI 字段
        if score >= 6:
            warning = "红色预警"
            priority = random.randint(4, 5)
            need_station = "高"
            is_val = True
            stage_weights = ["招标阶段"] * 3 + ["施工阶段"] * 4 + ["规划立项"] * 3
        elif score >= 4:
            warning = "黄色预警"
            priority = 3
            need_station = random.choice(["中", "高"])
            is_val = random.choice([True, True, False])
            stage_weights = ["招标阶段"] * 2 + ["施工阶段"] * 3 + ["规划立项"] * 3 + ["已竣工完工"] * 2
        elif score >= 2:
            warning = random.choice(["黄色预警", "无预警"])
            priority = random.randint(2, 3)
            need_station = random.choice(["低", "中"])
            is_val = random.choice([True, False, False])
            stage_weights = ["已竣工完工"] * 4 + ["施工阶段"] * 3 + ["招标阶段"] * 2 + ["规划立项"]
        else:
            warning = "无预警"
            priority = random.randint(1, 2)
            need_station = random.choice(["无", "低"])
            is_val = False
            stage_weights = ["已竣工完工"] * 6 + ["施工阶段"] * 2 + ["招标阶段"] + ["规划立项"]

        project_type = random.choice(MOCK_TYPES)
        project_stage = random.choice(stage_weights)
        telecom = random.sample(MOCK_TELECOM, random.randint(1, 4))

        base_station_map = {"高": "宏站+室分", "中": "室分", "低": "无需", "无": "无需"}
        station_type = base_station_map[need_station]

        mock_results.append({
            "project_name": r.get("title", ""),
            "project_type": project_type,
            "district": district,
            "location": "待核实",
            "scale": r.get("scale_extracted", "待核实") or "待核实",
            "investment": r.get("investment_extracted", "待核实") or "待核实",
            "developer": "待核实",
            "project_stage": project_stage,
            "need_base_station": need_station,
            "base_station_type": station_type,
            "priority": priority,
            "warning_level": warning,
            "is_valuable": is_val,
            "score": priority,
            "telecom_needs": telecom,
            "ai_summary": f"{district}{project_type}项目，{project_stage}，通信需求{need_station}",
            "_source_url": r.get("source_url", ""),
            "_publish_date": r.get("publish_date", ""),
        })

    return mock_results


def main():
    parser = argparse.ArgumentParser(description="AI分析结果 → 大屏数据准备")
    parser.add_argument("input_json", nargs="?", help="AI 分析结果 JSON")
    parser.add_argument("--output", "-o", default=None, help="输出路径（默认: frontend/data/dashboard_data.json）")
    parser.add_argument("--geo", default=None, help="GeoJSON 路径（默认: frontend/js/yantai.json）")
    parser.add_argument("--mock", type=int, default=0, help="生成 N 条模拟数据（从 for_ai.json 取）")
    args = parser.parse_args()

    # 默认路径
    project_root = Path(__file__).resolve().parent.parent
    default_output = project_root / "frontend" / "data" / "dashboard_data.json"
    default_geo = project_root / "frontend" / "js" / "yantai.json"

    output_path = args.output or str(default_output)
    geo_path = args.geo or str(default_geo)

    # 加载数据
    if args.mock > 0:
        print(f"[MOCK] 生成 {args.mock} 条模拟数据...")
        results = generate_mock_data(args.mock)
        print(f"       实际生成: {len(results)} 条")
    elif args.input_json:
        with open(args.input_json, "r", encoding="utf-8") as f:
            results = json.load(f)
        # 兼容 {"results": [...]} 格式
        if isinstance(results, dict):
            results = results.get("results", [])
        print(f"[LOAD] 加载 {len(results)} 条 AI 分析结果")
    else:
        print("请指定输入 JSON 或 --mock N")
        sys.exit(1)

    if not results:
        print("[EMPTY] 无数据")
        sys.exit(1)

    # 准备大屏数据
    dashboard = prepare_dashboard_data(results, geo_path)

    # 写入时间戳
    from datetime import datetime
    dashboard["meta"]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 保存
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 大屏数据已生成: {output_path}")
    print(f"   总项目: {dashboard['summary']['total']}")
    print(f"   红色预警: {dashboard['summary']['red_warning']}")
    print(f"   黄色预警: {dashboard['summary']['yellow_warning']}")
    print(f"   覆盖区县: {dashboard['summary']['district_count']}")
    print(f"   地图散点: {len(dashboard['map_points'])}")


if __name__ == "__main__":
    main()
