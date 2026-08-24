"""
数据库操作封装
--------------
提供常用的增删改查操作，供爬虫调度器和看板调用。
"""
import datetime
from typing import Optional
from sqlalchemy import func, extract

from database.models import db, User, RawProject, Project, CrawlLog


# ============================
# 用户操作
# ============================
def create_user(username: str, password: str, display_name: str,
                email: str = None, role: str = "user") -> User:
    """创建新用户"""
    user = User(username=username, display_name=display_name,
                email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def get_user_by_username(username: str) -> Optional[User]:
    """按用户名查找"""
    return User.query.filter_by(username=username).first()


def get_all_users() -> list:
    """获取所有用户"""
    return User.query.all()


# ============================
# 原始项目操作
# ============================
def add_raw_project(title: str, source_name: str, content: str = None,
                    source_url: str = None, publish_date: str = None,
                    raw_html: str = None) -> RawProject:
    """添加一条原始项目记录"""
    raw = RawProject(
        title=title,
        content=content,
        source_url=source_url,
        source_name=source_name,
        publish_date=publish_date,
        raw_html=raw_html,
    )
    db.session.add(raw)
    db.session.commit()
    return raw


def get_unprocessed_raws(limit: int = 100) -> list:
    """获取未处理的原始记录"""
    return (RawProject.query
            .filter_by(processed=False, duplicate_of=None)
            .order_by(RawProject.crawl_time.desc())
            .limit(limit)
            .all())


def mark_as_processed(raw_id: int):
    """标记原始记录为已处理"""
    raw = RawProject.query.get(raw_id)
    if raw:
        raw.processed = True
        db.session.commit()


def mark_as_duplicate(raw_id: int, master_id: int):
    """标记原始记录为重复"""
    raw = RawProject.query.get(raw_id)
    if raw:
        raw.processed = True
        raw.duplicate_of = master_id
        db.session.commit()


def count_unprocessed() -> int:
    """统计未处理数量"""
    return RawProject.query.filter_by(processed=False, duplicate_of=None).count()


# ============================
# 正式项目操作
# ============================
def add_project(project_name: str, **kwargs) -> Project:
    """添加一条正式项目"""
    project = Project(project_name=project_name, **kwargs)
    db.session.add(project)
    db.session.commit()
    return project


def get_project_by_id(project_id: int) -> Optional[Project]:
    """按ID获取项目"""
    return Project.query.get(project_id)


def query_projects(
    district: str = None,
    project_type: str = None,
    need_base_station: str = None,
    priority_min: int = None,
    status: str = None,
    notified: bool = None,
    keyword: str = None,
    date_from: str = None,
    date_to: str = None,
    sort_by: str = "created_at",
    sort_desc: bool = True,
    page: int = 1,
    per_page: int = 20,
) -> tuple:
    """
    灵活查询项目列表
    返回: (项目列表, 总数)
    """
    q = Project.query

    # 筛选条件
    if district:
        q = q.filter(Project.district == district)
    if project_type:
        q = q.filter(Project.project_type == project_type)
    if need_base_station:
        q = q.filter(Project.need_base_station == need_base_station)
    if priority_min:
        q = q.filter(Project.priority >= priority_min)
    if status:
        q = q.filter(Project.status == status)
    if notified is not None:
        q = q.filter(Project.notified == notified)
    if keyword:
        q = q.filter(
            db.or_(
                Project.project_name.contains(keyword),
                Project.location.contains(keyword),
                Project.developer.contains(keyword),
                Project.ai_summary.contains(keyword),
            )
        )
    if date_from:
        q = q.filter(Project.created_at >= date_from)
    if date_to:
        q = q.filter(Project.created_at <= date_to)

    # 总数
    total = q.count()

    # 排序
    sort_col = getattr(Project, sort_by, Project.created_at)
    if sort_desc:
        q = q.order_by(sort_col.desc())
    else:
        q = q.order_by(sort_col.asc())

    # 分页
    projects = q.offset((page - 1) * per_page).limit(per_page).all()

    return projects, total


def update_project_status(project_id: int, status: str, notes: str = None):
    """更新项目跟进状态"""
    project = Project.query.get(project_id)
    if project:
        project.status = status
        if notes:
            project.notes = notes
        project.updated_at = datetime.datetime.now()
        db.session.commit()


def mark_as_notified(project_ids: list):
    """批量标记为已通知"""
    Project.query.filter(Project.id.in_(project_ids)).update(
        {"notified": True, "notified_at": datetime.datetime.now()},
        synchronize_session=False,
    )
    db.session.commit()


def get_unnotified_high_priority() -> list:
    """获取未通知的高优先级项目（用于邮件）"""
    return (Project.query
            .filter(Project.notified == False)
            .filter(Project.need_base_station.in_(["高", "中"]))
            .filter(Project.priority >= 3)
            .order_by(Project.priority.desc())
            .all())


# ============================
# 统计操作
# ============================
def get_stats_this_week() -> dict:
    """获取本周统计概览"""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    week_start_dt = datetime.datetime.combine(week_start, datetime.time.min)

    month_start = today.replace(day=1)
    month_start_dt = datetime.datetime.combine(month_start, datetime.time.min)

    return {
        "new_this_week": Project.query.filter(
            Project.created_at >= week_start_dt
        ).count(),
        "high_priority": Project.query.filter(
            Project.priority >= 4
        ).count(),
        "urgent": Project.query.filter(
            Project.priority >= 4,
            Project.status == "新发现",
        ).count(),
        "signed_this_month": Project.query.filter(
            Project.status == "已签约",
            Project.updated_at >= month_start_dt,
        ).count(),
    }


def get_district_stats() -> list:
    """获取各区县项目数量统计"""
    results = (db.session.query(
        Project.district,
        func.count(Project.id).label("count")
    )
        .filter(Project.district.isnot(None))
        .filter(Project.district != "")
        .group_by(Project.district)
        .order_by(func.count(Project.id).desc())
        .all())
    return [{"name": r[0], "value": r[1]} for r in results]


def get_weekly_trend(weeks: int = 8) -> list:
    """获取近N周新增项目趋势"""
    today = datetime.date.today()
    trend = []
    for i in range(weeks - 1, -1, -1):
        week_start = today - datetime.timedelta(days=today.weekday() + i * 7)
        week_end = week_start + datetime.timedelta(days=6)
        count = Project.query.filter(
            Project.created_at >= datetime.datetime.combine(week_start, datetime.time.min),
            Project.created_at <= datetime.datetime.combine(week_end, datetime.time.max),
        ).count()
        trend.append({
            "week": f"{week_start.month}/{week_start.day}",
            "count": count,
        })
    return trend


# ============================
# 爬取日志操作
# ============================
def create_crawl_log(spider_name: str) -> CrawlLog:
    """创建爬取日志（开始爬取时调用）"""
    log = CrawlLog(spider_name=spider_name, start_time=datetime.datetime.now())
    db.session.add(log)
    db.session.commit()
    return log


def finish_crawl_log(log_id: int, items_found: int, items_new: int,
                     status: str = "success", error_message: str = None):
    """完成爬取日志"""
    log = CrawlLog.query.get(log_id)
    if log:
        log.end_time = datetime.datetime.now()
        log.items_found = items_found
        log.items_new = items_new
        log.status = status
        log.error_message = error_message
        db.session.commit()


# ============================
# 初始化数据库
# ============================
def init_db(app):
    """初始化数据库并创建默认管理员账号"""
    db.init_app(app)
    with app.app_context():
        db.create_all()

        # 创建默认管理员（如果不存在）
        if not get_user_by_username("admin"):
            admin = User(
                username="admin",
                display_name="管理员",
                email=None,
                role="admin",
            )
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
            print("[OK] 默认管理员账号已创建: admin / admin123")
