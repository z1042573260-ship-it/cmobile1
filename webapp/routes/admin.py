"""
管理后台路由
-----------
用户管理、系统配置（仅管理员可访问）
"""
import subprocess
import sys
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from database.models import db, User, CrawlLog
from database.db_manager import create_user, get_all_users

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(func):
    """装饰器：检查是否为管理员"""
    from functools import wraps
    @wraps(func)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin():
            flash("您没有管理权限", "danger")
            return redirect(url_for("dashboard.index"))
        return func(*args, **kwargs)
    return wrapper


@admin_bp.route("/")
@admin_required
def index():
    """管理后台首页"""
    users = get_all_users()

    # 最近爬取日志
    recent_logs = (CrawlLog.query
                   .order_by(CrawlLog.start_time.desc())
                   .limit(20)
                   .all())

    return render_template(
        "admin.html",
        users=users,
        recent_logs=recent_logs,
    )


# ============================
# 用户管理
# ============================
@admin_bp.route("/users/add", methods=["POST"])
@admin_required
def add_user():
    """添加用户"""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    display_name = request.form.get("display_name", "").strip()
    email = request.form.get("email", "").strip() or None
    role = request.form.get("role", "user")

    if not username or not password or not display_name:
        flash("请填写完整的用户信息", "danger")
        return redirect(url_for("admin.index"))

    # 检查是否已存在
    from database.db_manager import get_user_by_username
    if get_user_by_username(username):
        flash(f"用户名 '{username}' 已存在", "danger")
        return redirect(url_for("admin.index"))

    create_user(username, password, display_name, email, role)
    flash(f"用户 '{display_name}' 已创建", "success")
    return redirect(url_for("admin.index"))


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id: int):
    """启用/禁用用户"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "用户不存在"}), 404

    if user.id == current_user.id:
        return jsonify({"success": False, "message": "不能禁用自己"}), 400

    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({
        "success": True,
        "is_active": user.is_active,
        "message": "用户已启用" if user.is_active else "用户已禁用",
    })


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_password(user_id: int):
    """重置用户密码"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "用户不存在"}), 404

    data = request.get_json()
    new_password = data.get("password", "123456")
    user.set_password(new_password)
    db.session.commit()
    return jsonify({"success": True, "message": "密码已重置"})


# ============================
# 爬虫手动触发
# ============================
@admin_bp.route("/trigger-spider", methods=["POST"])
@admin_required
def trigger_spider():
    """手动触发爬虫（通过后台运行）"""
    try:
        scheduler_path = Path(__file__).resolve().parent.parent.parent / "crawler" / "scheduler.py"
        # 在后台运行爬虫
        subprocess.Popen(
            [sys.executable, str(scheduler_path)],
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        flash("爬虫已触发，正在后台运行...", "success")
    except Exception as e:
        flash(f"触发爬虫失败: {e}", "danger")

    return redirect(url_for("admin.index"))
