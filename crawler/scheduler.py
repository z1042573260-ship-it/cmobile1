"""
爬虫调度器
---------
负责依次运行所有爬虫，将结果写入数据库，
然后触发 AI 处理和邮件通知。
此文件也是 Windows 任务计划程序的入口点。
"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from config.settings import LOG_FILE, LOG_LEVEL, LOG_ROTATION, LOG_RETENTION
from database.models import db, RawProject
from database.db_manager import (
    add_raw_project, get_unprocessed_raws, mark_as_duplicate,
    mark_as_processed, create_crawl_log, finish_crawl_log, count_unprocessed,
)
from crawler.spiders.yantai_districts import YantaiDistrictsSpider
from crawler.spiders.yantai_planning import YantaiPlanningSpider
from crawler.spiders.yantai_bidding import YantaiBiddingSpider
from crawler.spiders.shm_news import ShmNewsSpider
from crawler.spiders.shandong_transport import ShandongTransportSpider
from crawler.spiders.shandong_zbxx import ShandongZbxxSpider
from crawler.spiders.yantai_investment import YantaiInvestmentSpider

# 配置日志
logger.remove()
logger.add(sys.stderr, level=LOG_LEVEL)
logger.add(LOG_FILE, level=LOG_LEVEL, rotation=LOG_ROTATION,
           retention=LOG_RETENTION, encoding="utf-8")

# 所有注册的爬虫（按优先级排序，仅保留工作中）
SPIDERS = [
    YantaiDistrictsSpider(),      # 1: 烟台13区县政府公告（466条，主力）
    YantaiPlanningSpider(),       # 2: 烟台自然资源和规划局（43条）
    YantaiBiddingSpider(),        # 3: 烟台公共资源交易网（70条）
    YantaiInvestmentSpider(),     # 4: 烟台投资促进中心（28条）
    ShmNewsSpider(),              # 5: 上海建工集团新闻（25条）
    ShandongTransportSpider(),    # 6: 山东省交通运输厅（4条）
    ShandongZbxxSpider(),         # 7: 山东省招标信息（5条）
]


def run_all_spiders(app) -> dict:
    """
    运行所有爬虫

    返回: {"total_found": 总数, "total_new": 新增数, "logs": [...]}
    """
    total_found = 0
    total_new = 0
    summary = []

    with app.app_context():
        for spider in SPIDERS:
            log_entry = create_crawl_log(spider.name)

            try:
                results = spider.run()
                total_found += len(results)

                new_count = 0
                for item in results:
                    # 简单去重：检查标题+来源是否已存在
                    existing = RawProject.query.filter_by(
                        title=item["title"],
                        source_name=spider.source_name,
                    ).first()

                    if existing:
                        # 标记为重复（保留第一个出现的）
                        logger.debug(f"重复跳过: {item['title'][:50]}")
                        continue

                    add_raw_project(
                        title=item["title"],
                        source_name=spider.source_name,
                        content=item.get("content", ""),
                        source_url=item.get("source_url", ""),
                        publish_date=item.get("publish_date", ""),
                    )
                    new_count += 1

                total_new += new_count
                finish_crawl_log(log_entry.id, len(results), new_count, "success")
                summary.append({
                    "name": spider.name,
                    "source": spider.source_name,
                    "found": len(results),
                    "new": new_count,
                    "status": "✅ 成功",
                })
                logger.info(
                    f"  {spider.source_name}: 爬取 {len(results)} 条, 新增 {new_count} 条"
                )

            except Exception as e:
                finish_crawl_log(log_entry.id, 0, 0, "failed", str(e))
                summary.append({
                    "name": spider.name,
                    "source": spider.source_name,
                    "found": 0,
                    "new": 0,
                    "status": f"❌ 失败: {e}",
                })
                logger.error(f"  {spider.source_name}: 爬取失败 - {e}")

    return {
        "total_found": total_found,
        "total_new": total_new,
        "summary": summary,
    }


def run_pipeline(app):
    """
    完整流水线：爬取 → 汇总 → AI统一情报分析（基站+商机） → 邮件通知
    这是 Windows 任务计划程序的入口
    """
    logger.info("=" * 60)
    logger.info("🚀 烟台基站工程情报系统 - 启动流水线")
    logger.info("=" * 60)

    # ---- 第一步：爬取 ----
    logger.info("📡 第一步：多源爬取...")
    result = run_all_spiders(app)
    logger.info(f"📊 爬取完成: 共获取 {result['total_found']} 条, "
                f"新增 {result['total_new']} 条")

    if result["total_new"] == 0:
        # 无新增爬虫数据：但可能仍有未处理记录（上次爬虫入库后未分析），继续 AI 环节
        with app.app_context():
            unproc = count_unprocessed()
        if unproc == 0:
            logger.info("📭 无新增数据且无未处理记录，流水线结束")
            return
        logger.info(f"📭 无新增爬虫数据，但有 {unproc} 条未处理记录，继续 AI 分析")

    # ---- 第二步：汇总（不做去重，交给 AI 处理） ----
    logger.info("🔄 第二步：汇总...")
    from scripts.aggregate import collect_from_db, export_json
    records = collect_from_db(app, limit=500)
    if records:
        from config.settings import DATA_DIR
        merged_path = str(DATA_DIR / "merged_for_ai.json")
        export_json(records, merged_path)
    else:
        logger.warning("汇总后无数据，跳过后续步骤")
        return

    # ---- 第三步：AI 统一情报分析（基站 + 商机，一次调用） ----
    logger.info("🤖 第三步：AI 统一情报分析（基站选址 + B2B商机）...")
    from processor.ai_pipeline import run_unified_pipeline
    from config.settings import UNIFIED_OUTPUT_JSON, UNIFIED_DB_PATH
    unified_results = run_unified_pipeline(
        input_records=records,
        output_json_path=UNIFIED_OUTPUT_JSON,
        db_path=UNIFIED_DB_PATH,
    )
    logger.info(f"✅ 统一分析完成: 产出 {len(unified_results)} 个情报项目")

    if not unified_results:
        logger.warning("AI 分析无结果，跳过入库/导出")
        return

    # ---- 第三步半：坐标补全（高德 5 级 + POI + 讯飞搜索，管线经纬度规范） ----
    logger.info("🗺️  第三步半：坐标补全（高德 + POI + 讯飞搜索）...")
    from scripts.import_workbuddy import fill_missing_coords, upsert_rows
    try:
        filled, missing = fill_missing_coords(unified_results)
        logger.info(f"坐标补全: 补 {filled} / 仍缺 {missing}（缺坐标记录暂不入库，保持待重试）")
    except Exception as e:
        logger.error(f"坐标补全失败: {e}")

    # ---- 第三步半：AI 结果自动入库（upsert 到 projects 表，不影响其他数据） ----
    logger.info("🗄️  第三步半：AI 结果写入 MySQL projects 表...")
    from scripts.import_workbuddy import upsert_rows
    try:
        ins, upd, skip = upsert_rows(unified_results)
        logger.info(f"✅ 入库完成: 新增 {ins} / 更新 {upd} / 跳过 {skip}")
    except Exception as e:
        logger.error(f"❌ 入库失败: {e}")

    # ---- 第三步半：标记本次已分析的原始记录（防下周重复分析） ----
    logger.info("🏷️  标记原始记录已处理...")
    raw_ids = set()
    for r in unified_results:
        for rid in r.get("_source_db_ids") or []:
            raw_ids.add(rid)
        if r.get("_source_db_id"):
            raw_ids.add(int(r["_source_db_id"]))
    marked = 0
    with app.app_context():
        for rid in raw_ids:
            try:
                mark_as_processed(rid)
                marked += 1
            except Exception as e:
                logger.warning(f"标记失败 id={rid}: {e}")
    logger.info(f"✅ 已标记 {marked}/{len(raw_ids)} 条原始记录")

    # ---- 第四步：自动导出大屏数据 + 报告数据（本月+本周） ----
    logger.info("📊 第四步：导出大屏数据 + 报告数据...")
    from scripts.export_dashboard_db import export_dashboard, export_report
    try:
        export_dashboard()
        export_report()
        # 详情卡片库（前端读 data/workbuddy.json）：统一情报结果复制过去，保证线上详情完整
        from config.settings import UNIFIED_OUTPUT_JSON, BASE_DIR
        import shutil
        src = Path(UNIFIED_OUTPUT_JSON)
        if src.exists():
            shutil.copyfile(src, BASE_DIR / "frontend" / "data" / "workbuddy.json")
        logger.info("✅ 大屏 dashboard_data.json + 报告 report_data.json + 详情 workbuddy.json 已更新")
    except Exception as e:
        logger.error(f"❌ 导出失败: {e}")

    # ---- 第五步：邮件通知（建筑预警工程信息周报） ----
    logger.info("📧 第五步：发送周报邮件...")
    from notifier.email_sender import send_report_email
    from config.settings import EMAIL_RECIPIENTS
    try:
        ok = send_report_email([e.strip() for e in EMAIL_RECIPIENTS if e.strip()])
        logger.info(f"✅ 周报邮件发送{'成功' if ok else '失败'}")
    except Exception as e:
        logger.error(f"❌ 周报邮件发送异常: {e}")

    logger.info("=" * 60)
    logger.info("🎉 流水线执行完毕")
    logger.info(f"   📊 爬取: {result['total_found']} 条 (新增 {result['total_new']})")
    logger.info(f"   🔄 汇总后（未去重，AI 判断）: {len(records)} 条")
    logger.info(f"   🤖 统一情报: {len(unified_results)} 个项目")
    logger.info(f"   📄 输出JSON: {UNIFIED_OUTPUT_JSON}")
    logger.info("=" * 60)


def main():
    """主入口 - 供 Windows 任务计划程序调用"""
    from flask import Flask
    from config.settings import DATABASE_URL, FLASK_SECRET_KEY

    # 创建 Flask 应用（仅用于数据库连接）
    app = Flask(__name__)
    app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    run_pipeline(app)


if __name__ == "__main__":
    main()
