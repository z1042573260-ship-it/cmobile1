"""
中国土地市场网爬虫
-----------------
https://www.landchina.com/
搜索烟台地区土地出让/成交公告 —— 最早的施工信号！
土地出让比施工招标早 3-12 个月。

爬取策略（v2 - 智能过滤）：
- 土地出让 = 最早的建设信号（土地拍下后必然建设）
- 阈值最低（>=0），因为土地出让本身就是建设前兆
- Layer 0: 流程公告预过滤
- Layer 1: 标题加权评分
- Layer 2: 详情页内容分析

注意: 此网站有 Cloudflare 防护，当前爬取受限。
"""
from __future__ import annotations

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer


class LandChinaSpider(BaseSpider):
    name = "landchina"
    source_name = "中国土地市场网"

    # 中国土地市场网 - 土地出让公告搜索
    SEARCH_URL = "https://www.landchina.com/"

    # 土地出让是最早的信号，阈值最低
    MIN_SCORE = 0

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

        for sel in ["div.txt-content", ".content", ".article-con", "#zoom"]:
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

        try:
            resp = self._get(self.SEARCH_URL)
            if not resp:
                logger.warning(f"[{self.name}] 首页请求失败（可能有Cloudflare防护）")
                return results

            soup = BeautifulSoup(resp.text, "lxml")
            items = soup.select(".result-list li, .list-item, tr[class]")

            for item in items:
                try:
                    title_el = item.select_one("a[title], .title a, td a")
                    date_el = item.select_one(".date, .time, td:last-child")

                    if not title_el:
                        continue

                    title = title_el.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue

                    link = title_el.get("href", "")
                    date = date_el.get_text(strip=True) if date_el else ""

                    # 过滤：只要标题或内容含"烟台"的
                    if "烟台" not in title:
                        continue

                    # 补全链接
                    if link and not link.startswith("http"):
                        link = "https://www.landchina.com" + link

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
                except Exception as e:
                    logger.debug(f"[{self.name}] 解析条目异常: {e}")
                    continue

            self._sleep()

        except Exception as e:
            logger.error(f"[{self.name}] 爬取异常: {e}")

        # 逐条获取详情（Layer 2 深度分析）
        logger.info(
            f"[{self.name}] 发现 {self.stats['total_found']} 条, "
            f"评分通过 {len(results)} 条 "
            f"(跳过: 流程{self.stats['skipped_process']} + "
            f"低分{self.stats['skipped_low_score']})"
        )

        for i, item in enumerate(results):
            if item["source_url"]:
                logger.debug(f"[{self.name}] [{i+1}/{len(results)}] 获取详情...")
                content = self._fetch_detail(item["source_url"])
                item["content"] = content

                if content:
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
