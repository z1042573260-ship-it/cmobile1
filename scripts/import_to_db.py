"""
AI 分析结果 → 数据库导入脚本
---------------------------
读取 AI 管线输出的 JSON（如 dashboard_test.json），导入 projects 表。

用法：
  python scripts/import_to_db.py <JSON文件>
  python scripts/import_to_db.py data/dashboard_test.json
  python scripts/import_to_db.py data/dashboard_data.json --replace  # 替换同名项目
"""
import json
import sys
import os
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.models import db, Project
from database.db_manager import init_db
from flask import Flask


def create_app() -> Flask:
    """最小 Flask 应用，只用于数据库连接"""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "import-script"
    from config.settings import DATABASE_URL
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    init_db(app)
    return app


def import_json_to_db(json_path: str, replace: bool = False):
    """将 AI 分析 JSON 导入 projects 表"""
    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    app = create_app()
    new_count = 0
    skip_count = 0
    replace_count = 0

    with app.app_context():
        for rec in records:
            name = rec.get("project_name", "未知项目")

            # 去重检查（按 project_name）
            existing = Project.query.filter_by(project_name=name).first()
            if existing:
                if replace:
                    # 替换模式：更新已有记录
                    _update_project(existing, rec)
                    replace_count += 1
                    print(f"  [~] 更新: {name[:40]}")
                else:
                    skip_count += 1
                    print(f"  [skip]  跳过(重复): {name[:40]}")
                continue

            # 新建
            project = Project(
                project_name=name,
                project_type=rec.get("project_type"),
                district=rec.get("district"),
                location=rec.get("location"),
                scale=rec.get("scale"),
                investment=rec.get("investment"),
                content=rec.get("content", ""),                    # 原文（不走AI，爬虫直存）
                developer=rec.get("developer"),
                contact_person=rec.get("contact_person", ""),
                contact_phone=rec.get("contact_phone", ""),
                publish_date=rec.get("_publish_date", rec.get("publish_date", "")),
                deadline=rec.get("deadline", ""),
                start_date=rec.get("start_date", ""),
                end_date=rec.get("end_date", ""),
                need_base_station=rec.get("need_base_station"),
                base_station_type=rec.get("base_station_type"),
                coverage_area=rec.get("coverage_area"),
                ai_reason=rec.get("ai_reason"),
                priority=rec.get("priority", 3),
                score=rec.get("score", 0),
                warning_level=rec.get("warning_level"),
                is_valuable=rec.get("is_valuable", False),
                telecom_needs=json.dumps(rec.get("telecom_needs", []), ensure_ascii=False),
                ai_summary=rec.get("ai_summary"),
                source_name=rec.get("_source_name", ""),
                source_url=rec.get("_source_url", ""),
                status=rec.get("project_stage", "新发现"),          # AI 的 project_stage → DB 的 status
            )
            db.session.add(project)
            new_count += 1
            print(f"  [+] 新增: {name[:40]}")

        db.session.commit()

    print(f"\n[Done] 导入完成: 新增 {new_count} | 更新 {replace_count} | 跳过 {skip_count} | 共 {len(records)} 条")
    return new_count, replace_count, skip_count


def _update_project(project: Project, rec: dict):
    """更新已有项目（替换模式）"""
    for field, key in [
        ("project_type", "project_type"),
        ("district", "district"),
        ("location", "location"),
        ("scale", "scale"),
        ("investment", "investment"),
        ("developer", "developer"),
        ("contact_person", "contact_person"),
        ("contact_phone", "contact_phone"),
        ("publish_date", "_publish_date"),
        ("deadline", "deadline"),
        ("start_date", "start_date"),
        ("end_date", "end_date"),
        ("need_base_station", "need_base_station"),
        ("base_station_type", "base_station_type"),
        ("coverage_area", "coverage_area"),
        ("ai_reason", "ai_reason"),
        ("priority", "priority"),
        ("score", "score"),
        ("warning_level", "warning_level"),
        ("is_valuable", "is_valuable"),
        ("ai_summary", "ai_summary"),
        ("source_name", "_source_name"),
        ("source_url", "_source_url"),
        ("status", "project_stage"),
    ]:
        val = rec.get(key)
        if val is not None:
            setattr(project, field, val)

    # telecom_needs 特殊处理（存 JSON 字符串）
    if "telecom_needs" in rec:
        project.telecom_needs = json.dumps(rec["telecom_needs"], ensure_ascii=False)

    # content
    if "content" in rec:
        project.content = rec["content"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/import_to_db.py <JSON文件> [--replace]")
        print("示例: python scripts/import_to_db.py data/dashboard_test.json")
        sys.exit(1)

    json_path = sys.argv[1]
    replace = "--replace" in sys.argv

    if not os.path.exists(json_path):
        print(f"❌ 文件不存在: {json_path}")
        sys.exit(1)

    import_json_to_db(json_path, replace=replace)
