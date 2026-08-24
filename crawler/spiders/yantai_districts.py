"""
烟台13区县政府公告爬虫
--------------------
统一爬取13个区县政府门户网站的公告信息。
所有站点使用大汉JCMS/JPAAS政府CMS，通过统一API获取列表。

爬取策略：
  1. 13个区县按顺序逐个爬取（避免并发反爬）
  2. 各区县调用 CMS API 分页获取文章列表
  3. 列表阶段即过滤"不动产"相关关键词
  4. 按发布日期（2026-05-01截止）停止翻页
  5. 逐条获取详情页，提取结构化信息
  6. 使用 RelevanceScorer 进行 Layer 0/1/2 评分

HTML结构变体（列表项）：
  Variant A (Laizhou): li.bt-main-r-ul-li > a[href] + span
  Variant B (Muping/Zhifu/...): li > a[href] + span (无ul包裹)
  Variant C (Haiyang): li > span.bt-prefix + a[href] + span.bt-data-time
  Variant D (Longkou): li > a[href][title] only (无日期span!)

特殊处理：
  - 龙口市：列表无日期，需访问详情页获取日期后再判断是否过期
  - 栖霞市/开发区：URL带query参数
"""
from __future__ import annotations

import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer
from crawler.cms_api import (
    fetch_cms_list, extract_detail_content, extract_detail_date,
)


class YantaiDistrictsSpider(BaseSpider):
    name = "yantai_districts"
    source_name = "烟台13区县政府公告"

    # ---- CMS API 固定参数 ----
    API_PATH = "/api-gateway/jpaas-publish-server/front/page/build/unit"
    PAGE_SIZE = 30
    PAGE_TYPE = "column"
    EDIT_TYPE = "null"

    # ---- 过滤配置 ----
    MIN_SCORE = 1            # 政府公告词汇与招标不同，低阈值
    SEARCH_DAYS = 7          # 每周增量：只爬最近7天（首次全量时设 START_DATE 绝对起点）
    START_DATE = ""          # 首次全量起点，如 "2026-05-01"；自动化增量模式置空
    END_DATE = None          # 最晚日期（None=不限制；如 "2026-08-13" 只抓到该日）

    # ---- 请求控制 ----
    LIST_PAGE_INTERVAL = 0.3    # 列表页间休息
    DETAIL_INTERVAL = 0.5       # 详情页间休息
    DISTRICT_INTERVAL = 2.0     # 区县间休息

    # ---- 不动产过滤关键词 ----
    REAL_ESTATE_KW = [
        "不动产", "房产", "房屋所有权", "不动产权", "房地",
        "首次登记", "转移登记", "变更登记", "注销登记",
        "登记公告", "登记公示", "权利人不明",
    ]

    # ---- 13 区县配置 ----
    # webId, tplSetId 已通过分析各站点HTML确认
    DISTRICT_CONFIG = {
        "longkou": {
            "name_cn": "龙口市",
            "base_url": "https://www.longkou.gov.cn",
            "col": "15019",
            "web_id": "153",
            "tpl_set_id": "U1S5IC8QNYd71CkF9ENIL",
            "tag_id": "右侧列表",
            "list_variant": "D",      # 无日期
            "date_in_list": False,
            "url_extra": "",
        },
        "haiyang": {
            "name_cn": "海阳市",
            "base_url": "https://www.haiyang.gov.cn",
            "col": "14046",
            "web_id": "158",
            "tpl_set_id": "A202XXROMYuFXyLH9Epbn",
            "tag_id": "右侧列表",
            "list_variant": "C",
            "date_in_list": True,
            "url_extra": "",
        },
        "fushan": {
            "name_cn": "福山区",
            "base_url": "https://www.ytfushan.gov.cn",
            "col": "15955",
            "web_id": "148",
            "tpl_set_id": "FkT6xljcB7CqYjedWPMTZ",
            "tag_id": "栏目信息列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
        "muping": {
            "name_cn": "牟平区",
            "base_url": "https://www.muping.gov.cn",
            "col": "13058",
            "web_id": "149",
            "tpl_set_id": "QJQ18GsL67Dutf4OTidwX",
            "tag_id": "当前栏目列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
        "laiyang": {
            "name_cn": "莱阳市",
            "base_url": "https://www.laiyang.gov.cn",
            "col": "43630",
            "web_id": "162",
            "tpl_set_id": "dNL352FK70O2rT296SQOw",
            "tag_id": "当前栏目列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
        "zhifu": {
            "name_cn": "芝罘区",
            "base_url": "https://www.zhifu.gov.cn",
            "col": "15596",
            "web_id": "146",
            "tpl_set_id": "5nQ4hhWpoxamxGVn3ny84",
            "tag_id": "分页列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
        "laishan": {
            "name_cn": "莱山区",
            "base_url": "https://www.ytlaishan.gov.cn",
            "col": "23163",
            "web_id": "147",
            "tpl_set_id": "F8YZY5tPMIoerzpBFLjno",
            "tag_id": "通知list",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
        "qixia": {
            "name_cn": "栖霞市",
            "base_url": "https://www.sdqixia.gov.cn",
            "col": "31313",
            "web_id": "156",
            "tpl_set_id": "9PoOaKYCR68JNEP175LR3",
            "tag_id": "列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "?vc_xxgkarea=113706860042344370A&number=QXC10",
        },
        "gaoxin": {
            "name_cn": "高新区",
            "base_url": "https://www.ytgxq.gov.cn",
            "col": "21341",
            "web_id": "151",
            "tpl_set_id": "ktvoXqeQYVFDAMWTQ0EO1",
            "tag_id": "首页列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
        "yeda": {
            "name_cn": "开发区(黄渤海新区)",
            "base_url": "https://www.yeda.gov.cn",
            "col": "50127",
            "web_id": "140",
            "tpl_set_id": "FhvjvaxoOZi0km37YAMrK",
            "tag_id": "当前栏目列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "?vc_xxgkarea=113706000042580096&number=KFC03&jh=263",
        },
        "zhaoyuan": {
            "name_cn": "招远市",
            "base_url": "https://www.zhaoyuan.gov.cn",
            "col": "16751",
            "web_id": "155",
            "tpl_set_id": "sW4TqQJo1K65B01yzYBRg",
            "tag_id": "右侧文章列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
        "laizhou": {
            "name_cn": "莱州市",
            "base_url": "https://www.laizhou.gov.cn",
            "col": "23203",
            "web_id": "154",
            "tpl_set_id": "kUVXvNhbixMZJJ7baLQ9I",
            "tag_id": "右侧文章列表",
            "list_variant": "A",
            "date_in_list": True,
            "url_extra": "",
        },
        "penglai": {
            "name_cn": "蓬莱区",
            "base_url": "https://www.penglai.gov.cn",
            "col": "13634",
            "web_id": "152",
            "tpl_set_id": "awU93spIZ5G7CYnk12KGt",
            "tag_id": "当前栏目列表",
            "list_variant": "B",
            "date_in_list": True,
            "url_extra": "",
        },
    }

    # 爬取顺序（龙口放最后，因为无日期最耗时）
    CRAWL_ORDER = [
        "haiyang", "fushan", "muping", "laiyang", "zhifu", "laishan",
        "qixia", "gaoxin", "yeda", "zhaoyuan", "laizhou", "penglai",
        "longkou",
    ]

    def __init__(self, target_districts: list[str] | None = None):
        super().__init__()
        self.target_districts = target_districts  # None=全部
        # 全局统计
        self.stats = {
            "districts_total": 0,
            "districts_completed": 0,
            "districts_failed": 0,
            "total_list_items": 0,
            "total_details_fetched": 0,
            "total_details_failed": 0,
            "total_results": 0,
        }
        # 各区县统计
        self.district_stats: dict[str, dict] = {}

    # ============================================================
    # 工具方法
    # ============================================================

    # _build_url 继承自 BaseSpider，无需覆写

    def _col_url(self, cfg: dict) -> str:
        """构建栏目页面URL"""
        extra = cfg.get("url_extra", "")
        return f"{cfg['base_url']}/col/col{cfg['col']}/index.html{extra}"

    # _parse_date 继承自 BaseSpider，无需覆写

    def _normalize_date(self, date_str: str) -> str:
        """标准化日期为 YYYY-MM-DD 格式"""
        d = self._parse_date(date_str)
        return d.strftime("%Y-%m-%d") if d else date_str.strip("[]（）() ")

    def _is_real_estate(self, title: str) -> bool:
        """检查是否为不动产登记类公告"""
        return any(kw in title for kw in self.REAL_ESTATE_KW)

    # ============================================================
    # CMS 列表 API
    # ============================================================

    def _repair_cms_params(self, cfg: dict) -> bool:
        """
        参数自校验（自动化可靠性）：CMS API 参数失效（网站改版导致 webId/tplSetId/tagId 变化）时，
        自动从栏目页 JS 的 queryData 提取最新参数并更新 cfg，返回是否更新成功。
        """
        try:
            url = f"{cfg['base_url']}/col/col{cfg['col']}/index.html"
            resp = self._get(url, timeout=20)
            if not resp:
                return False
            m = re.search(
                r"queryData=\"\{[^}]*'webId':'(\d+)'[^}]*'tplSetId':'([^']+)'[^}]*'tagId':'([^']+)'",
                resp.text,
            )
            if not m:
                # 属性顺序可能不同，宽松匹配
                m = re.search(r"'webId':'(\d+)'.*?'tplSetId':'([^']+)'.*?'tagId':'([^']+)'", resp.text)
            if not m:
                return False
            web, tpl, tag = m.group(1), m.group(2), m.group(3)
            changed = False
            if tpl != cfg.get("tpl_set_id"):
                cfg["tpl_set_id"] = tpl
                changed = True
            if web != cfg.get("web_id"):
                cfg["web_id"] = web
                changed = True
            if tag != cfg.get("tag_id"):
                cfg["tag_id"] = tag
                changed = True
            if changed:
                cfg.pop("_effective_tag_id", None)   # 参数变了，旧 tagId 缓存作废
                logger.warning(
                    f"[{self.name}][{cfg['name_cn']}] CMS 参数已自动更新: "
                    f"webId={web} tplSetId={tpl} tagId={tag}"
                )
            return changed
        except Exception as e:
            logger.warning(f"[{self.name}][{cfg['name_cn']}] 参数自校验失败: {e}")
            return False

    def _fetch_list_page(
        self, cfg: dict, page_no: int
    ) -> tuple[list[dict], int]:
        """
        调用 CMS API 获取一页文章列表。

        返回: (articles, total_count)
        """
        col_url = self._col_url(cfg)

        def _do_fetch(tag_id: str) -> tuple[str, int]:
            """调用共享的 CMS API 客户端"""
            return fetch_cms_list(
                session=self.session,
                base_url=cfg["base_url"],
                web_id=cfg["web_id"],
                tpl_set_id=cfg["tpl_set_id"],
                tag_id=tag_id,
                col_id=cfg["col"],
                page_no=page_no,
                page_size=self.PAGE_SIZE,
                extra_headers={"Referer": col_url},
            )

        # 缓存有效的 tagId：首页探测后记住结果，后续页面直接用
        effective_tag = cfg.get("_effective_tag_id")
        if effective_tag is not None:
            html, total = _do_fetch(effective_tag)
        else:
            html, total = _do_fetch(cfg["tag_id"])

            # 某些站点 tagId 不匹配会导致返回空内容，自动回退到空 tagId
            if (not html or len(html) < 50 or "模板内容数据为空" in html):
                logger.info(
                    f"[{self.name}][{cfg['name_cn']}] "
                    f"tagId='{cfg['tag_id']}' 返回空，后续使用空 tagId"
                )
                cfg["_effective_tag_id"] = ""
                html, total = _do_fetch("")

            # 首页成功则缓存原 tagId
            if html and cfg.get("_effective_tag_id") is None:
                cfg["_effective_tag_id"] = cfg["tag_id"]

        if not html:
            # 自动化可靠性：API 失败（参数失效/改版）→ 自动从栏目页 JS 提取最新参数并重试一次
            if page_no == 1 and self._repair_cms_params(cfg):
                logger.warning(
                    f"[{self.name}][{cfg['name_cn']}] 参数已修复，重试第 {page_no} 页"
                )
                html, total = _do_fetch(cfg.get("_effective_tag_id", cfg["tag_id"]))
                if html:
                    cfg["_effective_tag_id"] = cfg["tag_id"]
            if not html:
                if effective_tag is not None or cfg.get("_effective_tag_id") is not None:
                    logger.error(
                        f"[{self.name}][{cfg['name_cn']}] "
                        f"API 请求失败 (page={page_no})"
                    )
                return [], 0

        articles = self._parse_list_html(html, cfg)
        return articles, total

    # ============================================================
    # 列表 HTML 解析（按变体分发）
    # ============================================================

    def _parse_list_html(self, html: str, cfg: dict) -> list[dict]:
        """根据变体类型分发解析"""
        variant = cfg.get("list_variant", "B")
        soup = BeautifulSoup(html, "lxml")

        if variant == "A":
            return self._parse_variant_a(soup, cfg)
        elif variant == "C":
            return self._parse_variant_c(soup, cfg)
        elif variant == "D":
            return self._parse_variant_d(soup, cfg)
        else:
            return self._parse_variant_b(soup, cfg)

    def _parse_variant_a(self, soup: BeautifulSoup, cfg: dict) -> list[dict]:
        """
        Laizhou: li.bt-main-r-ul-li > a[href][title] + span
        """
        articles = []
        for li in soup.select("li.bt-main-r-ul-li"):
            a_tag = li.select_one("a[href]")
            if not a_tag:
                continue
            title = (a_tag.get("title") or a_tag.get_text()).strip()
            href = a_tag.get("href", "").strip()
            if not title or not href:
                continue
            if f"col{cfg['col']}" not in href:
                continue
            span = li.select_one("span")
            date = span.get_text(strip=True) if span else ""
            articles.append({"title": title, "url": href, "date": date})
        return articles

    def _parse_variant_b(self, soup: BeautifulSoup, cfg: dict) -> list[dict]:
        """
        Muping/Zhifu/多数网站: li > a[href] + span (no ul wrapper)
        """
        articles = []
        for li in soup.select("li"):
            a_tag = li.select_one("a[href]")
            if not a_tag:
                continue
            title = (a_tag.get("title") or a_tag.get_text()).strip()
            # 清理 title 中的 <br/> 标签
            title = re.sub(r"<br\s*/?\s*>", " ", title) if "<br" in title else title
            href = a_tag.get("href", "").strip()
            if not title or not href:
                continue
            # 文章 URL 模式匹配（修复 2026-08-20：福山文章 URL 是 /col/col13662/art/…，
            # 与列表 col15955 不一致，旧逻辑 f"col{cfg['col']}" 把所有文章过滤成 0 条）
            if not re.search(r"/col/col\d+/art/", href):
                continue
            # 查找日期 span（跳过 bt-prefix 等特殊 span）
            date = ""
            for sp in li.select("span"):
                sp_class = " ".join(sp.get("class", []))
                sp_text = sp.get_text(strip=True)
                if "bt-prefix" in sp_class or "bt-icon" in sp_class:
                    continue
                if re.match(r"[\d\[\]/\-]{8,12}", sp_text):
                    date = sp_text
                    break
                # 也可以匹配 YYYY-MM-DD
                if re.match(r"\d{4}[-/]\d{2}[-/]\d{2}", sp_text):
                    date = sp_text
                    break
            if not date:
                # fallback: 取最后一个 span 的文字
                spans = li.select("span")
                if spans:
                    last_text = spans[-1].get_text(strip=True)
                    if re.search(r"\d{4}", last_text):
                        date = last_text
            articles.append({"title": title, "url": href, "date": date})
        return articles

    def _parse_variant_c(self, soup: BeautifulSoup, cfg: dict) -> list[dict]:
        """
        Haiyang: li > span.bt-prefix + a[href] + span.bt-data-time
        日期格式：[YYYY-MM-DD]
        """
        articles = []
        for li in soup.select("li"):
            a_tag = li.select_one("a[href]")
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href = a_tag.get("href", "").strip()
            if not title or not href:
                continue
            if f"col{cfg['col']}" not in href:
                continue
            date_span = li.select_one("span.bt-data-time")
            date = date_span.get_text(strip=True) if date_span else ""
            articles.append({"title": title, "url": href, "date": date})
        return articles

    def _parse_variant_d(self, soup: BeautifulSoup, cfg: dict) -> list[dict]:
        """
        Longkou: li > a[href][title] only (无日期span)
        """
        articles = []
        for li in soup.select("li"):
            a_tag = li.select_one("a[href]")
            if not a_tag:
                continue
            title = (a_tag.get("title") or a_tag.get_text()).strip()
            href = a_tag.get("href", "").strip()
            if not title or not href:
                continue
            if f"col{cfg['col']}" not in href:
                continue
            articles.append({"title": title, "url": href, "date": ""})
        return articles

    # ============================================================
    # 详情页解析
    # ============================================================

    def _fetch_detail(self, url: str, cfg: dict) -> dict:
        """
        抓取详情页，提取正文和发布日期。
        使用共享的 extract_detail_content / extract_detail_date。
        """
        resp = self._get(url)
        if not resp:
            return {"content": "", "date": "", "error": "请求失败"}

        soup = BeautifulSoup(resp.text, "lxml")

        # 页面标题
        title_tag = soup.select_one("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""

        # 正文提取（共享选择器）
        content = extract_detail_content(soup)

        # 发布日期提取（共享方法，含龙口换行符处理）
        publish_date = extract_detail_date(soup, content, page_title)

        return {
            "content": content[:5000] if content else "",
            "date": publish_date,
            "page_title": page_title,
        }

    # ============================================================
    # 单区县爬取
    # ============================================================

    def _crawl_one_district(self, key: str, cfg: dict) -> list[dict]:
        """爬取单个区县"""
        name_cn = cfg["name_cn"]
        results = []
        cutoff_date = self.get_cutoff_date()
        # 最晚日期（END_DATE，None 不限制；如抓 7.23~8.13 时 END_DATE="2026-08-13"）
        end_cutoff = None
        if getattr(self, "END_DATE", None):
            try:
                end_cutoff = datetime.date.fromisoformat(self.END_DATE)
            except ValueError:
                logger.warning(f"[{self.name}] END_DATE={self.END_DATE} 格式无效，忽略")
                end_cutoff = None

        # 初始化区县统计
        self.district_stats[key] = {
            "name_cn": name_cn,
            "api_pages": 0,
            "api_total": 0,
            "list_items": 0,
            "skipped_real_estate": 0,
            "skipped_old": 0,
            "skipped_process": 0,
            "skipped_low_score": 0,
            "details_fetched": 0,
            "details_failed": 0,
            "items_kept": 0,
            "stopped": False,
            "error": "",
        }
        st = self.district_stats[key]

        logger.info(
            f"[{self.name}] ═══════════════════════════════════════"
        )
        logger.info(
            f"[{self.name}] 开始: {name_cn} "
            f"({cfg['base_url']}/col/col{cfg['col']})"
        )

        # ---- Phase 1: 翻页列表 API ----
        all_items: list[dict] = []
        page_no = 1
        date_in_list = cfg.get("date_in_list", True)
        max_pages = 9999  # 根据 API total 计算，首页后更新
        no_date_estate_pages = 0   # 无日期栏目：连续不动产页计数（早停优化）

        while True:
            articles, total = self._fetch_list_page(cfg, page_no)

            if page_no == 1:
                if not articles:
                    st["error"] = "API 首页无数据"
                    logger.error(
                        f"[{self.name}][{name_cn}] API 首页无数据，跳过"
                    )
                    self.stats["districts_failed"] += 1
                    return results
                st["api_total"] = total
                max_pages = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE if total else 9999
                logger.info(
                    f"[{self.name}][{name_cn}] API: {total} 篇文章, "
                    f"约 {max_pages} 页"
                )

            st["api_pages"] += 1

            if not articles:
                break

            # 处理本页条目
            kept_in_page = 0     # 本页保留的条目数
            old_in_page = 0      # 本页日期过期的条目数（不含不动产）
            page_estate = 0      # 本页不动产数（无日期栏目早停用）
            for art in articles:
                title = art.get("title", "")

                # 不动产过滤（列表阶段即过滤）
                if self._is_real_estate(title):
                    st["skipped_real_estate"] += 1
                    page_estate += 1
                    continue

                # 日期检查（列表有日期的区县）：早于 START_DATE 或晚于 END_DATE 都跳过
                if date_in_list:
                    date_str = art.get("date", "")
                    art_date = self._parse_date(date_str) if date_str else None
                    if art_date and (art_date < cutoff_date or (end_cutoff and art_date > end_cutoff)):
                        old_in_page += 1
                        st["skipped_old"] += 1
                        continue
                    st["list_items"] += 1
                    all_items.append(art)
                    kept_in_page += 1
                else:
                    # 龙口：无列表日期，全部收集
                    st["list_items"] += 1
                    all_items.append(art)
                    kept_in_page += 1

            # 翻页停止条件：
            # 1. 本页非不动产条目全部过期 → 后续页不会再有新数据
            # 2. 返回空列表 → 最后一页
            # 3. 已翻完 API 报告的总页数
            # 注意：不用 len(articles) < PAGE_SIZE 判断末页，
            #   CMS 可能返回少于 PAGE_SIZE 但仍有后续页（如第3页29条但第4页有数据）
            non_estate = kept_in_page + old_in_page
            if non_estate > 0 and kept_in_page == 0:
                logger.info(
                    f"[{self.name}][{name_cn}] "
                    f"本页 {non_estate} 条非不动产数据均早于截止日期，停止翻页"
                )
                break

            # 无日期栏目早停（龙口等）：列表按时间倒序时，连续 3 页不动产占比 ≥95%
            # → 后续页大概率仍是不动产+更旧公告，提前停止省翻页时间
            if not date_in_list and len(articles) > 0:
                estate_ratio = page_estate / len(articles)
                if estate_ratio >= 0.95:
                    no_date_estate_pages = no_date_estate_pages + 1
                else:
                    no_date_estate_pages = 0
                if no_date_estate_pages >= 3:
                    logger.info(
                        f"[{self.name}][{name_cn}] "
                        f"连续 3 页不动产占比 ≥95%，提前停止翻页（共 {page_no} 页）"
                    )
                    break

            if len(articles) == 0:
                break

            if page_no >= max_pages:
                logger.info(
                    f"[{self.name}][{name_cn}] "
                    f"已到达 API 报告的最后一页 ({max_pages} 页)，停止翻页"
                )
                break

            page_no += 1
            if page_no > 200:
                logger.warning(f"[{self.name}][{name_cn}] 已翻200页，强制停止")
                break

            self._sleep(self.LIST_PAGE_INTERVAL)

        logger.info(
            f"[{self.name}][{name_cn}] Phase 1 完成: "
            f"翻页 {st['api_pages']} 次, "
            f"收集 {len(all_items)} 条候选 "
            f"(不动产跳过 {st['skipped_real_estate']})"
        )

        # ---- Phase 2: 详情页获取 + 评分 ----
        logger.info(
            f"[{self.name}][{name_cn}] "
            f"Phase 2: 处理 {len(all_items)} 条候选..."
        )

        for idx, item in enumerate(all_items):
            title = item.get("title", "")
            url = self._build_url(item["url"], cfg["base_url"])
            list_date = item.get("date", "")

            # ---- Layer 0: 流程/结果公告过滤 ----
            if scorer.is_process_announcement(title):
                st["skipped_process"] += 1
                continue
            if scorer.is_result_announcement(title):
                st["skipped_process"] += 1
                continue

            # ---- 获取详情页 ----
            detail = self._fetch_detail(url, cfg)
            content = detail.get("content", "")
            detail_date = detail.get("date", "")

            if content:
                st["details_fetched"] += 1
            else:
                st["details_failed"] += 1

            # 确定发布日期
            publish_date = list_date if date_in_list else detail_date
            if not publish_date:
                publish_date = detail_date

            # 日期截止（龙口特殊：列表无日期，在此检查）
            if not date_in_list and publish_date:
                art_date = self._parse_date(publish_date)
                # 只有早于 START_DATE 才停止（旧公告之后不会再新）；晚于 END_DATE 走下方 continue 跳过
                if art_date and art_date < cutoff_date:
                    st["stopped"] = True
                    logger.info(
                        f"[{self.name}][{name_cn}] "
                        f"到达截止日期 ({publish_date} < {self.START_DATE}), "
                        f"停止处理"
                    )
                    break

            if publish_date:
                art_date = self._parse_date(publish_date)
                if art_date and (art_date < cutoff_date or (end_cutoff and art_date > end_cutoff)):
                    st["skipped_old"] += 1
                    continue

            # ---- Layer 1: 标题评分 ----
            score, score_detail = scorer.score_title(title)

            if score < self.MIN_SCORE:
                st["skipped_low_score"] += 1
                continue

            # ---- Layer 2: 内容分析 ----
            scale_extracted = ""
            investment_extracted = ""
            nature_extracted = ""

            if content:
                info = scorer.extract_content_info(content, title)
                scale_extracted = info.get("scale", "")
                investment_extracted = info.get("investment", "")
                nature_extracted = info.get("nature", "")

            # 区县信息（从配置获取）
            district = cfg["name_cn"]

            # 正文中尝试提取更具体的区县
            if content:
                content_district = scorer._extract_district(content)
                if content_district:
                    district = content_district

            # ---- 组装结果 ----
            results.append({
                "title": title,
                "content": content,
                "source_url": url,
                "publish_date": self._normalize_date(publish_date),
                "relevance_score": score,
                "score_detail": score_detail,
                "district_extracted": district,
                "scale_extracted": scale_extracted,
                "investment_extracted": investment_extracted,
                "project_nature": nature_extracted,
                "district": key,
                "district_name": name_cn,
            })

            st["items_kept"] += 1

            # 进度日志
            if (idx + 1) % 20 == 0:
                logger.info(
                    f"[{self.name}][{name_cn}] "
                    f"Phase 2: {idx + 1}/{len(all_items)}, "
                    f"已保留 {st['items_kept']} 条"
                )

            self._sleep(self.DETAIL_INTERVAL)

        # ---- 区县完成日志 ----
        high = sum(1 for r in results if r["relevance_score"] >= 5)
        mid = sum(1 for r in results if 3 <= r["relevance_score"] < 5)
        low = sum(1 for r in results if 0 < r["relevance_score"] < 3)

        logger.info(
            f"[{self.name}][{name_cn}] ✅ 完成: "
            f"{len(results)} 条 (高{high}/中{mid}/低{low}) | "
            f"详情: {st['details_fetched']}成功/{st['details_failed']}失败 | "
            f"过滤: 不动产{st['skipped_real_estate']}/"
            f"流程{st['skipped_process']}/"
            f"低分{st['skipped_low_score']}/"
            f"过期{st['skipped_old']}"
        )

        self.stats["districts_completed"] += 1
        self.stats["total_results"] += len(results)
        self.stats["total_details_fetched"] += st["details_fetched"]
        self.stats["total_details_failed"] += st["details_failed"]

        return results

    # ============================================================
    # 主爬取逻辑
    # ============================================================

    def crawl(self) -> list[dict]:
        results: list[dict] = []

        # 确定爬取哪些区县
        if self.target_districts:
            districts_to_crawl = [
                (k, self.DISTRICT_CONFIG[k])
                for k in self.target_districts
                if k in self.DISTRICT_CONFIG
            ]
        else:
            districts_to_crawl = [
                (k, self.DISTRICT_CONFIG[k]) for k in self.CRAWL_ORDER
            ]

        self.stats["districts_total"] = len(districts_to_crawl)

        logger.info(
            f"[{self.name}] 🚀 开始爬取 "
            f"{len(districts_to_crawl)} 个区县 "
            f"(截止日期: {self.START_DATE})"
        )

        for i, (key, cfg) in enumerate(districts_to_crawl):
            name_cn = cfg["name_cn"]
            logger.info(
                f"[{self.name}] [{i + 1}/{len(districts_to_crawl)}] "
                f"▶ {name_cn}"
            )

            try:
                district_results = self._crawl_one_district(key, cfg)
                results.extend(district_results)
            except Exception as e:
                logger.error(
                    f"[{self.name}][{name_cn}] ❌ 爬取异常: {e}"
                )
                self.stats["districts_failed"] += 1
                self.district_stats[key] = self.district_stats.get(
                    key, {"name_cn": name_cn}
                )
                self.district_stats[key]["error"] = str(e)

            # 区县间休息（失败区县后加长到 10s，降低限流概率）
            if i < len(districts_to_crawl) - 1:
                this_failed = self.district_stats.get(key, {}).get("error") or \
                    self.district_stats.get(key, {}).get("items_kept", 0) == 0
                rest = 10.0 if this_failed else self.DISTRICT_INTERVAL
                logger.info(
                    f"[{self.name}] 休息 {rest}s "
                    f"后开始下一个区县..."
                )
                self._sleep(rest)

        # ---- 全局汇总 ----
        self._log_summary(results)

        return results

    def _log_summary(self, results: list[dict]):
        """打印全局汇总日志"""
        logger.info(f"\n{'=' * 60}")
        logger.info(f"[{self.name}] ══════ 全部完成 ══════")
        logger.info(
            f"[{self.name}] 区县: {self.stats['districts_completed']}/"
            f"{self.stats['districts_total']} 成功"
            + (f", {self.stats['districts_failed']} 失败"
               if self.stats['districts_failed'] else "")
        )
        logger.info(
            f"[{self.name}] 总计: {len(results)} 条结果 | "
            f"详情: {self.stats['total_details_fetched']}成功/"
            f"{self.stats['total_details_failed']}失败"
        )

        # 各区县详情
        for key, st in sorted(self.district_stats.items()):
            name_cn = st.get("name_cn", key)
            if st.get("error"):
                logger.info(
                    f"[{self.name}]   {name_cn}: ❌ {st['error']}"
                )
            else:
                logger.info(
                    f"[{self.name}]   {name_cn}: "
                    f"{st.get('items_kept', '?')}条 | "
                    f"翻页{st.get('api_pages', '?')} | "
                    f"不动产跳过{st.get('skipped_real_estate', '?')} | "
                    f"流程跳过{st.get('skipped_process', '?')} | "
                    f"低分跳过{st.get('skipped_low_score', '?')}"
                )

        # 质量分布
        high = sum(1 for r in results if r["relevance_score"] >= 5)
        mid = sum(1 for r in results if 3 <= r["relevance_score"] < 5)
        low = sum(1 for r in results if 0 < r["relevance_score"] < 3)
        logger.info(
            f"[{self.name}] 质量分布: "
            f"[高]{high} [中]{mid} [低]{low}"
        )
        logger.info(f"{'=' * 60}\n")
