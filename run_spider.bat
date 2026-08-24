@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo 🕷️ 烟台基站工程情报 - 爬虫流水线
echo ============================================
echo.
echo 正在启动爬虫采集 + AI分析 + 邮件通知...
echo.

call venv\Scripts\activate.bat
python crawler\scheduler.py

echo.
echo ============================================
echo 执行完毕！按任意键关闭窗口...
echo ============================================
pause >nul
