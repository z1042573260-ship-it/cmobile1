"""
Token 消耗测试脚本
-----------------
从 Excel 取几条数据跑 AI 分析，实测每条 token 消耗。
同时补充 dashboard_test.json 中 3 条的 content 字段（轻量级，只提取原文）。

用法：
  python scripts/test_token_usage.py
"""
import json
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from loguru import logger

from processor.doubao_client import doubao
from processor.ai_pipeline import analyze_project, build_user_message, UNIFIED_SYSTEM_PROMPT


def test_fresh_items(excel_path: str, n: int = 5):
    """从 Excel 取 n 条新数据，跑完整 AI 管线，记录 token"""
    df = pd.read_excel(excel_path, engine='openpyxl')

    # 列名是乱码的，按位置读取
    # Col 0:序号 Col 1:评分 Col 2:区县 Col 3:标题 Col 4:日期 Col 8:发布时间 Col 9:URL Col 10:摘要
    cols = list(df.columns)
    title_col = cols[3]
    date_col = cols[4]
    url_col = cols[9]
    content_col = cols[10]

    print("=" * 60)
    print(f"[Test] Token 消耗测试 — 从 Excel 取 {n} 条跑 AI 分析")
    print(f"   数据源: {excel_path}")
    print(f"   总行数: {len(df)}")
    print("=" * 60)

    results = []
    for i in range(n):
        row = df.iloc[i]
        title = str(row[title_col]) if pd.notna(row[title_col]) else ""
        url = str(row[url_col]) if pd.notna(row[url_col]) else ""
        raw_date = row[date_col]
        raw_pub_date = row[cols[8]]
        date_str = str(raw_pub_date if pd.notna(raw_pub_date) else raw_date)[:10]
        content = str(row[content_col])[:500] if pd.notna(row[content_col]) else ""

        print(f"\n--- [{i+1}/{n}] {title[:60]} ---")
        print(f"   URL: {url[:80]}...")
        print(f"   Date: {date_str}")
        print(f"   爬虫摘要({len(content)}字): {content[:100]}...")

        usage_before = doubao.cumulative_usage.copy()

        result = analyze_project(title, content, date_str, url, "Excel导入")

        usage_after = doubao.cumulative_usage.copy()

        if result:
            this_call = {
                "prompt": usage_after["prompt_tokens"] - usage_before["prompt_tokens"],
                "completion": usage_after["completion_tokens"] - usage_before["completion_tokens"],
                "total": usage_after["total_tokens"] - usage_before["total_tokens"],
            }
            print(f"   [OK] 本条消耗: prompt={this_call['prompt']} completion={this_call['completion']} total={this_call['total']}")
            print(f"   基站需求:{result.get('need_base_station')} | 评分:{result.get('score')} | {result.get('warning_level')}")
            print(f"   AI摘要: {result.get('ai_summary','')[:80]}")
            result["_token_usage"] = this_call
            results.append(result)
        else:
            this_call = {
                "prompt": usage_after["prompt_tokens"] - usage_before["prompt_tokens"],
                "completion": usage_after["completion_tokens"] - usage_before["completion_tokens"],
                "total": usage_after["total_tokens"] - usage_before["total_tokens"],
            }
            print(f"   [FAIL] AI 分析失败 (仍消耗: {this_call['total']} tokens)")

        # 打印累计
        print(f"    累计: {usage_after['total_tokens']} tokens "
              f"({usage_after['call_count']}次调用) | "
              f"预算剩余: {usage_after['budget_remaining']/10000:.1f}万 "
              f"({usage_after['budget_used_pct']}%)")

    # 汇总
    print("\n" + "=" * 60)
    print(" 测试汇总")
    print("=" * 60)
    total_calls = doubao.cumulative_usage["call_count"]
    total_tokens = doubao.cumulative_usage["total_tokens"]
    if total_calls > 0:
        avg = total_tokens / total_calls
        print(f"   调用次数: {total_calls}")
        print(f"   总消耗: {total_tokens} tokens ({total_tokens/10000:.1f}万)")
        print(f"   平均每条: {avg:.0f} tokens")
        print(f"   预算剩余: {5_000_000 - total_tokens} ({(5_000_000-total_tokens)/10000:.1f}万)")
        print(f"   466条估算: {avg * 466:.0f} tokens ({(avg * 466)/10000:.1f}万)")
        if avg * 466 > 5_000_000:
            print(f"   [WARN]️ 超出预算! 需要优化策略")
        else:
            print(f"   [OK] 在预算范围内")

    return results


def supplement_content_for_existing(json_path: str):
    """
    为 dashboard_test.json 中已有的 3 条补充 content 字段。
    使用轻量级 AI 调用：只提取原文，不做完整分析（节省 token）。
    """
    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    print("\n" + "=" * 60)
    print(f" 补充 Content — {len(records)} 条已有记录")
    print("=" * 60)

    content_system = """你是一个网页内容提取器。请访问用户提供的URL，获取政府公告的完整原文，直接返回原文内容。

规则：
1. 只返回公告正文内容，不要添加任何解释或标记
2. 去除导航文字、网站头部、底部版权信息等非正文内容
3. 保留段落结构和格式
4. 如果是附件下载链接（PDF/Word），说明"公告为附件形式，无法直接获取"
5. 如果URL无法访问，返回"URL无法访问"
6. 最多返回2000字"""

    for i, rec in enumerate(records):
        url = rec.get("_source_url", "")
        title = rec.get("project_name", "")

        print(f"\n--- [{i+1}/{len(records)}] {title[:50]} ---")
        print(f"   URL: {url[:80]}...")

        usage_before = doubao.cumulative_usage.copy()

        try:
            content_text = doubao.chat(
                system_prompt=content_system,
                user_message=f"请访问以下链接获取公告原文：{url}\n公告标题：{rec.get('_title', title)}",
                temperature=0.0,
                max_tokens=2048,
                enable_web_search=True,
                search_limit=3,
            )
        except Exception as e:
            logger.error(f"获取原文失败 [{title}]: {e}")
            content_text = None

        usage_after = doubao.cumulative_usage.copy()
        this_call = usage_after["total_tokens"] - usage_before["total_tokens"]

        if content_text:
            rec["content"] = content_text.strip()
            print(f"   [OK] 原文获取成功 ({len(rec['content'])}字) | 本条token: {this_call}")
            print(f"   原文预览: {rec['content'][:120]}...")
        else:
            rec["content"] = ""
            print(f"   [FAIL] 获取失败 | 本条token: {this_call}")

    # 写回
    backup_path = json_path.replace(".json", "_backup.json")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)  # 先备份

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\n    已保存: {json_path} (备份: {backup_path})")
    return records


if __name__ == "__main__":
    excel_path = r"D:\网络部工作\新建文件夹\各个区县数据.xlsx"
    dashboard_path = r"data/dashboard_test.json"

    # 重置计数器（测试用）
    doubao.reset_cumulative_usage()

    # Step 1: 补充已有 3 条的 content
    supplement_content_for_existing(dashboard_path)

    # Step 2: 从 Excel 取 5 条新数据测试
    test_fresh_items(excel_path, n=5)

    # 最终汇总
    usage = doubao.cumulative_usage
    print("\n" + "=" * 60)
    print(" 全部完成")
    print(f"   总调用: {usage['call_count']}次")
    print(f"   总消耗: {usage['total_tokens']} tokens ({usage['total_tokens']/10000:.1f}万)")
    print(f"   预算剩余: {usage['budget_remaining']/10000:.1f}万")
    if usage['total_tokens'] > 0:
        avg = usage['total_tokens'] / usage['call_count']
        est_466 = avg * 466
        print(f"   平均每条: {avg:.0f} tokens")
        print(f"   466条估算: {est_466:.0f} tokens ({est_466/10000:.1f}万)")
    print("=" * 60)
