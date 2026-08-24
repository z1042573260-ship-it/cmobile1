"""
烟台市生态环境局爬虫
--------------------
采集环境影响评价公示。
大项目必须做环评，环评公示是项目即将开工的强信号。

爬取策略（v2 - 智能过滤）：
- 环评 = 强信号，阈值较低（>=1即可纳入）
- Layer 0: 流程公告预过滤
- Layer 1: 标题加权评分
- Layer 2: 详情页内容分析（环评正文通常含详细工程信息）
"""
from __future__ import annotations

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer


class YantaiEPBSpider(BaseSpider):
    name = "yantai_epb"
    source_name = "烟台市生态环境局"

    # 烟台市生态环境局 - 环评公示
    # 注意: col23547 页面内容由 JS 动态加载，静态抓取只能拿到导航链接
    # 需要后续用 Selenium 或找到 JSON API 端点来获取真实列表
    BASE_URL = "https://hbj.yantai.gov.cn/"
    EIA_COL_URL = "https://hbj.yantai.gov.cn/col/col23547/index.html"

    # 环评是强信号，阈值低
    MIN_SCORE = 1

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
        """抓取详情页正文（环评正文通常很详细）"""
        resp = self._get(url)
        if not resp:
            self.stats["details_failed"] += 1
            return ""

        soup = BeautifulSoup(resp.text, "lxml")

        for sel in ["#zoom", ".content", ".article-content", ".TRS_Editor",
                     "div.txt-content", ".detail-content"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                self.stats["details_fetched"] += 1
                return text[:5000]  # 环评正文信息量大，多取一些

        body = soup.select_one("body")
        if body:
            self.stats["details_fetched"] += 1
            return body.get_text(strip=True)[:3000]

        self.stats["details_failed"] += 1
        return ""

    def crawl(self) -> list[dict]:
        results = []

        # 环评栏目（主栏目 col23547 = 环评公示）
        # 子栏目由 JS 动态加载，需要进一步调试
        columns = [
            ("环评公示", self.EIA_COL_URL),
        ]

        for col_name, url in columns:
            try:
                resp = self._get(url)
                if not resp:
                    logger.debug(f"[{self.name}] {col_name} 无响应")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                items = soup.select(".news-list li, .list-item, tr")

                for item in items:
                    try:
                        title_el = item.select_one("a[title], .title a, td a")
                        if not title_el:
                            continue

                        title = title_el.get_text(strip=True)
                        if not title or len(title) < 6:
                            continue

                        link = title_el.get("href", "")
                        if link and not link.startswith("http"):
                            link = self.BASE_URL.rstrip("/") + "/" + link.lstrip("/")

                        date_el = item.select_one(".date, .time")
                        date = date_el.get_text(strip=True) if date_el else ""

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
                    except Exception:
                        continue

                self._sleep()

            except Exception as e:
                logger.error(f"[{self.name}] 爬取 {col_name} 异常: {e}")

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
