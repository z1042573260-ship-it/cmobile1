"""
乙方宝爬虫
---------
https://www.ybb.com/
聚合类招标信息平台，覆盖面广。
搜索"烟台"地区的招标信息。

爬取策略（v2 - 智能过滤）：
- Layer 0: 流程公告预过滤
- Layer 1: 标题加权评分
- Layer 2: 内容分析

注意: 此网站有反爬机制（403），当前爬取受限。
"""
from __future__ import annotations

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer


class YBBSpider(BaseSpider):
    name = "ybb"
    source_name = "乙方宝"

    BASE_URL = "https://www.ybb.com/"

    MIN_SCORE = 3

    def __init__(self):
        super().__init__()
        self.stats = {
            "total_found": 0,
            "skipped_process": 0,
            "skipped_low_score": 0,
            "details_fetched": 0,
            "details_failed": 0,
        }

    def _fetch_detail(self, url: str) -> str:
        """抓取详情页正文"""
        resp = self._get(url)
        if not resp:
            self.stats["details_failed"] += 1
            return ""

        soup = BeautifulSoup(resp.text, "lxml")

        for sel in ["div.txt-content", ".content", ".article-con",
                     "#zoom", ".detail-content"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                self.stats["details_fetched"] += 1
                return text[:3000]

        body = soup.select_one("body")
        if body:
            self.stats["details_fetched"] += 1
            return body.get_text(strip=True)[:2000]

        self.stats["details_failed"] += 1
        return ""

    def crawl(self) -> list[dict]:
        results = []

        search_urls = [
            f"{self.BASE_URL}search?keyword=烟台",
            f"{self.BASE_URL}search?keyword=烟台+施工",
            f"{self.BASE_URL}search?keyword=烟台+建设",
        ]

        seen_titles = set()

        for url in search_urls:
            try:
                resp = self._get(url)
                if not resp:
                    logger.debug(f"[{self.name}] 请求失败: {url}")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                items = soup.select(
                    ".search-result-item, .bid-item, "
                    ".list-item, .result-list li"
                )

                for item in items:
                    try:
                        title_el = item.select_one("a.title, a[href]")
                        if not title_el:
                            continue

                        title = title_el.get_text(strip=True)
                        if not title or len(title) < 6:
                            continue

                        link = title_el.get("href", "")
                        if link and not link.startswith("http"):
                            link = self.BASE_URL.rstrip("/") + "/" + link.lstrip("/")

                        date_el = item.select_one(".date, .time, .pub-date")
                        date = date_el.get_text(strip=True) if date_el else ""

                        # 摘要
                        summary_el = item.select_one(".summary, .desc, .abstract")
                        content = summary_el.get_text(strip=True) if summary_el else ""

                        # 去重
                        if title in seen_titles:
                            continue
                        seen_titles.add(title)

                        self.stats["total_found"] += 1

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

                        # ===== Layer 2 (预): 区县提取 =====
                        district = scorer._extract_district(title)

                        results.append({
                            "title": title,
                            "content": content,
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

                self._sleep()

            except Exception as e:
                logger.error(f"[{self.name}] 爬取 {url} 异常: {e}")

        # 逐条获取详情（Layer 2 深度分析）
        logger.info(
            f"[{self.name}] 搜索 {len(search_urls)} 个URL, "
            f"发现 {self.stats['total_found']} 条(去重后), "
            f"评分通过 {len(results)} 条 "
            f"(跳过: 流程{self.stats['skipped_process']} + "
            f"低分{self.stats['skipped_low_score']})"
        )

        for i, item in enumerate(results):
            if item["source_url"] and not item.get("content"):  # 仅有摘要的才去抓详情
                logger.debug(f"[{self.name}] [{i+1}/{len(results)}] 获取详情...")
                content = self._fetch_detail(item["source_url"])
                if content:
                    item["content"] = content

                    info = scorer.extract_content_info(content, item["title"])
                    item["scale_extracted"] = info.get("scale", "") or item["scale_extracted"]
                    item["investment_extracted"] = info.get("investment", "")
                    item["district_extracted"] = info.get("district", "") or item["district_extracted"]
                    item["project_nature"] = info.get("nature", "")

                self._sleep(0.5)

        logger.info(
            f"[{self.name}] 完成: {len(results)} 条 | "
            f"详情: {self.stats['details_fetched']}成功/{self.stats['details_failed']}失败 | "
            f"过滤: 流程{self.stats['skipped_process']}+"
            f"低分{self.stats['skipped_low_score']}"
        )

        return results
