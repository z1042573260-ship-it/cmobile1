"""
邮件通知模块
-----------
每周向收件人发送高价值项目汇总邮件。
使用 QQ邮箱 SMTP 服务发送。
"""
import datetime
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from loguru import logger

from config.settings import (
    EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT,
    EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS,
)
from database.db_manager import get_unnotified_high_priority, mark_as_notified


def _build_html_email(projects: list) -> str:
    """构建 HTML 邮件内容"""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())

    # 统计
    high_count = sum(1 for p in projects if p.need_base_station == "高")
    mid_count = sum(1 for p in projects if p.need_base_station == "中")
    priority_5 = sum(1 for p in projects if p.priority >= 5)
    priority_4 = sum(1 for p in projects if p.priority == 4)

    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; color: #333; }}
            .header {{ background: linear-gradient(135deg, #1a73e8, #0d47a1);
                       color: white; padding: 30px; border-radius: 8px 8px 0 0; }}
            .header h1 {{ margin: 0; font-size: 22px; }}
            .header p {{ margin: 8px 0 0; opacity: 0.9; font-size: 14px; }}
            .stats {{ display: flex; gap: 15px; padding: 20px;
                      background: #f5f7fa; border-bottom: 1px solid #e0e0e0; }}
            .stat-box {{ flex: 1; text-align: center; padding: 12px;
                         background: white; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .stat-box .num {{ font-size: 28px; font-weight: bold; color: #1a73e8; }}
            .stat-box .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
            .table-container {{ padding: 20px; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
            th {{ background: #f5f7fa; padding: 10px 8px; text-align: left;
                 border-bottom: 2px solid #e0e0e0; font-weight: 600; }}
            td {{ padding: 10px 8px; border-bottom: 1px solid #f0f0f0; }}
            tr:hover {{ background: #f8f9ff; }}
            .priority {{ display: inline-block; padding: 2px 8px; border-radius: 10px;
                        font-size: 11px; font-weight: bold; }}
            .priority-5 {{ background: #ffebee; color: #c62828; }}
            .priority-4 {{ background: #fff3e0; color: #e65100; }}
            .priority-3 {{ background: #fffde7; color: #f9a825; }}
            .need-high {{ color: #c62828; font-weight: bold; }}
            .need-mid {{ color: #e65100; }}
            .footer {{ padding: 20px; color: #999; font-size: 11px;
                      text-align: center; border-top: 1px solid #e0e0e0; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏗️ 烟台基站工程情报 - 周报</h1>
            <p>报告周期：{week_start.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}
            　|　共 {len(projects)} 条高价值项目</p>
        </div>

        <div class="stats">
            <div class="stat-box">
                <div class="num">{len(projects)}</div>
                <div class="label">高价值项目总数</div>
            </div>
            <div class="stat-box">
                <div class="num">{high_count}</div>
                <div class="label">基站需求：高</div>
            </div>
            <div class="stat-box">
                <div class="num">{priority_5}</div>
                <div class="label">★★★★★ 最高优先级</div>
            </div>
            <div class="stat-box">
                <div class="num">{priority_4}</div>
                <div class="label">★★★★ 高优先级</div>
            </div>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>项目名称</th>
                        <th>类型</th>
                        <th>区县</th>
                        <th>规模</th>
                        <th>基站需求</th>
                        <th>优先级</th>
                        <th>发现日期</th>
                    </tr>
                </thead>
                <tbody>
    """

    for i, p in enumerate(projects, 1):
        priority_class = f"priority-{p.priority}" if p.priority >= 3 else ""
        need_class = "need-high" if p.need_base_station == "高" else (
            "need-mid" if p.need_base_station == "中" else ""
        )
        date_str = p.created_at.strftime("%m-%d") if p.created_at else ""

        html += f"""
                    <tr>
                        <td>{i}</td>
                        <td>
                            {'<a href="' + p.source_url + '" target="_blank">' + p.project_name + '</a>'
                              if p.source_url else p.project_name}
                        </td>
                        <td>{p.project_type or '-'}</td>
                        <td>{p.district or '-'}</td>
                        <td>{p.scale or '-'}</td>
                        <td class="{need_class}">{p.need_base_station or '-'}</td>
                        <td><span class="priority {priority_class}">{"★" * p.priority}</span></td>
                        <td>{date_str}</td>
                    </tr>
        """

    html += """
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>本邮件由「烟台基站工程情报自动化监控系统」自动发送</p>
            <p>如需调整通知偏好或退订，请联系系统管理员</p>
        </div>
    </body>
    </html>
    """
    return html


def _validate_email_config(to_emails: list) -> tuple:
    """验证邮件配置和收件人列表，返回 (是否有效, 过滤后的收件人列表)"""
    if not EMAIL_SENDER:
        logger.warning("邮件发件人未配置")
        return False, []

    if EMAIL_PASSWORD in ("", "your-smtp-auth-code"):
        logger.warning("邮件密码未配置，请在 config/settings.py 中设置 EMAIL_PASSWORD（QQ邮箱授权码）")
        return False, []

    if not to_emails:
        logger.warning("无收件人，跳过发送")
        return False, []

    # 过滤空邮箱
    to_emails = [e.strip() for e in to_emails if e.strip()]

    if not to_emails:
        logger.warning("收件人列表为空")
        return False, []

    return True, to_emails


def _send_mime_message(msg, to_emails: list) -> bool:
    """SMTP SSL 发送（共享逻辑）"""
    try:
        server = smtplib.SMTP_SSL(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, to_emails, msg.as_string())
        server.quit()
        logger.info(f"✅ 邮件已发送至 {len(to_emails)} 位收件人")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("邮箱认证失败！请检查 QQ邮箱 SMTP 授权码是否正确")
        return False
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False


def send_email(to_emails: list, subject: str, html_body: str) -> bool:
    """
    发送 HTML 邮件

    Returns:
        True 表示发送成功
    """
    valid, to_emails = _validate_email_config(to_emails)
    if not valid:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = Header("烟台基站情报系统", "utf-8").encode() + " <" + EMAIL_SENDER + ">"
    msg["To"] = ", ".join(to_emails)

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return _send_mime_message(msg, to_emails)


def send_report_email(to_emails: list, report_file: str = "report.html") -> bool:
    """
    发送报告邮件（HTML 附件）

    读取 frontend/<report_file> 作为附件发送（默认 report.html，可传 report2.html），
    邮件正文为简短说明文字。

    Returns:
        True 表示发送成功
    """
    import os

    valid, to_emails = _validate_email_config(to_emails)
    if not valid:
        return False

    # 读取报告模板（report.html / report2.html）
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
    frontend_dir = os.path.abspath(frontend_dir)
    report_path = os.path.join(frontend_dir, report_file)
    data_path = os.path.join(frontend_dir, "data", "dashboard_data.json")

    if not os.path.exists(report_path):
        logger.error(f"报告文件不存在: {report_path}")
        return False

    with open(report_path, "r", encoding="utf-8") as f:
        report_html = f.read()

    # TODO: 接入数据库后改为从 DB 查询数据，替换下面的 JSON 读取
    # 读取测试数据并注入 HTML，使邮件附件离线可用
    import json
    embedded_data = None
    if os.path.exists(data_path):
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                embedded_data = json.load(f)
        except Exception as e:
            logger.warning(f"读取数据文件失败: {e}")

    if embedded_data:
        json_str = json.dumps(embedded_data, ensure_ascii=False)
        # 使用 type="application/json" 避免 JSON 中的 </script> 等字符破坏 HTML
        inject_script = (
            '<script type="application/json" id="embedded-data">\n'
            + json_str +
            '\n</script>\n'
        )
        # 注入到 <script> 外部（<!-- EMAIL_DATA_INJECTION --> 在 report.html 中
        # 位于主 <script> 标签之前，避免 </script> 过早关闭主脚本块）
        report_html = report_html.replace(
            '<!-- EMAIL_DATA_INJECTION -->',
            '<!-- EMAIL_DATA_INJECTION -->\n' + inject_script
        )
        logger.info(f"已注入 {len(json_str)} 字节内嵌数据到报告")
    else:
        logger.warning("未找到测试数据文件，报告将使用兜底假数据")

    # 构建混合邮件：正文 + 附件（周报 Excel + 报告 HTML）
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(
        "建筑预警工程信息周报 - %s" % datetime.date.today().strftime("%Y-%m-%d"), "utf-8"
    )
    msg["From"] = Header("建筑预警工程信息周报", "utf-8").encode() + " <" + EMAIL_SENDER + ">"
    msg["To"] = ", ".join(to_emails)

    # 邮件正文（建筑预警工程信息周报风格：概览统计 + HTML 柱状图 + 附件说明）
    today = datetime.date.today()
    date_str = "%d-%02d-%02d" % (today.year, today.month, today.day)
    week_ago_d = today - datetime.timedelta(days=today.weekday())  # 本周一（自然周口径）
    week_range = "%d-%02d-%02d 至 %s" % (
        week_ago_d.year, week_ago_d.month, week_ago_d.day, date_str)

    # 本周统计 + HTML 柱状图（CSS div 高度，区县横坐标，邮件客户端兼容）
    try:
        from scripts.export_dashboard_db import fetch_weekly_stats
        st = fetch_weekly_stats()
    except Exception:
        st = {"total": 0, "red": 0, "yellow": 0, "district_count": 0, "by_district": []}

    max_cnt = max((e["total"] for e in st["by_district"]), default=0) or 1
    # 横向条形图（表格实现，邮件客户端 100% 兼容：区县名 + 条形 + 数值）
    bar_rows = []
    for e in st["by_district"]:
        w = max(int(e["total"] / max_cnt * 100), 4)  # 条宽 4%~100%
        bar_rows.append(
            '<tr>'
            '<td style="padding:5px 10px; font-size:13px; color:#333; white-space:nowrap; '
            'border-bottom:1px solid #eef1f4; width:90px;">{d}</td>'
            '<td style="padding:5px 0; border-bottom:1px solid #eef1f4;">'
            '<div style="background:#2f6db3; height:16px; width:{w}%; border-radius:3px; min-width:8px;"></div></td>'
            '<td style="padding:5px 10px; font-size:14px; font-weight:bold; color:#1a3d6d; '
            'text-align:center; border-bottom:1px solid #eef1f4; width:44px;">{c}</td>'
            '</tr>'.format(d=e["district"], w=w, c=e["total"])
        )
    bar_html = ('<table width="100%" style="border-collapse:collapse;">' + "".join(bar_rows)
                + '</table>') if bar_rows else "<p>本周暂无项目数据</p>"

    body = """
    <html>
    <body style="font-family: 'Microsoft YaHei', Arial, sans-serif; color: #333; line-height: 1.7; margin: 0; padding: 20px;">
        <div style="max-width: 680px; margin: 0 auto; border: 1px solid #e3e8ee; border-radius: 12px; overflow: hidden;">
            <div style="background: #1a3d6d; color: #fff; padding: 20px 28px;">
                <h2 style="margin: 0; font-size: 20px;">🏗️ 工程建设信息预警周报</h2>
                <div style="margin-top: 6px; font-size: 13px; opacity: 0.85;">报告周期：{week_range}</div>
            </div>
            <div style="padding: 24px 28px;">
                <p>您好：</p>
                <p>本期烟台地区建筑工程项目预警信息已汇总，重点情况如下：</p>

                <table style="width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 15px; text-align: center;">
                    <tr>
                        <td style="padding: 12px; border: 1px solid #e3e8ee; background: #f4f7fb;">
                            <div style="font-size: 26px; font-weight: bold; color: #1a3d6d;">{total}</div>
                            <div style="font-size: 12px; color: #666;">本周项目总数</div>
                        </td>
                        <td style="padding: 12px; border: 1px solid #e3e8ee; background: #fdf3f3;">
                            <div style="font-size: 26px; font-weight: bold; color: #e74c3c;">{red}</div>
                            <div style="font-size: 12px; color: #666;">红色预警</div>
                        </td>
                        <td style="padding: 12px; border: 1px solid #e3e8ee; background: #fef9ee;">
                            <div style="font-size: 26px; font-weight: bold; color: #f39c12;">{yellow}</div>
                            <div style="font-size: 12px; color: #666;">黄色预警</div>
                        </td>
                        <td style="padding: 12px; border: 1px solid #e3e8ee; background: #f4f7fb;">
                            <div style="font-size: 26px; font-weight: bold; color: #1a3d6d;">{dc}</div>
                            <div style="font-size: 12px; color: #666;">覆盖区县</div>
                        </td>
                    </tr>
                </table>

                <div style="background: #fafcff; border: 1px solid #e3e8ee; border-radius: 8px; padding: 16px 20px; margin: 14px 0;">
                    <div style="font-size: 14px; font-weight: bold; color: #1a3d6d; margin-bottom: 10px;">📊 本周区县项目分布</div>
                    {bar_html}
                </div>

                <p style="margin-top: 18px;">详细数据请查收附件：</p>
                <table style="width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px;">
                    <tr style="background: #f4f7fb;">
                        <td style="padding: 8px 12px; border: 1px solid #e3e8ee; width: 38%;">📊 周报 Excel</td>
                        <td style="padding: 8px 12px; border: 1px solid #e3e8ee;">概览 + 项目明细 + 区县柱状图（Excel 原生图表）</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 12px; border: 1px solid #e3e8ee;">📄 详细报告</td>
                        <td style="padding: 8px 12px; border: 1px solid #e3e8ee;">{report_file}（下载后用浏览器打开）</td>
                    </tr>
                </table>

                <p style="color: #999; font-size: 12px; margin-top: 24px; border-top: 1px solid #eef1f4; padding-top: 12px;">
                    本邮件由「建筑预警工程信息自动化监控系统」自动发送
                </p>
            </div>
        </div>
    </body>
    </html>
    """.format(
        week_range=week_range,
        total=st["total"], red=st["red"], yellow=st["yellow"],
        dc=st["district_count"], bar_html=bar_html,
        report_file=report_file,
    )
    msg.attach(MIMEText(body, "html", "utf-8"))

    # 附件 1：周报 Excel（本周项目 + 区县柱状图，原生图表）
    try:
        from scripts.export_dashboard_db import export_weekly_excel
        excel_path = export_weekly_excel()
        with open(excel_path, "rb") as f:
            xlsx_bytes = f.read()
        from email.mime.application import MIMEApplication
        xlsx_att = MIMEApplication(xlsx_bytes, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        xlsx_att.add_header("Content-Disposition", "attachment", filename=os.path.basename(excel_path))
        msg.attach(xlsx_att)
    except Exception as e:
        logger.error(f"周报 Excel 生成失败: {e}")

    # 附件 2：报告 HTML
    attachment = MIMEText(report_html, "html", "utf-8")
    attachment.add_header(
        "Content-Disposition", "attachment", filename=report_file
    )
    msg.attach(attachment)

    return _send_mime_message(msg, to_emails)


def send_weekly_digest(app) -> dict:
    """
    发送每周项目汇总邮件

    返回 {"sent": bool, "count": int}
    """
    with app.app_context():
        projects = get_unnotified_high_priority()

        if not projects:
            logger.info("无待通知的高优先级项目")
            return {"sent": False, "count": 0}

        subject = (
            f"🏗️ 烟台基站工程情报周报 - "
            f"{datetime.date.today().strftime('%Y-%m-%d')} "
            f"| {len(projects)} 条高价值项目"
        )

        html_body = _build_html_email(projects)

        success = send_email(
            to_emails=EMAIL_RECIPIENTS,
            subject=subject,
            html_body=html_body,
        )

        if success:
            # 标记为已通知
            project_ids = [p.id for p in projects]
            mark_as_notified(project_ids)
            logger.info(f"✅ 已标记 {len(project_ids)} 条项目为已通知")
            return {"sent": True, "count": len(projects)}
        else:
            return {"sent": False, "count": len(projects)}
