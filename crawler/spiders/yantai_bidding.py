"""
烟台市公共资源交易网爬虫
-----------------------
https://ggzyjy.yantai.gov.cn/
采集工程建设招标公告 —— 最密集的施工信息来源。

爬取策略（v3 - API + 智能过滤）：
- 通过 Elasticsearch API 直接获取数据（比 HTML 解析更快更全）
- 筛选条件：最近一个月 / 招标公告 / 施工类
- Layer 0: categorynum=003001003（招标公告），过滤更正/废标/中标
- Layer 1: 标题加权评分
- Layer 2: 详情页内容分析（提取规模、区县、项目性质）
- 分页遍历所有结果（每次20条）

API 端点:
  POST /inteligentsearch/rest/esinteligentsearch/getFullTextDataNew
"""
from __future__ import annotations

import json
import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer


class YantaiBiddingSpider(BaseSpider):
    name = "yantai_bidding"
    source_name = "烟台市公共资源交易网"

    BASE_URL = "https://ggzyjy.yantai.gov.cn"
    API_URL = f"{BASE_URL}/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"

    # 评分阈值
    MIN_SCORE = 3

    # 每页条数（API 最大似乎支持20）
    PAGE_SIZE = 20

    # 搜索天数（最近N天）
    SEARCH_DAYS = 7          # 每周增量：只爬最近7天

    def __init__(self):
        super().__init__()
        self.stats = {
            "total_found": 0,         # API 返回总数
            "skipped_process": 0,     # 流程公告跳过
            "skipped_low_score": 0,   # 低分跳过
            "details_fetched": 0,     # 详情获取成功
            "details_failed": 0,      # 详情获取失败
            "pages_fetched": 0,       # API 翻页次数
        }

    def _build_api_params(self, page: int) -> dict:
        """构建 API 请求参数（与 transaction-list.js 的 getList 一致）"""
        today = datetime.date.today()
        end_date = today.strftime("%Y-%m-%d")
        start_date = self.get_cutoff_date().strftime("%Y-%m-%d")

        return {
            "token": "",
            "pn": page * self.PAGE_SIZE,
            "rn": self.PAGE_SIZE,
            "sdt": "",
            "edt": "",
            "wd": "",
            "inc_wd": "",
            "exc_wd": "",
            "fields": "",
            "cnum": "001",
            "sort": '{"webdate":"0","id":"0"}',
            "ssort": "",
            "cl": 200,
            "terminal": "",
            "condition": [
                {
                    "fieldName": "categorynum",
                    "equal": "003001003",      # 招标公告
                    "notEqual": None,
                    "equalList": None,
                    "notEqualList": None,
                    "isLike": True,
                    "likeType": 2,
                }
            ],
            "time": [
                {
                    "fieldName": "webdate",
                    "startTime": f"{start_date} 00:00:00",
                    "endTime": f"{end_date} 23:59:59",
                }
            ],
            "highlights": "",
            "statistics": None,
            "unionCondition": None,
            "accuracy": "",
            "noParticiple": "1",
            "searchRange": None,
            "noWd": True,
        }

    def _fetch_api_page(self, page: int) -> Optional[list]:
        """调用 API 获取一页数据"""
        params = self._build_api_params(page)

        resp = self._post(self.API_URL, json=params)
        if not resp:
            logger.error(f"[{self.name}] API 请求失败 (page={page})")
            return None

        try:
            outer = resp.json()
        except Exception:
            logger.error(f"[{self.name}] API JSON 解析失败 (page={page})")
            return None

        if outer.get("code") != 200:
            logger.error(f"[{self.name}] API 错误码: {outer.get('code')}")
            return None

        try:
            content = json.loads(outer["content"])
        except Exception:
            logger.error(f"[{self.name}] API content JSON 解析失败 (page={page})")
            return None

        records = content.get("result", {}).get("records", [])
        total = content.get("result", {}).get("totalcount", 0)
        return {"records": records, "total": total}

    def _build_detail_url(self, linkurl: str) -> str:
        """从相对路径构建详情页完整 URL"""
        if linkurl.startswith("http"):
            return linkurl
        return self.BASE_URL + linkurl

    def _fetch_detail(self, url: str) -> str:
        """抓取详情页正文"""
        resp = self._get(url)
        if not resp:
            self.stats["details_failed"] += 1
            return ""

        soup = BeautifulSoup(resp.text, "lxml")

        # 正文选择器（按优先级）
        for sel in ["div.txt-content", "div.com-detail-content",
                     "div.article-con", "#zoom", ".detail-content"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                self.stats["details_fetched"] += 1
                return text[:3000]

        # 回退：body 全文提取
        body = soup.select_one("body")
        if body:
            text = body.get_text(strip=True)
            start = text.find("招标条件")
            end = text.find("联系方式")
            if start >= 0:
                self.stats["details_fetched"] += 1
                return text[start:end+100][:3000]
            self.stats["details_fetched"] += 1
            return text[:2000]

        self.stats["details_failed"] += 1
        return ""

    def crawl(self) -> list[dict]:
        results = []
        seen_titles = set()

        # ===== 第一页：获取总数 =====
        page0 = self._fetch_api_page(0)
        if not page0:
            logger.error(f"[{self.name}] 无法获取首页数据，切换到旧版 HTML 模式")
            return self._crawl_legacy_html()

        total = page0["total"]
        total_pages = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        self.stats["total_found"] = total

        logger.info(
            f"[{self.name}] API 查询: SEARCH_DAYS={self.SEARCH_DAYS}, "
            f"START_DATE={self.START_DATE or '无'}, "
            f"招标公告共 {total} 条, 分 {total_pages} 页"
        )

        # ===== 处理所有页 =====
        all_raw = []

        for page_num in range(total_pages):
            if page_num == 0:
                page_data = page0
            else:
                page_data = self._fetch_api_page(page_num)
                if not page_data:
                    logger.warning(f"[{self.name}] 第{page_num}页获取失败，跳过")
                    continue

            self.stats["pages_fetched"] += 1

            for rec in page_data["records"]:
                title = rec.get("title", "").strip()
                if not title or len(title) < 6:
                    continue

                # 去重
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                linkurl = rec.get("linkurl", "")
                detail_url = self._build_detail_url(linkurl) if linkurl else ""
                webdate = rec.get("webdate", "")[:10]  # 只取日期部分
                xiaquname = rec.get("xiaquname", "")    # API 直接返回区县名
                zbtype = rec.get("zbtype", "")           # 施工/监理/勘察/设计
                categoryname = rec.get("categoryname", "")
                content_preview = rec.get("content", "")

                # ===== Layer 0: 流程公告预过滤 =====
                if scorer.is_process_announcement(title):
                    self.stats["skipped_process"] += 1
                    continue

                if scorer.is_result_announcement(title):
                    self.stats["skipped_process"] += 1
                    continue

                # ===== Layer 1: 标题加权评分 =====
                score, score_detail = scorer.score_title(title)

                if score < self.MIN_SCORE:
                    self.stats["skipped_low_score"] += 1
                    continue

                # 区县优先用 API 返回的 xiaquname
                district = xiaquname or scorer._extract_district(title)

                all_raw.append({
                    "title": title,
                    "content": "",
                    "content_preview": content_preview,
                    "source_url": detail_url,
                    "publish_date": webdate,
                    "relevance_score": score,
                    "score_detail": score_detail,
                    "district_extracted": district,
                    "scale_extracted": "",
                    "investment_extracted": "",
                    "project_nature": "",
                    # 额外元信息
                    "meta_zbtype": zbtype,
                    "meta_category": categoryname,
                })

        logger.info(
            f"[{self.name}] 评分通过 {len(all_raw)} 条 "
            f"(跳过: 流程{self.stats['skipped_process']} + "
            f"低分{self.stats['skipped_low_score']}) "
            f"| 共 {self.stats['pages_fetched']}/{total_pages} 页"
        )

        # ===== Layer 2: 逐条获取详情 =====
        for i, item in enumerate(all_raw):
            if item["source_url"]:
                logger.debug(f"[{self.name}] [{i+1}/{len(all_raw)}] 获取详情...")
                content = self._fetch_detail(item["source_url"])
                item["content"] = content

                # 如果有 content 用正文分析，否则用 API 预览
                analysis_text = content if content else item.get("content_preview", "")
                if analysis_text:
                    info = scorer.extract_content_info(analysis_text, item["title"])
                    item["scale_extracted"] = info.get("scale", "") or item["scale_extracted"]
                    item["investment_extracted"] = info.get("investment", "")
                    item["district_extracted"] = info.get("district", "") or item["district_extracted"]
                    item["project_nature"] = info.get("nature", "")

                self._sleep(0.5)

        logger.info(
            f"[{self.name}] 完成: {len(all_raw)} 条 | "
            f"详情: {self.stats['details_fetched']}成功/{self.stats['details_failed']}失败 | "
            f"过滤: 流程{self.stats['skipped_process']}+"
            f"低分{self.stats['skipped_low_score']}"
        )

        return all_raw

    def _crawl_legacy_html(self) -> list[dict]:
        """旧版 HTML 解析（API 不可用时的回退方案）"""
        results = []

        resp = self._get(self.BASE_URL + "/")
        if not resp:
            return results

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select("li.notice-item")

        for item in items:
            try:
                a_tag = item.select_one("a[href]")
                if not a_tag:
                    continue

                title = a_tag.get_text(strip=True)
                if not title or len(title) < 6:
                    continue

                # 提取日期
                match = re.search(r"(\d{4}-\d{2}-\d{2})\s*$", title)
                date = match.group(1) if match else ""
                if match:
                    title = title[: match.start()].strip()

                link = a_tag.get("href", "")
                if link and not link.startswith("http"):
                    link = self.BASE_URL + link

                if scorer.is_process_announcement(title):
                    continue
                if scorer.is_result_announcement(title):
                    continue

                score, score_detail = scorer.score_title(title)
                if score < self.MIN_SCORE:
                    continue

                district = scorer._extract_district(title)

                results.append({
                    "title": title,
                    "content": "",
                    "source_url": link,
                    "publish_date": date,
                    "relevance_score": score,
                    "score_detail": score_detail,
                    "district_extracted": district,
                    "scale_extracted": "",
                    "investment_extracted": "",
                    "project_nature": "",
                })
            except Exception:
                continue

        for item in results:
            if item["source_url"]:
                content = self._fetch_detail(item["source_url"])
                item["content"] = content
                if content:
                    info = scorer.extract_content_info(content, item["title"])
                    item["scale_extracted"] = info.get("scale", "") or item["scale_extracted"]
                    item["investment_extracted"] = info.get("investment", "")
                    item["district_extracted"] = info.get("district", "") or item["district_extracted"]
                    item["project_nature"] = info.get("nature", "")
                self._sleep(0.5)

        return results
