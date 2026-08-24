"""
用户认证模块
-----------
登录、登出、密码修改。
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user,
)

from database.models import User
from database.db_manager import get_user_by_username

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id):
    """加载当前登录用户"""
    return User.query.get(int(user_id))


# ============================
# 登录
# ============================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """登录页面"""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("请输入用户名和密码", "danger")
            return render_template("login.html")

        user = get_user_by_username(username)

        if user and user.check_password(password):
            if not user.is_active:
                flash("此账号已被禁用，请联系管理员", "danger")
                return render_template("login.html")

            login_user(user, remember=request.form.get("remember"))
            flash(f"欢迎回来，{user.display_name}！", "success")

            # 跳转到原目标页面（如果有的话）
            next_page = request.args.get("next")
            if next_page:
                return redirect(next_page)
            return redirect(url_for("dashboard.index"))
        else:
            flash("用户名或密码错误", "danger")

    return render_template("login.html")


# ============================
# 登出
# ============================
@auth_bp.route("/logout")
@login_required
def logout():
    """退出登录"""
    logout_user()
    flash("已退出登录", "info")
    return redirect(url_for("auth.login"))


# ============================
# 修改密码
# ============================
@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """修改密码"""
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_user.check_password(old_password):
            flash("原密码错误", "danger")
            return render_template("change_password.html")

        if new_password != confirm_password:
            flash("两次输入的新密码不一致", "danger")
            return render_template("change_password.html")

        if len(new_password) < 6:
            flash("新密码长度不能少于6位", "danger")
            return render_template("change_password.html")

        from database.models import db
        current_user.set_password(new_password)
        db.session.commit()
        flash("密码修改成功！", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("change_password.html")
