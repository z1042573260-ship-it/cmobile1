@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo 🏗️ 烟台基站工程情报系统 - 看板启动
echo ============================================
echo.
echo 📍 本地访问: http://localhost:5000
echo 📍 局域网访问: http://你的电脑IP:5000
echo 👤 默认管理员: admin / admin123
echo.
echo 按 Ctrl+C 可停止服务
echo ============================================
echo.

call venv\Scripts\activate.bat
python -m webapp.app

pause >nul
