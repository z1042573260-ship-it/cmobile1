"""
爬虫结果按日期范围统一过滤
----------------------------
对各爬虫 JSON 按 publish_date 过滤（早于 --start-date 或晚于 --end-date 的剔除；
publish_date 为空的保留——不确定的不丢）。输出到新文件，不覆盖原始结果。

用法:
  python scripts/filter_by_date.py "data/spider_test/*.json" --end-date 2026-08-13
  python scripts/filter_by_date.py "data/spider_test/*.json" --start-date 2026-07-23 --end-date 2026-08-13
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path


def norm_date(v) -> str:
    if not v:
        return ""
    s = str(v).replace(".", "-").strip()
    # 只认 YYYY-MM-DD（或 YYYY-MM-DD HH:MM）
    if len(s) >= 10 and s[:4].isdigit() and s[4] == "-" and s[5:7].isdigit() and s[7] == "-" and s[8:10].isdigit():
        return s[:10]
    return ""


def main():
    parser = argparse.ArgumentParser(description="爬虫 JSON 按日期范围过滤")
    parser.add_argument("pattern", nargs="+", help="JSON glob 或文件，可多个，如 data/spider_test/*.json")
    parser.add_argument("--start-date", default="", help="最早日期（含），默认不限制")
    parser.add_argument("--end-date", default="", help="最晚日期（含），默认不限制")
    parser.add_argument("--suffix", default="_up_to", help="输出文件后缀（原文件名+后缀+日期）")
    args = parser.parse_args()

    files = sorted(glob.glob(args.pattern))
    if not files:
        print(f"[ERROR] 无匹配文件: {args.pattern}")
        sys.exit(1)

    total_in = total_out = 0
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        kept = []
        for item in data:
            d = norm_date(item.get("publish_date"))
            if d and args.start_date and d < args.start_date:
                continue
            if d and args.end_date and d > args.end_date:
                continue
            kept.append(item)
        total_in += len(data)
        total_out += len(kept)
        if len(kept) != len(data):
            out = Path(fp).with_name(
                Path(fp).stem + args.suffix + ".json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(kept, f, ensure_ascii=False, indent=2)
            print(f"{Path(fp).name}: {len(data)} → {len(kept)} 条 → {out.name}")
        else:
            print(f"{Path(fp).name}: {len(data)} 条（无需过滤）")

    print(f"\n合计: {total_in} → {total_out} 条")


if __name__ == "__main__":
    main()
