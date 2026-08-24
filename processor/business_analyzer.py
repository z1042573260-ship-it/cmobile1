"""
B2B 商机情报分析管线（向后兼容封装）
----------------------------------
已迁移到 processor.ai_pipeline（统一情报分析管线）。
本文件保留作为薄封装，委托给 ai_pipeline.py，确保旧代码和 CLI 不受影响。

用法（推荐直接用新接口）：
  from processor.ai_pipeline import run_unified_pipeline, analyze_project
  result = run_unified_pipeline(records, "data/dashboard_data.json")

用法（旧接口，仍然可用）：
  from processor.business_analyzer import run_business_pipeline
  result = run_business_pipeline(records, "data/dashboard_data.json")
"""
from __future__ import annotations

import json
import datetime
from typing import Optional
from loguru import logger

# 委托给统一管线
from processor.ai_pipeline import run_unified_pipeline, analyze_project


def analyze_single(title: str, summary: str, date_str: str, url: str) -> Optional[dict]:
    """
    对单条新闻进行 AI 分析（旧接口，委托给统一管线）。

    保留此函数以兼容旧调用方。
    """
    return analyze_project(
        title=title,
        content=summary,
        publish_date=date_str,
        source_url=url,
        source_name="手动调用",
    )


def run_business_pipeline(input_records: list[dict],
                          output_json_path: str = "data/dashboard_data.json",
                          db_path: str = None,
                          verbose: bool = True) -> list[dict]:
    """
    B2B 商机分析完整管线（旧接口，委托给统一管线）。

    保留此函数以兼容旧调用方。新代码请直接用 run_unified_pipeline()。
    """
    logger.info("💡 提示: business_analyzer.run_business_pipeline() 已迁移到 ai_pipeline.run_unified_pipeline()")
    return run_unified_pipeline(
        input_records=input_records,
        output_json_path=output_json_path,
        db_path=db_path,
        verbose=verbose,
    )


# ==============================================================================
# CLI (测试用 — 保持兼容)
# ==============================================================================

def main():
    """命令行入口：测试单条或批量 AI 分析。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="B2B 商机分析管线 — 豆包 AI 深度推理（已迁移到 ai_pipeline）",
    )
    parser.add_argument(
        "--input-json", type=str,
        help="输入 JSON 文件（aggregate.py 的输出）",
    )
    parser.add_argument(
        "--output-json", type=str, default="data/dashboard_data.json",
        help="输出 JSON 路径（默认 data/dashboard_data.json）",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="SQLite 数据库路径（可选）",
    )
    parser.add_argument(
        "--max-items", type=int, default=0,
        help="最多分析 N 条（0=全部，测试用）",
    )
    parser.add_argument(
        "--test-single", type=str, default=None,
        help="测试单条分析: '标题|摘要|日期|URL'",
    )

    args = parser.parse_args()

    # 单条测试模式
    if args.test_single:
        parts = args.test_single.split("|")
        title = parts[0] if len(parts) > 0 else "测试项目"
        summary = parts[1] if len(parts) > 1 else ""
        date_str = parts[2] if len(parts) > 2 else str(datetime.date.today())
        url = parts[3] if len(parts) > 3 else ""

        print(f"测试: {title[:50]}...")
        result = analyze_single(title, summary, date_str, url)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 批量模式
    if not args.input_json:
        logger.error("请指定 --input-json 或 --test-single")
        return

    with open(args.input_json, "r", encoding="utf-8") as f:
        records = json.load(f)

    if args.max_items > 0:
        records = records[:args.max_items]
        logger.info(f"限制分析数量: {args.max_items} 条")

    run_business_pipeline(
        input_records=records,
        output_json_path=args.output_json,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
