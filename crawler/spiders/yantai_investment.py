"""
烟台投资促进中心爬虫
-------------------
https://idb.yantai.gov.cn/col/col53159/index.html
采集招商项目 —— 项目建设的最早期信号！

业务价值：
  招商项目 → 土地出让 → 规划许可 → 施工招标 → 开工 → 基站需求
  招商项目是比土地出让更早 6-12 个月的建设信号！

爬取策略（v1 - CMS API 直连）：
  1. 调用 CMS 分页 API（大汉 JCAP，与规划局相同）
  2. 分页遍历 col53159（招商项目）全部文章
  3. 按日期过滤 → 超过 SEARCH_DAYS 则停止翻页
  4. 逐条访问详情页，提取结构化项目信息
  5. Layer 0/1/2 智能评分过滤（招商项目阈值低，因全部相关）

内容特点：
  全部为招商项目，天然包含：
  - 项目名称、项目地点 → 区县推断
  - 总投资 → 金额提取
  - 项目介绍 → 规模提取（亩/㎡/万元/亿元）
  - 项目合作方式 → 新建/扩建/改建
"""
from __future__ import annotations

import re
import datetime

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider
from crawler.relevance_scorer import scorer
from crawler.cms_api import (
    fetch_cms_list, extract_detail_content, extract_detail_date,
)


class YantaiInvestmentSpider(BaseSpider):
    name = "yantai_investment"
    source_name = "烟台投资促进中心"

    BASE_URL = "https://idb.yantai.gov.cn"

    # ---- CMS API 配置 ----
    API_URL = f"{BASE_URL}/api-gateway/jpaas-publish-server/front/page/build/unit"
    COLUMN_ID = "53159"  # 招商项目

    # API 固定参数（从 col53159 页面源码提取）
    API_BASE_PARAMS = {
        "parseType": "bulidstatic",
        "webId": "44",
        "tplSetId": "4n9VQJnAHileaAUM9bZJ0",
        "pageType": "column",
        "tagId": "右侧列表",
        "editType": "null",
        "pageId": COLUMN_ID,
    }

    PAGE_SIZE = 30  # API 每页条数

    # ---- 过滤配置 ----
    MIN_SCORE = 0       # 招商项目全部相关（投资加分后区分质量）
    SEARCH_DAYS = 7     # 每周增量：只爬最近7天（首次全量时设 START_DATE 绝对起点）
    START_DATE = ""     # 首次全量起点，如 "2026-01-01"；自动化增量模式置空
    PRE_FILTER = False  # 详情获取前不按标题评分过滤（招商项目用词与招标不同）

    def __init__(self):
        super().__init__()
        self.stats = {
            "api_total": 0,            # API 返回的总文章数
            "api_pages": 0,            # 已翻页数
            "list_items": 0,           # 列表解析出的条目数
            "skipped_old": 0,          # 过期跳过
            "skipped_process": 0,      # 流程公告跳过
            "skipped_low_score": 0,    # 低分跳过
            "details_fetched": 0,      # 详情获取成功
            "details_failed": 0,       # 详情获取失败
        }

    # ============================================================
    # CMS 列表 API
    # ============================================================

    def _fetch_list_page(self, page_no: int) -> tuple[list[dict], int]:
        """
        调用 CMS API 获取一页文章列表。

        返回: (articles, total_count)
        """
        html, total = fetch_cms_list(
            session=self.session,
            base_url=self.BASE_URL,
            web_id=self.API_BASE_PARAMS["webId"],
            tpl_set_id=self.API_BASE_PARAMS["tplSetId"],
            tag_id=self.API_BASE_PARAMS["tagId"],
            col_id=self.COLUMN_ID,
            page_no=page_no,
            page_size=self.PAGE_SIZE,
            extra_headers={
                "Referer": f"{self.BASE_URL}/col/col{self.COLUMN_ID}/index.html",
            },
        )

        if not html:
            logger.error(f"[{self.name}] API 请求失败 (page={page_no})")
            return [], 0

        # 从 HTML 中解析文章列表
        articles = []
        soup = BeautifulSoup(html, "lxml")

        for li in soup.select("li"):
            a_tag = li.select_one("a[href][target]")
            if not a_tag:
                a_tag = li.select_one("a[href]")
            if not a_tag:
                continue

            title = a_tag.get_text(strip=True)
            href = a_tag.get("href", "").strip()

            if not title or not href:
                continue

            # 处理特殊字符
            title = title.replace("​", "").replace("﻿", "")

            date_span = li.select_one("span")
            date = date_span.get_text(strip=True) if date_span else ""

            articles.append({
                "title": title,
                "url": href,
                "date": date,
            })

        return articles, total

    # ============================================================
    # 详情页解析
    # ============================================================

    # _build_url 继承自 BaseSpider，无需覆写

    def _fetch_detail(self, url: str) -> dict:
        """
        抓取详情页，提取结构化项目信息。

        招商项目典型字段:
          项目名称, 项目地点, 年度, 总投资, 项目合作方式,
          项目牵头单位, 项目介绍, 项目优势及发展展望,
          市场分析及效益预测, 招商需求及合作方式
        """
        resp = self._get(url)
        if not resp:
            self.stats["details_failed"] += 1
            return {"content": "", "error": "请求失败"}

        # 用 content 解码，容忍畸形字符
        html = resp.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")

        # 页面标题
        title_tag = soup.select_one("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""

        # 正文提取（共享选择器）
        content = extract_detail_content(soup, max_chars=8000)

        self.stats["details_fetched"] += 1

        # 结构化提取
        result = {
            "content": content[:8000] if content else "",
            "page_title": page_title,
            "project_name": "",
            "project_location": "",
            "total_investment": "",
            "project_scale": "",
            "cooperation_mode": "",
            "lead_unit": "",
        }

        if content:
            # 项目名称
            m = re.search(
                r"项目\s*名称\s*[：:]\s*([^\n。；;]{4,120}?)(?:$|\n)",
                content, re.MULTILINE
            )
            if m:
                result["project_name"] = m.group(1).strip()

            # 项目地点
            m = re.search(
                r"项目\s*地点\s*[：:]\s*([^\n。；;]{4,120}?)(?:$|\n)",
                content, re.MULTILINE
            )
            if m:
                result["project_location"] = m.group(1).strip()

            # 总投资
            m = re.search(
                r"总投资\s*[：:]\s*([^\n。；;]{2,60}?)(?:$|\n)",
                content, re.MULTILINE
            )
            if m:
                result["total_investment"] = m.group(1).strip()

            # 合作方式
            m = re.search(
                r"项目\s*合作\s*方式\s*[：:]\s*([^\n。；;]{2,120}?)(?:$|\n)",
                content, re.MULTILINE
            )
            if m:
                result["cooperation_mode"] = m.group(1).strip()

            # 牵头单位
            m = re.search(
                r"项目\s*牵\s*头\s*单\s*位\s*[：:]\s*([^\n。；;]{4,120}?)(?:$|\n)",
                content, re.MULTILINE
            )
            if m:
                result["lead_unit"] = m.group(1).strip()

            # 项目介绍/规模（从项目介绍段落提取面积、投资等）
            intro_match = re.search(
                r"项目\s*介绍\s*[：:]\s*(.+?)(?:\n(?:项目优势|市场分析|招商需求|$))",
                content, re.MULTILINE | re.DOTALL
            )
            if intro_match:
                intro = intro_match.group(1).strip()[:600]
                result["project_scale"] = re.sub(r"\s+", " ", intro)

        # 备用：如果结构化字段为空，尝试从标题提取
        if not result["project_name"]:
            # 标题本身就是项目名
            result["project_name"] = page_title

        return result

    # ============================================================
    # 招商项目专项评分
    # ============================================================

    def _investment_bonus(self, title: str, detail: dict) -> int:
        """
        招商项目专项加分。

        招商项目特点：
        - 通常有明确的投资金额（千万/亿级）
        - 包含用地面积（亩/㎡）
        - 产业园区/厂房/物流等高建设信号项目
        """
        bonus = 0
        content = detail.get("content", "")
        investment = detail.get("total_investment", "")
        text_to_scan = title + " " + content[:2000] if content else title

        # ---- 投资金额加分 ----
        if investment:
            if any(kw in investment for kw in ["亿元", "亿"]):
                # 尝试提取具体数字
                nums = re.findall(r"(\d+\.?\d*)\s*亿", investment)
                if nums:
                    try:
                        amount = float(nums[0])
                        if amount >= 100:
                            bonus += 6   # 百亿级超大项目
                        elif amount >= 10:
                            bonus += 5   # 十亿级
                        elif amount >= 1:
                            bonus += 4   # 亿级
                        else:
                            bonus += 3
                    except ValueError:
                        bonus += 4
                else:
                    bonus += 4
            elif any(kw in investment for kw in ["万元", "万"]):
                nums = re.findall(r"(\d+\.?\d*)\s*万", investment)
                if nums:
                    try:
                        amount = float(nums[0])
                        if amount >= 50000:
                            bonus += 4   # 5亿+
                        elif amount >= 10000:
                            bonus += 3   # 1亿+
                        elif amount >= 1000:
                            bonus += 2   # 千万级
                        else:
                            bonus += 1
                    except ValueError:
                        bonus += 2
                else:
                    bonus += 2

        # ---- 规模加分 ----
        # 用地面积
        area_match = re.findall(
            r"(\d+\.?\d*)\s*(?:亩|公顷|万?\s*平方米|万?\s*㎡|平方公里)",
            text_to_scan
        )
        for num_str in area_match:
            try:
                area = float(num_str)
                if area >= 1000:
                    bonus += 4  # 千亩级
                elif area >= 100:
                    bonus += 3  # 百亩级
                elif area >= 10:
                    bonus += 2
                else:
                    bonus += 1
                break  # 只取第一个
            except ValueError:
                continue

        # ---- 项目类型加分 ----
        # 产业园区/厂房/物流 → 高建设信号
        high_signal_kw = [
            "产业园", "科技园", "工业园", "物流园", "创业园",
            "厂房", "仓库", "物流中心", "数据中心",
            "码头", "港口", "机场", "高速公路", "铁路",
            "生产基地", "制造基地", "加工基地",
        ]
        for kw in high_signal_kw:
            if kw in text_to_scan:
                bonus += 3
                break

        mid_signal_kw = [
            "综合体", "商业街", "酒店", "度假", "康养",
            "养老", "医院", "学校", "体育", "文旅",
            "温泉", "小镇", "景区", "旅游", "生态",
        ]
        for kw in mid_signal_kw:
            if kw in text_to_scan:
                bonus += 2
                break

        return bonus

    # ============================================================
    # 主爬取逻辑
    # ============================================================

    def crawl(self) -> list[dict]:
        results = []
        cutoff_date = self.get_cutoff_date()

        # ---- 阶段 1: 分页遍历列表 API ----
        logger.info(
            f"[{self.name}] 开始获取列表"
            f"（SEARCH_DAYS={self.SEARCH_DAYS}, START_DATE={self.START_DATE or '无'}, "
            f"截止={cutoff_date}）..."
        )

        all_items = []
        page_no = 1
        stop_paging = False

        while not stop_paging:
            articles, total = self._fetch_list_page(page_no)

            if page_no == 1:
                if not articles:
                    logger.error(f"[{self.name}] API 首页无数据，终止")
                    return results
                self.stats["api_total"] = total
                total_pages = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE
                logger.info(
                    f"[{self.name}] API: {total} 篇文章, "
                    f"约 {total_pages} 页"
                )

            self.stats["api_pages"] += 1

            if not articles:
                logger.warning(f"[{self.name}] 第{page_no}页无数据，停止翻页")
                break

            # 检查日期是否超出范围
            for art in articles:
                date_str = art.get("date", "")
                if date_str:
                    try:
                        art_date = datetime.datetime.strptime(
                            date_str, "%Y-%m-%d"
                        ).date()
                        if art_date < cutoff_date:
                            stop_paging = True
                            self.stats["skipped_old"] += 1
                            break
                    except ValueError:
                        pass

                all_items.append(art)
                self.stats["list_items"] += 1

            page_no += 1

            # 安全上限
            if page_no > 200:
                logger.warning(f"[{self.name}] 已翻200页，强制停止")
                break

            self._sleep(0.3)

        logger.info(
            f"[{self.name}] 列表获取完成: {len(all_items)} 条 "
            f"(翻页{self.stats['api_pages']}次, "
            f"过期截止于{cutoff_date})"
        )

        # ---- 阶段 2: 逐条过滤 + 详情 ----
        logger.info(f"[{self.name}] 开始逐条处理...")

        for i, item in enumerate(all_items):
            title = item["title"]
            url = self._build_url(item["url"], self.BASE_URL)
            date = item.get("date", "")

            # ---- Layer 0: 流程公告预过滤 ----
            if scorer.is_process_announcement(title):
                self.stats["skipped_process"] += 1
                continue
            if scorer.is_result_announcement(title):
                self.stats["skipped_process"] += 1
                continue

            # ---- Layer 1: 标题评分 ----
            score, score_detail = scorer.score_title(title)

            # 招商项目标题用词与工程招标不同，不在此时过滤
            # 等拿到详情页投资/规模信息后再判断

            # ---- 区县预提取 ----
            district = scorer._extract_district(title)

            # ---- 获取详情 ----
            logger.debug(f"[{self.name}] [{i+1}/{len(all_items)}] {title[:60]}...")

            detail = self._fetch_detail(url)
            content = detail.get("content", "")

            # ---- 招商项目专项加分 ----
            invest_bonus = self._investment_bonus(title, detail)
            score += invest_bonus
            score_detail["investment_bonus"] = invest_bonus

            # 招商项目：投资加分后才判断是否低于阈值
            if score < self.MIN_SCORE:
                self.stats["skipped_low_score"] += 1
                continue

            # ---- Layer 2: 内容深度分析 ----
            scale_extracted = ""
            investment_extracted = ""
            nature_extracted = ""

            if content:
                info = scorer.extract_content_info(content, title)
                scale_extracted = info.get("scale", "")
                investment_extracted = info.get("investment", "")
                nature_extracted = info.get("nature", "")

            # 结构化字段补充
            if not investment_extracted and detail.get("total_investment"):
                investment_extracted = detail["total_investment"]

            if not scale_extracted and detail.get("project_scale"):
                scale_extracted = detail["project_scale"][:300]

            if not district and detail.get("project_location"):
                district = scorer._extract_district(detail["project_location"])

            # 合作方式 → 项目性质
            if not nature_extracted and detail.get("cooperation_mode"):
                mode = detail["cooperation_mode"]
                if any(kw in mode for kw in ["新建", "新引进", "招商引资"]):
                    nature_extracted = "新建"
                elif any(kw in mode for kw in ["扩建", "技改", "升级"]):
                    nature_extracted = "扩建"
                elif any(kw in mode for kw in ["改造", "改建", "盘活"]):
                    nature_extracted = "改造"
                else:
                    nature_extracted = mode[:20]

            # 项目地点 → 区县补充
            if not district and detail.get("project_location"):
                district = scorer._extract_district(detail["project_location"])

            # ---- 组装结果 ----
            results.append({
                "title": title,
                "content": content,
                "source_url": url,
                "publish_date": date,
                "relevance_score": score,
                "score_detail": score_detail,
                "district_extracted": district,
                "scale_extracted": scale_extracted,
                "investment_extracted": investment_extracted,
                "project_nature": nature_extracted,
                # 招商项目特有字段
                "project_name": detail.get("project_name", ""),
                "project_location": detail.get("project_location", ""),
                "total_investment": detail.get("total_investment", ""),
                "cooperation_mode": detail.get("cooperation_mode", ""),
                "lead_unit": detail.get("lead_unit", ""),
            })

            self._sleep(0.5)

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
