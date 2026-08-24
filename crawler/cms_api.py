"""
大汉JCMS/JPAAS 政府CMS API 客户端
--------------------------------
封装 /api-gateway/jpaas-publish-server/front/page/build/unit 的调用逻辑，
供 yantai_districts, yantai_planning, yantai_investment 三个爬虫共用。

消除以下重复代码：
  1. API 参数构建
  2. JSON 响应解析（{success: true, data: {html: "..."}}）
  3. 分页总数提取（div.pagination[count]）
  4. 详情页正文提取（多个选择器 + fallback）
"""
from __future__ import annotations

import json
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup


def fetch_cms_list(
    session: requests.Session,
    base_url: str,
    web_id: str,
    tpl_set_id: str,
    tag_id: str,
    col_id: str,
    page_no: int,
    page_size: int = 30,
    extra_headers: dict | None = None,
) -> tuple[str, int]:
    """
    调用大汉JCMS CMS API 获取一页文章列表HTML。

    参数:
        session: requests.Session
        base_url: 站点根URL (如 https://www.longkou.gov.cn)
        web_id, tpl_set_id, tag_id, col_id: CMS API 参数
        page_no: 页码
        page_size: 每页条数
        extra_headers: 额外请求头

    返回:
        (html, total) — html 为列表HTML片段，total 为总文章数
    """
    api_url = base_url.rstrip("/") + "/api-gateway/jpaas-publish-server/front/page/build/unit"
    params = {
        "parseType": "bulidstatic",
        "webId": web_id,
        "tplSetId": tpl_set_id,
        "pageType": "column",
        "tagId": tag_id,
        "editType": "null",
        "pageId": col_id,
        "paramJson": json.dumps({
            "pageNo": page_no,
            "pageSize": page_size,
        }),
    }

    headers = {"X-Requested-With": "XMLHttpRequest"}
    if extra_headers:
        headers.update(extra_headers)

    # 重试（自动化可靠性）：政务服务器偶发限流/强制断开（ConnectionResetError），
    # 指数退避重试 3 次，避免静默漏抓
    max_retries = 3
    resp = None
    for attempt in range(max_retries):
        try:
            resp = session.get(api_url, params=params, headers=headers, timeout=30)
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)   # 1s, 2s
                continue
            raise
    if not resp:
        return "", 0

    try:
        outer = resp.json()
    except Exception:
        return "", 0

    if not outer.get("success"):
        return "", 0

    html = outer.get("data", {}).get("html", "")
    if not html:
        return "", 0

    # 从 pagination div 提取总数
    total = 0
    soup = BeautifulSoup(html, "lxml")
    pagination = soup.select_one("div.pagination")
    if pagination:
        try:
            total = int(pagination.get("count", "0"))
        except ValueError:
            pass

    return html, total


# 详情页正文选择器（按优先级排列，所有站点共用）
DETAIL_CONTENT_SELECTORS = [
    "#zoom",
    "div.pages_content",
    "div.TRS_Editor",
    ".article-content",
    ".content",
    "#UCAP-CONTENT",
    "div.txt-content",
    "div.article-con",
    "div.news-content",
    "div.article_con",
    "div.detail-content",
]


def extract_detail_content(soup: BeautifulSoup, max_chars: int = 5000) -> str:
    """
    从详情页 BeautifulSoup 中提取正文内容。

    按优先级尝试多个 CSS 选择器，失败时回退到 body 文本。
    """
    for sel in DETAIL_CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            content = el.get_text(separator="\n", strip=True)
            if content:
                return content[:max_chars]

    # 兜底：取 body
    body = soup.select_one("body")
    if body:
        return body.get_text(strip=True)[:3000]

    return ""


def extract_detail_date(soup: BeautifulSoup, content: str = "",
                        page_title: str = "") -> str:
    """
    从详情页提取发布日期。

    先尝试 CSS 选择器，再用正则兜底。
    容忍龙口等站点的换行符分割日期（2026-\n07-\n23）。
    """
    import re
    import datetime

    # CSS 选择器
    for sel in ["span.time", "span.pub_time", "span.info-time", ".article-info span"]:
        el = soup.select_one(sel)
        if el:
            text = re.sub(r'\s+', '', el.get_text(strip=True))
            m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", text)
            if m:
                return m.group(1)

    # 正则兜底
    date_patterns = [
        r"发布日期[：:]\s*(\d{4}[-/]\d{2}[-/]\d{2})",
        r"发布时间[：:]\s*(\d{4}[-/]\d{2}[-/]\d{2})",
        r"时间[：:]\s*(\d{4}[-/]\d{2}[-/]\d{2})",
        r"日期[：:]\s*(\d{4}[-/]\d{2}[-/]\d{2})",
        r"(\d{4}[-/]\d{2}[-/]\d{2})\s*\d{2}:\d{2}",
    ]
    text_to_search = re.sub(r'\s+', '', content + page_title)
    for pat in date_patterns:
        m = re.search(pat, text_to_search)
        if m:
            return m.group(1)

    return ""
