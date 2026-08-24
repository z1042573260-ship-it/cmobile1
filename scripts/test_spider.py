"""
爬虫调试脚本
-------
单独测试某个爬虫，结果保存为 JSON 文件供人工审核，
不写入数据库，不触发 AI 处理。

用法:
    python scripts/test_spider.py              # 列出所有爬虫
    python scripts/test_spider.py landchina    # 测试单个爬虫
    python scripts/test_spider.py all          # 测试全部爬虫
"""
import sys
import json
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler.spiders.landchina import LandChinaSpider
from crawler.spiders.shandong_approval import ShandongApprovalSpider
from crawler.spiders.yantai_planning import YantaiPlanningSpider
from crawler.spiders.yantai_bidding import YantaiBiddingSpider
from crawler.spiders.yantai_epb import YantaiEPBSpider
from crawler.spiders.ybb import YBBSpider
from crawler.spiders.shm_news import ShmNewsSpider
from crawler.spiders.yantai_investment import YantaiInvestmentSpider
from crawler.spiders.shandong_transport import ShandongTransportSpider
from crawler.spiders.shandong_zbxx import ShandongZbxxSpider
from crawler.spiders.yantai_districts import YantaiDistrictsSpider

# ---- 正常工作的爬虫 ----
SPIDERS = {
    "shm_news": ShmNewsSpider(),
    "yantai_planning": YantaiPlanningSpider(),
    "yantai_bidding": YantaiBiddingSpider(),
    "yantai_investment": YantaiInvestmentSpider(),
    "shandong_transport": ShandongTransportSpider(),
    "shandong_zbxx": ShandongZbxxSpider(),
    "yantai_districts": YantaiDistrictsSpider(),
}

# ---- 失效爬虫（代码保留，单独可测，不参与 all 批量运行）----
DISABLED_SPIDERS = {
    "landchina": LandChinaSpider(),
    "shandong_approval": ShandongApprovalSpider(),
    "yantai_epb": YantaiEPBSpider(),
    "ybb": YBBSpider(),
}

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "spider_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def print_score_detail(detail: dict, indent: str = "    "):
    """打印评分明细"""
    if not detail:
        return
    pos = detail.get("positive", [])
    neg = detail.get("negative", [])
    scale = detail.get("scale", [])

    if pos:
        items = [f"+{s}({k})" for s, k in pos]
        print(f"{indent}正向: {', '.join(items[:6])}")
    if neg:
        items = [f"{s}({k})" for s, k in neg]
        print(f"{indent}负向: {', '.join(items[:6])}")
    if scale:
        items = [f"+{s}({t})" for s, t in scale]
        print(f"{indent}规模: {', '.join(items)}")


def print_quality_bar(stats: dict):
    """打印质量统计栏"""
    high = stats.get("高质量", 0)
    mid = stats.get("中等", 0)
    low = stats.get("低质量", 0)
    discard = stats.get("应丢弃", 0) + stats.get("流程公告", 0)
    total = high + mid + low + discard
    if total == 0:
        return

    print(f"\n{'─'*60}")
    print(f"质量分布 ({total} 条):  "
          f"[高]{high}  [中]{mid}  [低]{low}  [丢]{discard}")
    bar_width = 40
    if total > 0:
        h_w = int(high / total * bar_width)
        m_w = int(mid / total * bar_width)
        l_w = int(low / total * bar_width)
        d_w = bar_width - h_w - m_w - l_w
        print(f"  [{'#'*h_w}{'='*m_w}{'-'*l_w}{'.'*d_w}]")


def test_spider(key: str, start_date: str = "", end_date: str = ""):
    spider = SPIDERS[key]
    # 日期范围参数（yantai_districts 支持 START_DATE/END_DATE；其他爬虫忽略）
    if start_date and hasattr(spider, "START_DATE"):
        spider.START_DATE = start_date
        print(f"  起始日期: {start_date}（覆盖 START_DATE）")
    if end_date and hasattr(spider, "END_DATE"):
        spider.END_DATE = end_date
        print(f"  结束日期: {end_date}（END_DATE）")
    print(f"\n{'='*60}")
    print(f"测试爬虫: {spider.name}")
    print(f"数据来源: {spider.source_name}")
    print(f"{'='*60}")

    failed = False
    try:
        results = spider.run()
    except Exception as e:
        print(f"[FAIL] 爬取异常: {e}")
        import traceback
        traceback.print_exc()
        return 1

    if not results:
        print("[EMPTY] 未爬取到任何数据。")
        print("可能原因: 1) 网站不可达  2) 评分阈值过高  3) 网站反爬")
        return 1

    # ---- 自动化可靠性：检测区县级静默失败（0 条/API 失败） ----
    if hasattr(spider, "district_stats"):
        for dk, ds in spider.district_stats.items():
            if ds.get("items_kept", 0) == 0 or ds.get("error"):
                failed = True
                print(f"[WARN] 区县 [{ds.get('name_cn', dk)}] 0 条"
                      f"{'  (' + ds['error'] + ')' if ds.get('error') else ''}")

    # ---- 质量统计 ----
    stats = {"高质量": 0, "中等": 0, "低质量": 0, "应丢弃": 0, "流程公告": 0}
    for item in results:
        score = item.get("relevance_score", 0)
        if score >= 5:
            stats["高质量"] += 1
        elif score >= 3:
            stats["中等"] += 1
        elif score >= 1:
            stats["低质量"] += 1
        else:
            stats["应丢弃"] += 1

    # ---- 保存 JSON ----
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"{spider.name}_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 爬取到 {len(results)} 条数据")
    print(f"结果已保存: {output_file}")
    print_quality_bar(stats)

    # ---- 打印所有条目（含评分）----
    print(f"\n{'─'*60}")
    print(f"全部 {len(results)} 条:")
    print(f"{'─'*60}")

    for i, item in enumerate(results, 1):
        score = item.get("relevance_score", "?")
        district = item.get("district_extracted", "")
        scale = item.get("scale_extracted", "")
        nature = item.get("project_nature", "")
        title = item.get("title", "N/A")[:70]
        # 清理不可打印字符（零宽空格等）
        title = title.replace("​", "").replace("﻿", "")

        # 评分等级图标
        if isinstance(score, int):
            if score >= 5:
                icon = "[高]"
            elif score >= 3:
                icon = "[中]"
            elif score >= 1:
                icon = "[低]"
            else:
                icon = "[弃]"
        else:
            icon = "[?]"

        # 附加信息
        extras = []
        if district:
            extras.append(f"区:{district}")
        if scale:
            extras.append(f"规模:{scale}")
        if nature:
            extras.append(f"性质:{nature}")

        extra_str = "  " + " ".join(extras) if extras else ""

        print(f"\n[{i}] {icon} 评分:{score:>3} | {title}")
        if extra_str:
            print(f"    {extra_str}")

        # 显示评分明细
        detail = item.get("score_detail", {})
        if detail:
            print_score_detail(detail)

        # 显示来源URL
        url = item.get("source_url", "")
        if url:
            print(f"    URL: {url[:100]}")

        # 内容预览
        content = item.get("content", "")
        if content:
            preview = content.replace("\n", " ").replace("\xa0", " ")[:120]
            print(f"    内容: {preview}...")

    # ---- 最终摘要 ----
    print(f"\n{'='*60}")
    print(f"摘要: {len(results)} 条通过评分过滤")
    print(f"  高质量(>=5分): {stats['高质量']} 条")
    print(f"  中等(3-4分):   {stats['中等']} 条")
    print(f"  低质量(1-2分): {stats['低质量']} 条")

    # 如果有爬虫内部的统计信息，也打印
    if hasattr(spider, 'stats'):
        s = spider.stats
        print(f"\n爬虫内部统计:")
        print(f"  主页总数:       {s.get('total_found', '?')}")
        print(f"  流程公告跳过:   {s.get('skipped_process', '?')}")
        print(f"  低分跳过:       {s.get('skipped_low_score', '?')}")
        print(f"  详情获取成功:   {s.get('details_fetched', '?')}")
        print(f"  详情获取失败:   {s.get('details_failed', '?')}")

    print(f"\n提示: 用 python scripts/review_data.py {output_file} 进行人工审核")
    return 1 if failed else 0


if __name__ == "__main__":
    # 合并所有爬虫用于查找
    ALL_SPIDERS = {**SPIDERS, **DISABLED_SPIDERS}

    # 简单参数解析：<爬虫名> [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
    args = sys.argv[1:]
    target = args[0] if args else ""
    start_date = end_date = ""
    i = 1
    while i < len(args):
        if args[i] == "--start-date" and i + 1 < len(args):
            start_date = args[i + 1]; i += 2
        elif args[i] == "--end-date" and i + 1 < len(args):
            end_date = args[i + 1]; i += 2
        else:
            i += 1

    if not target:
        print("正常爬虫 (all 模式会运行):")
        for k, v in SPIDERS.items():
            print(f"  ✅ {k:25s} -> {v.source_name}")
        print(f"\n失效爬虫（保留代码，单独可测）:")
        for k, v in DISABLED_SPIDERS.items():
            print(f"  ❌ {k:25s} -> {v.source_name}")
        print(f"\n用法: python scripts/test_spider.py <爬虫名> [--start-date 2026-07-23] [--end-date 2026-08-13]")
        print(f"      python scripts/test_spider.py all     # 只跑正常爬虫")
        sys.exit(0)

    exit_code = 0
    if target == "all":
        for k in SPIDERS:
            rc = test_spider(k, start_date, end_date)
            exit_code = exit_code or rc
            print()
    elif target in ALL_SPIDERS:
        exit_code = test_spider(target, start_date, end_date)
    else:
        print(f"未知爬虫: {target}")
        print(f"正常爬虫: {', '.join(SPIDERS.keys())}")
        print(f"失效爬虫: {', '.join(DISABLED_SPIDERS.keys())}")
        print(f"全部: all")
        sys.exit(1)

    # 自动化可靠性：有失败区县/异常时退出码非 0（后台任务可检测告警）
    sys.exit(exit_code)
