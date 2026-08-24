"""
Flask 主应用
-----------
启动看板 Web 服务的入口。
"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask
from loguru import logger

from config.settings import (
    DATABASE_URL, FLASK_SECRET_KEY,
    FLASK_HOST, FLASK_PORT,
    LOG_FILE, LOG_LEVEL, LOG_ROTATION, LOG_RETENTION,
)
from database.models import db
from database.db_manager import init_db


def create_app() -> Flask:
    """创建并配置 Flask 应用"""
    app = Flask(__name__)

    # 基础配置
    app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # 初始化数据库
    init_db(app)

    # 初始化登录管理器
    from webapp.auth import login_manager
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "请先登录后再访问此页面"
    login_manager.login_message_category = "warning"

    # 注册蓝图
    from webapp.auth import auth_bp
    from webapp.routes.dashboard import dashboard_bp
    from webapp.routes.projects import projects_bp
    from webapp.routes.admin import admin_bp
    from webapp.routes.report import report_bp

    app.register_blueprint(auth_bp)          # /auth/*
    app.register_blueprint(dashboard_bp)     # /
    app.register_blueprint(projects_bp)      # /projects/*
    app.register_blueprint(admin_bp)         # /admin/*
    app.register_blueprint(report_bp)        # /report, /api/report-data

    # 配置日志
    logger.remove()
    logger.add(sys.stderr, level=LOG_LEVEL)
    logger.add(LOG_FILE, level=LOG_LEVEL, rotation=LOG_ROTATION,
               retention=LOG_RETENTION, encoding="utf-8")

    return app


def main():
    """启动看板服务"""
    app = create_app()

    logger.info("=" * 50)
    logger.info("🏗️ 烟台基站工程情报系统 - 看板启动")
    logger.info(f"📍 本地访问: http://localhost:{FLASK_PORT}")
    logger.info(f"📍 局域网访问: http://<本机IP>:{FLASK_PORT}")
    logger.info(f"👤 默认管理员: admin / admin123")
    logger.info("=" * 50)

    app.run(
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=False,  # 生产环境关闭 debug
        threaded=True,  # 多线程处理请求
    )


if __name__ == "__main__":
    main()
