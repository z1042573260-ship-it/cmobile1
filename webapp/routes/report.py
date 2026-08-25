"""
数据分析报告路由
---------------
/report → 报告页面
/api/report-data → 数据库驱动的报告数据 JSON
/api/report/send-email → 发送报告邮件
"""
import datetime
import os
from flask import Blueprint, jsonify, request, send_file, send_from_directory
from flask_login import login_required
from sqlalchemy import func

from database.models import db, Project

# status（如"施工阶段（施工许可证已核发）"）→ 5 类标准阶段，与 export_dashboard_db 同一实现
try:
    from scripts.export_dashboard_db import stage_of
except Exception:
    def stage_of(status):
        s = status or ""
        if any(k in s for k in ("竣工", "完工", "验收", "交付", "建成")): return "已竣工完工"
        if any(k in s for k in ("招标", "中标", "磋商", "资格预审", "开标")): return "招标阶段"
        if any(k in s for k in ("施工", "开工", "在建", "封顶", "主体")): return "施工阶段"
        if any(k in s for k in ("规划", "立项", "预审", "选址", "公示", "许可", "审批", "评估")): return "规划阶段"
        return "待核实"

report_bp = Blueprint("report", __name__)

# report.html 文件路径（abspath 归一化，否则 send_from_directory 前缀检查失败返回 404）
FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))


@report_bp.route("/report")
@login_required
def report_page():
    """数据分析报告页面"""
    report_path = os.path.join(FRONTEND_DIR, "report.html")
    return send_file(report_path)


@report_bp.route("/report2")
@login_required
def report2_page():
    """数据分析报告页面（副本，report2.html）"""
    report2_path = os.path.join(FRONTEND_DIR, "report2.html")
    return send_file(report2_path)


@report_bp.route("/data/<path:filename>")
def report_data_file(filename):
    """报告静态数据文件（report_data.json / dashboard_data.json）"""
    return send_from_directory(os.path.join(FRONTEND_DIR, "data"), filename)


@report_bp.route("/api/report-data")
@login_required
def report_data():
    """
    报告数据 API
    从数据库 Project 表聚合所有数据，输出为报告需要的 JSON 格式
    """
    # ---- 所有项目（与 report_data.json 统一口径：全部红/黄预警，不按基站需求过滤） ----
    all_projects = Project.query.filter(
        Project.warning_level.like("%红色%") | Project.warning_level.like("%黄色%")
    ).order_by(Project.priority.desc(), Project.created_at.desc()).all()

    # ---- 警告映射 ----
    def warning_label(need_bs, priority):
        """根据基站需求 + 优先级映射预警级别"""
        if need_bs == "高":
            return "红色预警"
        elif need_bs == "中":
            return "黄色预警"
        # 兜底（理论上不会到这里，因为查询已过滤）
        if priority and priority >= 4:
            return "红色预警"
        return "黄色预警"

    # ---- 项目列表 ----
    project_list = []
    for p in all_projects:
        project_list.append({
            "name": p.project_name or "",
            "district": p.district or "",
            "type": p.project_type or "未分类",
            "stage": stage_of(p.status),          # 5 类标准阶段（卡片徽章：施工阶段，不带括号长文本）
            "stage_detail": p.status or "",       # AI 完整阶段描述（详情弹窗用）
            "priority": p.priority or 3,
            "score": p.score or 0,
            "warning": p.warning_level or warning_label(p.need_base_station, p.priority),
            "investment": p.investment or "待核实",
            "scale": p.scale or "待核实",
            "date": p.publish_date or "",
            "url": p.source_url or "",
            "location": p.location or "",
            "content": p.content or "",
            "base_station_type": p.base_station_type or "",
            "coverage_area": p.coverage_area or "",
            "ai_reason": p.ai_reason or "",
            "ai_summary": p.ai_summary or "",
            "is_valuable": p.is_valuable if p.is_valuable is not None else False,
            "telecom_needs": p.telecom_needs or "",
            "processed_status": p.processed_status if p.processed_status is not None else 0,
            "processed_time": p.processed_time.strftime("%Y-%m-%d %H:%M") if p.processed_time else "",
        })

    # ---- 汇总统计 ----
    total = len(project_list)
    red_count = sum(1 for p in project_list if p["warning"] == "红色预警")
    yellow_count = sum(1 for p in project_list if p["warning"] == "黄色预警")

    # 覆盖区县数
    districts_set = set(p.district for p in all_projects if p.district)
    district_count = len(districts_set)

    summary = {
        "total": total,
        "red_warning": red_count,
        "yellow_warning": yellow_count,
        "district_count": district_count,
    }

    # ---- 区县排名 ----
    district_agg = (
        db.session.query(Project.district, func.count(Project.id))
        .filter(Project.need_base_station.in_(["高", "中"]))
        .filter(Project.district.isnot(None))
        .filter(Project.district != "")
        .group_by(Project.district)
        .order_by(func.count(Project.id).desc())
        .limit(10)
        .all()
    )
    district_ranking = [{"name": d[0], "value": d[1]} for d in district_agg]

    # ---- 月度趋势 ----
    # 按月聚合 publish_date（格式 YYYY-MM-DD 或 YYYY-MM）
    month_counts = {}
    for p in all_projects:
        if p.publish_date and len(p.publish_date) >= 7:
            month = p.publish_date[:7]  # "2026-07"
            month_counts[month] = month_counts.get(month, 0) + 1
        elif p.created_at:
            month = p.created_at.strftime("%Y-%m")
            month_counts[month] = month_counts.get(month, 0) + 1

    timeline = sorted(
        [{"date": m, "value": c} for m, c in month_counts.items()],
        key=lambda x: x["date"]
    )

    # ---- 预警分布饼图 ----
    warning_pie = []
    if red_count > 0:
        warning_pie.append({"name": "红色预警", "value": red_count})
    if yellow_count > 0:
        warning_pie.append({"name": "黄色预警", "value": yellow_count})

    # ---- 项目类型饼图 ----
    type_agg = (
        db.session.query(Project.project_type, func.count(Project.id))
        .filter(Project.need_base_station.in_(["高", "中"]))
        .filter(Project.project_type.isnot(None))
        .filter(Project.project_type != "")
        .group_by(Project.project_type)
        .order_by(func.count(Project.id).desc())
        .all()
    )
    type_pie = [{"name": t[0], "value": t[1]} for t in type_agg]

    # ---- 阶段分布饼图 ----
    stage_agg = (
        db.session.query(Project.status, func.count(Project.id))
        .filter(Project.need_base_station.in_(["高", "中"]))
        .filter(Project.status.isnot(None))
        .filter(Project.status != "")
        .group_by(Project.status)
        .all()
    )
    stage_pie = [{"name": s[0], "value": s[1]} for s in stage_agg]

    # ---- 更新时间 ----
    latest_project = (
        Project.query.order_by(Project.updated_at.desc()).first()
    )
    updated_at = (
        latest_project.updated_at.strftime("%Y-%m-%d %H:%M")
        if latest_project and latest_project.updated_at
        else datetime.date.today().strftime("%Y-%m-%d")
    )

    return jsonify({
        "meta": {
            "updated_at": updated_at,
            "total_projects": total,
            "source": "AI统一情报分析管线（数据库）",
        },
        "summary": summary,
        "district_ranking": district_ranking,
        "timeline": timeline,
        "warning_pie": warning_pie,
        "type_pie": type_pie,
        "stage_pie": stage_pie,
        "project_list": project_list,
    })


@report_bp.route("/api/report/send-email", methods=["POST"])
@login_required
def send_report_email():
    """
    发送报告邮件
    请求体 JSON: {"emails": ["xxx@qq.com", "yyy@qq.com"]}
    如果不传 emails，使用配置文件中的 EMAIL_RECIPIENTS
    """
    from notifier.email_sender import send_report_email as do_send

    to_emails = []
    report_file = "report.html"  # 附件模板：report.html / report2.html
    if request.is_json:
        to_emails = request.json.get("emails", [])
        report_file = request.json.get("report", "report.html")

    # 安全校验：只允许 frontend 下的报告模板
    import os
    from webapp.routes.report import FRONTEND_DIR
    if not report_file or ".." in report_file or "/" in report_file or "\\" in report_file:
        report_file = "report.html"
    if not os.path.exists(os.path.join(FRONTEND_DIR, report_file)):
        report_file = "report.html"

    # 如果没传收件人，用配置文件默认值
    if not to_emails:
        from config.settings import EMAIL_RECIPIENTS
        to_emails = [e.strip() for e in EMAIL_RECIPIENTS if e.strip()]

    if not to_emails:
        return jsonify({
            "success": False,
            "error": "未指定收件人。请在请求中传入 emails 参数，或在 config/settings.py 中配置 EMAIL_RECIPIENTS",
        }), 400

    success = do_send(to_emails, report_file)

    if success:
        return jsonify({
            "success": True,
            "message": f"邮件已发送至 {len(to_emails)} 位收件人",
            "recipients": to_emails,
        })
    else:
        return jsonify({
            "success": False,
            "error": "邮件发送失败，请检查邮件配置（授权码、收件人等）",
        }), 500
