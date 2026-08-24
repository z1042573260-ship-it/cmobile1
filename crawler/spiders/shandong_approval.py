"""
山东省投资项目在线审批监管平台爬虫
----------------------------------
https://www.shandong.gov.cn/ 或专用审批平台
采集烟台地区的项目立项/核准/备案信息。
项目备案比施工招标早 1-6 个月。

爬取策略（v2 - 智能过滤）：
- 按区县关键词逐一搜索
- Layer 0: 流程公告预过滤
- Layer 1: 标题加权评分（审批类阈值低，因为是早期信号）
- Layer 2: 详情页内容分析
"""
from __future__ import annotations

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer


class ShandongApprovalSpider(BaseSpider):
    name = "shandong_approval"
    source_name = "山东省投资项目在线审批监管平台"

    # 山东省投资项目在线审批监管平台（实际URL需确认）
    BASE_URL = "https://tzxm.shandong.gov.cn/"
    SEARCH_URL = "https://tzxm.shandong.gov.cn/"

    # 审批类阈值更低 — 备案本身就是建设前兆信号
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
        """抓取详情页正文"""
        resp = self._get(url)
        if not resp:
            self.stats["details_failed"] += 1
            return ""

        soup = BeautifulSoup(resp.text, "lxml")

        for sel in ["div.txt-content", "div.article-con", "#zoom",
                     ".detail-content", ".content", ".TRS_Editor"]:
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

        # 烟台各区县关键词，逐一搜索
        yantai_keywords = [
            "烟台", "芝罘", "莱山", "福山", "牟平",
            "蓬莱", "龙口", "莱阳", "莱州", "招远", "栖霞", "海阳",
        ]

        seen_titles = set()  # 关键词搜索会有重复

        for keyword in yantai_keywords:
            try:
                resp = self._get(self.SEARCH_URL, params={
                    "keyword": keyword,
                    "type": "备案",
                })

                if not resp:
                    logger.debug(f"[{self.name}] 搜索 '{keyword}' 无响应")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                items = soup.select(".project-item, .list tr, .result-item, li")

                for item in items:
                    try:
                        title_el = item.select_one("a[href]")
                        if not title_el:
                            continue

                        title = title_el.get_text(strip=True)
                        if not title or len(title) < 4:
                            continue

                        link = title_el.get("href", "")
                        if link and not link.startswith("http"):
                            link = self.BASE_URL.rstrip("/") + "/" + link.lstrip("/")

                        date_el = item.select_one(".date, .time, span:last-child")
                        date = date_el.get_text(strip=True) if date_el else ""

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
                logger.error(f"[{self.name}] 搜索 '{keyword}' 异常: {e}")

        # 逐条获取详情（Layer 2 深度分析）
        logger.info(
            f"[{self.name}] 搜索 {len(yantai_keywords)} 个关键词, "
            f"发现 {self.stats['total_found']} 条(去重后), "
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
