"""
首页看板路由
-----------
概览卡片 + 烟台地图 + 趋势图 + 高优先级项目列表
"""
import json
from flask import Blueprint, render_template
from flask_login import login_required

from database.db_manager import (
    get_stats_this_week, get_district_stats,
    get_weekly_trend, query_projects,
)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    """首页看板"""
    # 概览统计
    stats = get_stats_this_week()

    # 区县分布（用于地图）
    district_stats = get_district_stats()

    # 近8周趋势
    weekly_trend = get_weekly_trend(weeks=8)

    # 本周高优先级项目（前10条）
    high_priority, _ = query_projects(
        priority_min=4,
        sort_by="priority",
        sort_desc=True,
        page=1,
        per_page=10,
    )

    return render_template(
        "dashboard.html",
        stats=stats,
        district_stats=json.dumps(district_stats, ensure_ascii=False),
        weekly_trend=json.dumps(weekly_trend, ensure_ascii=False),
        high_priority=high_priority,
    )
