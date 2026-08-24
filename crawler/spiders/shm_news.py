"""
水母网爬虫 (烟台日报社)
-----------------------
https://www.shm.com.cn — 烟台地方新闻门户

爬取策略（v2 - 关联专栏深度覆盖）：
  1. 遍历 18 个相关 Node 列表页（分类栏目 + 区市动态），带分页翻页
  2. 首页补充采集（主首页 + 新闻中心首页），兜底覆盖
  3. 按日期过滤 → 超过 30 天停止翻页
  4. 逐条访问详情页，提取 <!--enpcontent--> 正文
  5. 提取 <!--enpproperty--> 结构化元数据
  6. RelevanceScorer Layer 0/1/2 智能评分过滤

专栏覆盖（只爬相关专栏，无关的不爬）：
  分类栏目: 烟台要闻(4151), 烟台经济(4153), 山东新闻(4818), 国内新闻(4155)
  区市动态: 开发区(5600), 芝罘区(5601), 福山区(5598), 莱山区(5599),
            牟平区(5855), 蓬莱区(5595), 龙口市(5276), 莱阳市(5597),
            海阳市(5602), 莱州市(5856), 栖霞市(5857), 招远市(5914),
            长岛试验区(5947), 昆嵛山(41068)

业务价值：
  水母网作为地方新闻门户，会报道重点工程、交通建设、城建项目等，
  可作为招标网和规划局的补充信号源（预判+舆情参考）。
"""
from __future__ import annotations

import re
import datetime
import json

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer


class ShmNewsSpider(BaseSpider):
    name = "shm_news"
    source_name = "水母网"

    BASE_URL = "https://www.shm.com.cn"
    NEWS_BASE = "http://news.shm.com.cn"

    # ---- 列表页配置 ----
    # Node 列表页（带分页翻页）
    # 只爬与工程建设相关的专栏，不爬社会/教卫/国际/汽车等无关栏目
    LIST_NODES = [
        # 分类栏目 — 基建/交通/产业项目高频出现
        f"{NEWS_BASE}/node_4151.htm",   # 烟台要闻
        f"{NEWS_BASE}/node_4153.htm",   # 烟台经济
        f"{NEWS_BASE}/node_4818.htm",   # 山东新闻
        f"{NEWS_BASE}/node_4155.htm",   # 国内新闻
        # 区市动态 — 各区县本地城建/市政项目
        f"{NEWS_BASE}/node_5600.htm",   # 开发区（工业园区/厂房密集）
        f"{NEWS_BASE}/node_5601.htm",   # 芝罘区（主城区城建）
        f"{NEWS_BASE}/node_5598.htm",   # 福山区
        f"{NEWS_BASE}/node_5599.htm",   # 莱山区
        f"{NEWS_BASE}/node_5855.htm",   # 牟平区
        f"{NEWS_BASE}/node_5595.htm",   # 蓬莱区
        f"{NEWS_BASE}/node_5276.htm",   # 龙口市
        f"{NEWS_BASE}/node_5597.htm",   # 莱阳市
        f"{NEWS_BASE}/node_5602.htm",   # 海阳市
        f"{NEWS_BASE}/node_5856.htm",   # 莱州市
        f"{NEWS_BASE}/node_5857.htm",   # 栖霞市
        f"{NEWS_BASE}/node_5914.htm",   # 招远市
        f"{NEWS_BASE}/node_5947.htm",   # 长岛试验区
        f"{NEWS_BASE}/node_41068.htm",  # 昆嵛山
    ]

    # 首页（最新头条，覆盖面广）
    HOMEPAGE_URLS = [
        f"{BASE_URL}/",                 # 水母网主首页（含多频道头条）
        f"{NEWS_BASE}/",               # 新闻中心首页
    ]

    # ---- 过滤配置 ----
    MIN_SCORE = 1        # 新闻信号弱，低阈值不过滤太狠
    SEARCH_DAYS = 7      # 每周增量：只爬最近7天

    def __init__(self):
        super().__init__()
        self.stats = {
            "list_pages": 0,             # 列表页翻页数
            "list_items": 0,            # 列表链接总数
            "skipped_old": 0,           # 过期跳过
            "skipped_process": 0,       # 流程公告跳过
            "skipped_low_score": 0,     # 低分跳过
            "details_fetched": 0,       # 详情获取成功
            "details_failed": 0,        # 详情获取失败
        }
        self._seen_urls = set()

    # ============================================================
    # 编码修复
    # ============================================================
    def _get_soup(self, url: str):
        """
        获取页面并返回 BeautifulSoup 对象。
        水母网 HTTP 头返回 ISO-8859-1，实际是 UTF-8，需要手动修正。
        """
        resp = self._get(url)
        if not resp:
            return None
        # 用 raw bytes 让 BeautifulSoup 自动检测编码
        return BeautifulSoup(resp.content, "lxml")

    # ============================================================
    # 列表页采集
    # ============================================================

    def _fetch_node_page(self, url: str) -> list[dict]:
        """
        访问一个 Node 列表页，提取所有文章链接和日期。

        返回: [{"title": "...", "url": "...", "date": "2026-07-22"}, ...]
        """
        soup = self._get_soup(url)
        if not soup:
            logger.warning(f"[{self.name}] 列表页请求失败: {url}")
            return []

        articles = []

        # 多种选择器适配不同页面布局：
        #   Node 列表页: div.cl_list h2 a
        #   主首页:     .main_list ul li a, .headline a, .news_frall a
        #   通用:      任意 a 标签包含 content_*.htm
        selectors = [
            "div.cl_list h2 a[href]",
            ".main_list a[href]",
            ".headline a[href]",
            ".news_frall a[href]",
            ".news_frall2 a[href]",
        ]

        found_links = set()
        for sel in selectors:
            for link in soup.select(sel):
                title = link.get_text(strip=True)
                # 清理零宽空格等不可见字符
                title = title.replace("​", "").replace("﻿", "")
                href = link.get("href", "").strip()

                if not title or not href:
                    continue

                # 收所有 shm.com.cn 子域名的文章链接
                if not self._is_shm_article_url(href):
                    continue

                url_full = self._build_url(href)

                # 用 URL 去重（当前页内）
                if url_full in found_links:
                    continue
                found_links.add(url_full)

                # 跨页面去重
                if url_full in self._seen_urls:
                    continue
                self._seen_urls.add(url_full)

                # 从 href 中提取日期（news.shm.com.cn/YYYY-MM/DD/）
                date = ""
                m = re.search(r'/(\d{4}-\d{2}/\d{2})/', href)
                if m:
                    date = m.group(1).replace("/", "-")

                # 尝试从父容器找更准确的日期
                parent = link.parent
                if parent:
                    # TRS WCM 列表页: div.cl_txt > em
                    txt_div = parent.find_next_sibling("div", class_="cl_txt")
                    if txt_div:
                        em = txt_div.find("em")
                        if em:
                            date = em.get_text(strip=True) or date
                    # 也可能是 p > em
                    next_p = parent.find_next_sibling("p")
                    if next_p:
                        em = next_p.find("em")
                        if em:
                            date = em.get_text(strip=True) or date

                articles.append({
                    "title": title,
                    "url": url_full,
                    "date": date,
                })

        return articles

    def _get_pagination_links(self, base_url: str, soup) -> list[str]:
        """
        从分页区域提取所有页码链接。

        TRS WCM 分页: div#autopage > a[href] → node_NNNNN_N.htm
        """
        page_urls = []
        autopage = soup.select_one("div#autopage")
        if not autopage:
            return page_urls

        for a in autopage.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue

            # 构造完整 URL
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = self.NEWS_BASE + href
            else:
                # 相对路径
                base_dir = base_url.rsplit("/", 1)[0]
                full_url = base_dir + "/" + href

            if full_url not in page_urls and full_url != base_url:
                page_urls.append(full_url)

        return page_urls

    # ============================================================
    # URL 处理
    # ============================================================

    def _build_url(self, path: str) -> str:
        """补全为完整 URL"""
        if path.startswith("http://"):
            path = path.replace("http://", "https://", 1)
        if not path.startswith("https://"):
            if path.startswith("//"):
                path = "https:" + path
            elif path.startswith("/"):
                path = self.BASE_URL.rstrip("/") + "/" + path.lstrip("/")
            else:
                path = self.NEWS_BASE.rstrip("/") + "/" + path.lstrip("/")
        return path

    def _is_shm_article_url(self, href: str) -> bool:
        """检查是否为水母网旗下的文章链接（支持所有子域名）"""
        return (
            "shm.com.cn" in href
            and re.search(r'/content_\d+\.htm', href)
        )

    # ============================================================
    # 详情页解析
    # ============================================================

    def _fetch_detail(self, url: str) -> dict:
        """
        抓取详情页，提取结构化信息。

        TRS WCM 详情页关键标记:
          <!--enpcontent-->...<!--/enpcontent-->  正文
          <!--enpproperty-->...<!--/enpproperty-->  元数据

        返回: {"content": "...", "publish_date": "...", "source": "...",
               "author": "...", "node_name": "..."}
        """
        resp = self._get(url)
        if not resp:
            self.stats["details_failed"] += 1
            return {"content": "", "error": "请求失败"}

        # 修正编码：HTTP 头返回 ISO-8859-1，实际是 UTF-8
        html = resp.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(resp.content, "lxml")

        self.stats["details_fetched"] += 1

        result = {
            "content": "",
            "page_title": "",
            "publish_date": "",
            "source": "",
            "author": "",
            "node_name": "",
        }

        # 页面标题
        title_tag = soup.select_one("title")
        if title_tag:
            page_title = title_tag.get_text(strip=True)
            # 去除后缀 "-水母网" / "-烟台社会-水母网" 等
            page_title = re.sub(r'[-–—]\s*水母网\s*$', '', page_title)
            page_title = re.sub(r'[-–—]\s*烟台.*?水母网\s*$', '', page_title)
            result["page_title"] = page_title.strip()

        # ---- 正文提取: <!--enpcontent--> 标记 ----
        enp_m = re.search(
            r'<!--enpcontent-->(.*?)<!--/enpcontent-->',
            html, re.DOTALL
        )
        if enp_m:
            content_html = enp_m.group(1)
            content_soup = BeautifulSoup(content_html, "lxml")
            content = content_soup.get_text(separator="\n", strip=True)
            result["content"] = content[:5000]
        else:
            # 回退: class="ml_zy" 内容容器
            for sel in ["div.ml_zy", "div.contentFiles", "div.article-content",
                        "#zoom", "div.pages_content", "div.TRS_Editor"]:
                el = soup.select_one(sel)
                if el:
                    result["content"] = el.get_text(separator="\n", strip=True)[:5000]
                    break

            # 最终回退: body 全文
            if not result["content"]:
                body = soup.select_one("body")
                if body:
                    result["content"] = body.get_text(strip=True)[:3000]

        # ---- 元数据提取: <!--enpproperty--> 标记 ----
        enp_prop = re.search(
            r'<!--enpproperty\s+(.*?)\s*/enpproperty-->',
            html, re.DOTALL
        )
        if enp_prop:
            prop_text = enp_prop.group(1)
            # 提取 date
            m = re.search(r'date="([^"]+)"', prop_text)
            if m:
                result["publish_date"] = m.group(1)[:10]  # YYYY-MM-DD
            # 提取 sourcename
            m = re.search(r'sourcename="([^"]+)"', prop_text)
            if m:
                result["source"] = m.group(1)
            # 提取 author
            m = re.search(r'author="([^"]+)"', prop_text)
            if m:
                result["author"] = m.group(1)
            # 提取 nodename
            m = re.search(r'nodename="([^"]+)"', prop_text)
            if m:
                result["node_name"] = m.group(1)

        # ---- 备用: 从页面 HTML 提取日期 ----
        if not result["publish_date"]:
            m = re.search(
                r'id="pubtime_baidu"[^>]*>\s*(\d{4}-\d{2}-\d{2})',
                html
            )
            if m:
                result["publish_date"] = m.group(1)

        # ---- 备用: 从 URL 路径提取日期 ----
        if not result["publish_date"]:
            m = re.search(r'/(\d{4}-\d{2}/\d{2})/', url)
            if m:
                result["publish_date"] = m.group(1).replace("/", "-")

        return result

    # ============================================================
    # 主爬取逻辑
    # ============================================================

    def crawl(self) -> list[dict]:
        results = []
        cutoff_date = self.get_cutoff_date()

        # ---- Phase 1: 遍历 Node 列表页 ----
        logger.info(
            f"[{self.name}] 开始获取列表"
            f"（SEARCH_DAYS={self.SEARCH_DAYS}, START_DATE={self.START_DATE or '无'}, "
            f"截止={cutoff_date}）..."
        )

        all_items = []

        # 1a. Node 列表页（带分页）
        for node_url in self.LIST_NODES:
            logger.info(f"[{self.name}] 采集节点: {node_url}")
            page_urls_to_fetch = [node_url]  # 待抓取的列表页 URL 队列

            while page_urls_to_fetch:
                page_url = page_urls_to_fetch.pop(0)
                self.stats["list_pages"] += 1

                soup = self._get_soup(page_url)
                if not soup:
                    continue

                # 提取当前页的文章链接
                articles = self._fetch_node_page(page_url)
                all_items.extend(articles)

                # 检查分页（第一页时才需要发现更多页面）
                if page_url == node_url:
                    more_pages = self._get_pagination_links(page_url, soup)
                    page_urls_to_fetch.extend(more_pages)
                    if more_pages:
                        logger.debug(
                            f"[{self.name}] 发现 {len(more_pages)} 个分页"
                        )

                self._sleep(0.3)

        # 1b. 首页补充（只抓第一页，不用翻页）
        for homepage_url in self.HOMEPAGE_URLS:
            logger.info(f"[{self.name}] 采集首页: {homepage_url}")
            articles = self._fetch_node_page(homepage_url)
            all_items.extend(articles)
            self._sleep(0.5)

        # 去重
        seen = set()
        unique_items = []
        for item in all_items:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique_items.append(item)
        all_items = unique_items

        self.stats["list_items"] = len(all_items)
        logger.info(
            f"[{self.name}] 列表获取完成: {len(all_items)} 条 "
            f"(翻页{self.stats['list_pages']}次)"
        )

        # ---- Phase 2: 逐条过滤 + 详情 ----
        logger.info(f"[{self.name}] 开始逐条处理...")

        for i, item in enumerate(all_items):
            title = item["title"]
            url = item["url"]
            date_str = item.get("date", "")

            # ---- 日期过滤 ----
            if date_str:
                try:
                    art_date = datetime.datetime.strptime(
                        date_str, "%Y-%m-%d"
                    ).date()
                    if art_date < cutoff_date:
                        self.stats["skipped_old"] += 1
                        continue
                except ValueError:
                    pass

            # ---- Layer 0: 流程公告预过滤 ----
            if scorer.is_process_announcement(title):
                self.stats["skipped_process"] += 1
                continue
            if scorer.is_result_announcement(title):
                self.stats["skipped_process"] += 1
                continue

            # ---- Layer 1: 标题评分 ----
            score, score_detail = scorer.score_title(title)

            # 新闻类额外加分：基建/交通/城建关键词在新闻报道中常见
            news_bonus = 0
            _news_kw = [
                "重点工程", "城建", "城建重点", "城市更新", "海绵城市",
                "雨污分流", "老旧小区改造", "路网", "市政道路",
                "安置区", "棚改", "旧村改造", "安置房建设",
                "立交", "互通立交", "快速路", "主干道",
                "公交场站", "停车场", "充电桩", "换电站",
                "供热管网", "供水管网", "供气管网", "电力管廊",
                "污水处理厂", "垃圾处理", "环卫设施",
                "海岸线整治", "河道治理", "防潮堤",
                "人才公寓", "保障性住房", "公租房",
                "标准化厂房", "通用厂房", "产业载体",
                "输变电", "变电站", "电力线路",
                "5G基站", "通信基站", "通信管道",
            ]
            for kw in _news_kw:
                if kw in title:
                    news_bonus += 2
                    break  # 只加一次，避免一个标题命中多个
            score += news_bonus
            score_detail["news_bonus"] = news_bonus

            if score < self.MIN_SCORE:
                self.stats["skipped_low_score"] += 1
                continue

            # ---- 新闻误判过滤：纯财经/医保/消费类文章含"亿元"导致假阳性 ----
            _finance_kw = ["外贸进出口", "GDP", "民营企业", "再贷款", "医保基金",
                          "同比增长", "消费品", "零售", "销售额", "保费", "贷款",
                          "信用卡", "理财", "存款", "基金份额", "A股", "股市"]
            _has_finance = any(kw in title for kw in _finance_kw)
            _has_construct_kw = bool(score_detail.get("positive"))  # 有建设类关键词
            if _has_finance and not _has_construct_kw:
                self.stats["skipped_low_score"] += 1
                continue

            # 区县预提取
            district = scorer._extract_district(title)

            # ---- 获取详情 ----
            logger.debug(f"[{self.name}] [{i+1}/{len(all_items)}] {title[:60]}...")

            detail = self._fetch_detail(url)
            content = detail.get("content", "")

            # 用详情页的日期覆盖列表页的日期（更准确）
            if detail.get("publish_date"):
                date_str = detail["publish_date"]
                try:
                    art_date = datetime.datetime.strptime(
                        date_str, "%Y-%m-%d"
                    ).date()
                    if art_date < cutoff_date:
                        self.stats["skipped_old"] += 1
                        continue
                except ValueError:
                    pass

            # ---- Layer 2: 内容深度分析 ----
            scale_extracted = ""
            investment_extracted = ""
            nature_extracted = ""

            if content:
                info = scorer.extract_content_info(content, title)
                scale_extracted = info.get("scale", "")
                investment_extracted = info.get("investment", "")
                nature_extracted = info.get("nature", "")

            # 从页面元数据补充来源
            meta_source = detail.get("source", "")
            meta_node = detail.get("node_name", "")

            # ---- 组装结果 ----
            results.append({
                "title": title,
                "content": content,
                "source_url": url,
                "publish_date": date_str,
                "relevance_score": score,
                "score_detail": score_detail,
                "district_extracted": district,
                "scale_extracted": scale_extracted,
                "investment_extracted": investment_extracted,
                "project_nature": nature_extracted,
                # 水母网特有字段
                "meta_source": meta_source,
                "meta_node": meta_node,
            })

            self._sleep(0.3)

        # ---- 质量分布统计 ----
        high = sum(1 for r in results if r["relevance_score"] >= 5)
        mid = sum(1 for r in results if 3 <= r["relevance_score"] < 5)
        low = sum(1 for r in results if 0 < r["relevance_score"] < 3)

        logger.info(
            f"[{self.name}] 完成: {len(results)} 条 "
            f"(高{high}/中{mid}/低{low}) | "
            f"详情: {self.stats['details_fetched']}成功/"
            f"{self.stats['details_failed']}失败 | "
            f"过滤: 流程{self.stats['skipped_process']}+"
            f"低分{self.stats['skipped_low_score']}+"
            f"过期{self.stats['skipped_old']}"
        )

        return results
