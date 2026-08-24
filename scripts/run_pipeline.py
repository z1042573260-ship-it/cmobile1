"""
一键管线：数据汇总 → AI 统一情报分析
----------------------------------
无需数据库，从爬虫 JSON 或审核表 Excel 读取，
汇总后直接调用 AI 管线，输出统一情报结果。

用法：
  # 爬虫 JSON → AI 分析（主力路径，content 字段有值，效果最好）
  python scripts/run_pipeline.py --from-json "data/spider_test/yantai_districts_merged.json"

  # JSON + Excel 双输出
  python scripts/run_pipeline.py --from-json "data/spider_test/yantai_districts_merged.json" \
      --output-json data/unified_intelligence.json \
      --output-excel data/unified_intelligence.xlsx

  # Excel 审核表 → AI 分析（测试用）
  python scripts/run_pipeline.py --from-excel "data/spider_test/*审核表*.xlsx"

  # 限制分析条数（测试用）
  python scripts/run_pipeline.py --from-json "data/spider_test/yantai_districts_merged.json" --limit 5

输出：
  data/unified_intelligence.json  — AI 分析结果（JSON）
  data/unified_intelligence.xlsx  — AI 分析结果（Excel，可选）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.aggregate import collect_from_json, collect_from_excel
from processor.ai_pipeline import run_unified_pipeline
from scripts.export_results import export_ai_results
from config.settings import UNIFIED_OUTPUT_JSON


def main():
    parser = argparse.ArgumentParser(
        description="一键管线：汇总 → AI 分析 → JSON + Excel 输出",
    )
    parser.add_argument(
        "--from-json", action="append", default=[],
        help="爬虫 JSON 文件（支持 glob），可多次指定",
    )
    parser.add_argument(
        "--from-excel", action="append", default=[],
        help="审核表 Excel 文件（支持 glob），可多次指定",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="限制 AI 分析条数（0=全部，测试时建议 5~10）",
    )
    parser.add_argument(
        "--output-json", type=str, default=UNIFIED_OUTPUT_JSON,
        help=f"输出 JSON 路径（默认: {UNIFIED_OUTPUT_JSON}）",
    )
    parser.add_argument(
        "--output-excel", type=str, default=None,
        help="输出 Excel 路径（可选，如 data/unified_intelligence.xlsx）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只汇总不分析，打印统计信息",
    )

    args = parser.parse_args()

    # ---- 收集 ----
    all_records = []

    for pattern in args.from_json:
        all_records.extend(collect_from_json(pattern))

    for pattern in args.from_excel:
        all_records.extend(collect_from_excel(pattern))

    if not all_records:
        logger.error("未收集到任何记录，请指定 --from-json 或 --from-excel")
        sys.exit(1)

    logger.info(f"共收集 {len(all_records)} 条记录")

    # 限制条数
    if args.limit > 0 and len(all_records) > args.limit:
        all_records = all_records[:args.limit]
        logger.info(f"限制分析前 {args.limit} 条")

    # 统计
    high = sum(1 for r in all_records if r.get("relevance_score", 0) >= 5)
    mid = sum(1 for r in all_records if 3 <= r.get("relevance_score", 0) < 5)
    low = sum(1 for r in all_records if 0 < r.get("relevance_score", 0) < 3)
    unrated = sum(1 for r in all_records if r.get("relevance_score", 0) == 0)
    with_content = sum(1 for r in all_records if r.get("content", "").strip())

    logger.info(
        f"评分分布: 高{high} / 中{mid} / 低{low} / 未评分{unrated}  |  "
        f"有正文: {with_content}/{len(all_records)}"
    )

    if args.dry_run:
        logger.info("--dry-run 模式，跳过 AI 分析")
        return

    # ---- AI 分析 ----
    logger.info("🤖 启动 AI 统一情报分析（基站选址 + B2B商机）...")
    results = run_unified_pipeline(
        input_records=all_records,
        output_json_path=args.output_json,
        db_path=None,  # 不写数据库
    )

    # ---- 统计结果 ----
    if results:
        priority_high = sum(1 for r in results if r.get("priority", 0) >= 4)
        need_station = sum(1 for r in results if r.get("need_base_station") in ("高", "中"))
        valuable = sum(1 for r in results if r.get("is_valuable"))

        logger.info("=" * 50)
        logger.info("📊 分析结果统计:")
        logger.info(f"   总项目: {len(results)}")
        logger.info(f"   高优先级(≥4): {priority_high}")
        logger.info(f"   需要基站: {need_station}")
        logger.info(f"   有商机价值: {valuable}")
        logger.info(f"   JSON 输出: {args.output_json}")

        # ---- Excel 导出 ----
        if args.output_excel:
            export_ai_results(results, args.output_excel)
            logger.info(f"   Excel 输出: {args.output_excel}")

        logger.info("=" * 50)

    logger.info("✅ 管线完成")


if __name__ == "__main__":
    main()
