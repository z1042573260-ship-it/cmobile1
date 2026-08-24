"""
项目列表路由
-----------
搜索、筛选、排序、详情、导出、状态更新
"""
import datetime
import io
from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required
import pandas as pd

from config.settings import YANTAI_DISTRICTS
from database.db_manager import (
    query_projects, get_project_by_id, update_project_status,
)

projects_bp = Blueprint("projects", __name__, url_prefix="/projects")


@projects_bp.route("/")
@login_required
def list_projects():
    """项目列表页"""
    # 筛选参数
    district = request.args.get("district", "")
    project_type = request.args.get("project_type", "")
    need_base_station = request.args.get("need_base_station", "")
    priority_min = request.args.get("priority_min", type=int)
    status = request.args.get("status", "")
    _notified = request.args.get("notified", "")
    notified = int(_notified) if _notified.isdigit() else None
    keyword = request.args.get("keyword", "")
    sort_by = request.args.get("sort_by", "created_at")
    sort_desc = request.args.get("sort_desc", "1") == "1"
    page = request.args.get("page", 1, type=int)

    # notified 参数转换
    notified_bool = None
    if notified is not None:
        notified_bool = bool(notified)

    # 日期筛选
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    projects, total = query_projects(
        district=district or None,
        project_type=project_type or None,
        need_base_station=need_base_station or None,
        priority_min=priority_min,
        status=status or None,
        notified=notified_bool,
        keyword=keyword or None,
        date_from=date_from or None,
        date_to=date_to or None,
        sort_by=sort_by,
        sort_desc=sort_desc,
        page=page,
        per_page=20,
    )

    # 总页数
    total_pages = (total + 19) // 20

    # 所有可能的工程类型（用于筛选下拉）
    project_types = [
        "住宅小区", "商业综合体", "写字楼", "学校", "医院",
        "工业园区", "道路", "桥梁", "隧道", "市政设施",
        "酒店", "商场", "景区", "其他",
    ]

    return render_template(
        "project_list.html",
        projects=projects,
        total=total,
        page=page,
        total_pages=total_pages,
        districts=YANTAI_DISTRICTS,
        project_types=project_types,
        current_filters={
            "district": district,
            "project_type": project_type,
            "need_base_station": need_base_station,
            "priority_min": priority_min,
            "status": status,
            "notified": notified,
            "keyword": keyword,
            "sort_by": sort_by,
            "sort_desc": sort_desc,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@projects_bp.route("/<int:project_id>")
@login_required
def detail(project_id: int):
    """项目详情页"""
    project = get_project_by_id(project_id)
    if not project:
        return "项目不存在", 404
    return render_template("project_detail.html", project=project)


@projects_bp.route("/<int:project_id>/update-status", methods=["POST"])
@login_required
def update_status(project_id: int):
    """更新项目跟进状态（AJAX）"""
    data = request.get_json()
    status = data.get("status", "")
    notes = data.get("notes", "")

    valid_statuses = ["新发现", "跟进中", "已签约", "已丢失"]
    if status not in valid_statuses:
        return jsonify({"success": False, "message": "无效的状态"}), 400

    update_project_status(project_id, status, notes)
    return jsonify({"success": True})


@projects_bp.route("/export")
@login_required
def export_excel():
    """导出为 Excel 文件"""
    # 获取所有项目（筛选条件同查询参数）
    district = request.args.get("district", "")
    need_base_station = request.args.get("need_base_station", "")
    priority_min = request.args.get("priority_min", type=int)
    keyword = request.args.get("keyword", "")
    status = request.args.get("status", "")

    projects, _ = query_projects(
        district=district or None,
        need_base_station=need_base_station or None,
        priority_min=priority_min,
        keyword=keyword or None,
        status=status or None,
        sort_by="created_at",
        sort_desc=True,
        page=1,
        per_page=10000,  # 导出全部
    )

    # 转为 DataFrame
    data = []
    for p in projects:
        data.append({
            "项目名称": p.project_name,
            "工程类型": p.project_type,
            "所属区县": p.district,
            "详细地址": p.location,
            "建设规模": p.scale,
            "投资金额": p.investment,
            "建设单位": p.developer,
            "联系人": p.contact_person,
            "联系电话": p.contact_phone,
            "发布日期": p.publish_date,
            "截止日期": p.deadline,
            "AI-基站需求": p.need_base_station,
            "AI-判断依据": p.ai_reason,
            "AI-优先级": p.priority,
            "AI-摘要": p.ai_summary,
            "跟进状态": p.status,
            "已邮件通知": "是" if p.notified else "否",
            "数据来源": p.source_name,
            "来源链接": p.source_url,
            "发现时间": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
        })

    df = pd.DataFrame(data)

    # 写入内存
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="烟台工程情报", index=False)

    output.seek(0)

    today_str = datetime.date.today().strftime("%Y%m%d")
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"烟台基站工程情报_{today_str}.xlsx",
    )
