"""
数据库模型定义
--------------
三个核心表：
  1. User        - 看板用户
  2. RawProject  - 爬虫原始数据（未清洗）
  3. Project     - AI 分析后的结构化项目数据
"""
import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ============================
# 用户表
# ============================
class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(50), nullable=False)  # 显示名称
    email = db.Column(db.String(100), nullable=True)
    role = db.Column(db.String(20), default="user")  # admin / user
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    def set_password(self, password: str):
        """设置密码（自动哈希）"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """验证密码"""
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        return self.role == "admin"

    def __repr__(self):
        return f"<User {self.username}>"


# ============================
# 原始项目表（爬虫直接产出）
# ============================
class RawProject(db.Model):
    """爬虫采集的原始数据，未经AI处理"""
    __tablename__ = "raw_projects"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(500), nullable=False)          # 公告标题
    content = db.Column(db.Text, nullable=True)                 # 公告正文
    source_url = db.Column(db.String(1000), nullable=True)      # 来源URL
    source_name = db.Column(db.String(100), nullable=False)     # 来源网站名称
    publish_date = db.Column(db.String(50), nullable=True)      # 原始发布日期
    raw_html = db.Column(db.Text, nullable=True)                # 原始HTML（备用）
    crawl_time = db.Column(db.DateTime, default=datetime.datetime.now)  # 爬取时间
    processed = db.Column(db.Boolean, default=False)            # 是否已被AI处理
    duplicate_of = db.Column(db.Integer, nullable=True)         # 如果是重复的，指向主记录ID

    def __repr__(self):
        return f"<RawProject {self.title[:50]}>"


# ============================
# 正式项目表（AI分析后的结构化数据）
# ============================
class Project(db.Model):
    """经过AI清洗、分类、打分的正式情报项目"""
    __tablename__ = "projects"

    # ---- 基本信息 ----
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_name = db.Column(db.String(500), nullable=False, unique=True)  # 项目名称（AI提取，唯一）
    project_type = db.Column(db.String(50), nullable=True)       # 工程类型：住宅/商业/学校/医院/...
    district = db.Column(db.String(50), nullable=True)           # 所属区县
    lng = db.Column(db.Numeric(10, 6), nullable=True)            # 经度（GCJ-02，大屏定位）
    lat = db.Column(db.Numeric(10, 6), nullable=True)            # 纬度（GCJ-02）
    location = db.Column(db.String(500), nullable=True)          # 详细地址
    scale = db.Column(db.String(200), nullable=True)             # 建设规模（如"1200户""5万㎡"）
    investment = db.Column(db.String(100), nullable=True)        # 投资金额
    content = db.Column(db.Text, nullable=True)                  # 公告原文（爬虫直存，不走AI）

    # ---- 建设单位信息 ----
    developer = db.Column(db.String(300), nullable=True)         # 建设单位/开发商
    contact_person = db.Column(db.String(100), nullable=True)    # 联系人
    contact_phone = db.Column(db.String(50), nullable=True)      # 联系电话

    # ---- 时间节点 ----
    publish_date = db.Column(db.String(50), nullable=True)       # 公告发布日期
    deadline = db.Column(db.String(50), nullable=True)           # 投标截止日期/报名截止
    start_date = db.Column(db.String(50), nullable=True)         # 预计开工日期
    end_date = db.Column(db.String(50), nullable=True)           # 预计竣工日期

    # ---- AI 分析结果 ----
    need_base_station = db.Column(db.String(10), nullable=True)  # 需要基站概率：高/中/低/无
    base_station_type = db.Column(db.String(20), nullable=True)  # 基站类型：宏站/室分/小站/宏站+室分/无需
    coverage_area = db.Column(db.String(200), nullable=True)     # 覆盖范围描述
    ai_reason = db.Column(db.Text, nullable=True)                # AI判断依据
    priority = db.Column(db.Integer, default=3)                  # 优先级 1-5星
    score = db.Column(db.Integer, default=0)                     # 商机评分 1-5
    warning_level = db.Column(db.String(10), nullable=True)      # 红色预警/黄色预警/无预警
    is_valuable = db.Column(db.Boolean, default=False)           # 是否有商机价值
    telecom_needs = db.Column(db.Text, nullable=True)            # 通信需求（JSON数组字符串）
    ai_summary = db.Column(db.Text, nullable=True)               # AI生成的摘要

    # ---- 来源信息 ----
    source_name = db.Column(db.String(100), nullable=True)       # 最早发现的来源
    source_url = db.Column(db.String(1000), nullable=True)       # 来源URL
    raw_ids = db.Column(db.String(500), nullable=True)           # 关联的原始记录ID（逗号分隔）

    # ---- 状态管理 ----
    status = db.Column(db.String(20), default="新发现")          # 项目阶段（规划立项/招标阶段/施工阶段/已竣工完工/待核实）
    processed_status = db.Column(db.Integer, default=0)          # 处理状态：0=未处理(项目明细) / 1=已处理
    processed_time = db.Column(db.DateTime, nullable=True)       # 处理时间（标记为已处理的时间）
    notified = db.Column(db.Boolean, default=False)              # 是否已邮件通知
    notified_at = db.Column(db.DateTime, nullable=True)          # 通知时间
    notes = db.Column(db.Text, nullable=True)                    # 用户备注/跟进记录

    # ---- 时间戳 ----
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.now,
                           onupdate=datetime.datetime.now)

    def to_dict(self) -> dict:
        """转为字典，方便JSON序列化"""
        return {
            "id": self.id,
            "project_name": self.project_name,
            "project_type": self.project_type,
            "district": self.district,
            "location": self.location,
            "scale": self.scale,
            "investment": self.investment,
            "content": self.content,
            "developer": self.developer,
            "contact_person": self.contact_person,
            "contact_phone": self.contact_phone,
            "publish_date": self.publish_date,
            "deadline": self.deadline,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "need_base_station": self.need_base_station,
            "base_station_type": self.base_station_type,
            "coverage_area": self.coverage_area,
            "ai_reason": self.ai_reason,
            "priority": self.priority,
            "score": self.score,
            "warning_level": self.warning_level,
            "is_valuable": self.is_valuable,
            "telecom_needs": self.telecom_needs,
            "ai_summary": self.ai_summary,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "status": self.status,
            "processed_status": self.processed_status,
            "processed_time": self.processed_time.isoformat() if self.processed_time else None,
            "notified": self.notified,
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Project {self.project_name[:50]}>"


# ============================
# 爬取日志表
# ============================
class CrawlLog(db.Model):
    """每次爬取任务的执行记录"""
    __tablename__ = "crawl_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    spider_name = db.Column(db.String(100), nullable=False)     # 爬虫名称
    start_time = db.Column(db.DateTime, nullable=True)           # 开始时间
    end_time = db.Column(db.DateTime, nullable=True)             # 结束时间
    items_found = db.Column(db.Integer, default=0)               # 抓取到的条目数
    items_new = db.Column(db.Integer, default=0)                  # 新增（去重后的）
    status = db.Column(db.String(20), default="running")         # running/success/failed
    error_message = db.Column(db.Text, nullable=True)            # 错误信息

    def __repr__(self):
        return f"<CrawlLog {self.spider_name} {self.status}>"
