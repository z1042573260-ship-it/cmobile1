"""
烟台市自然资源和规划局爬虫
-------------------------
https://gtj.yantai.gov.cn/
采集建设工程规划许可证、用地规划许可、规划批前公示。
这是比施工招标更早 2-6 个月的建设信号！

业务价值：
  土地出让 → 规划许可(本爬虫) → 施工招标 → 开工 → 基站需求
  规划许可证核发公示 = 项目已通过规划审批，即将进入招标阶段

爬取策略（v3 - CMS API 直连）：
  1. 调用 CMS 分页 API (/api-gateway/jpaas-publish-server/front/page/build/unit)
  2. 分页遍历 col17923（规划公开公示）全部文章
  3. 按日期过滤 → 超过 SEARCH_DAYS 则停止翻页
  4. 逐条访问详情页，提取结构化信息
  5. Layer 0/1/2 智能评分过滤

API 发现过程：
  首页 → col17923 页面 → unitbuild.js → AJAX → page/build/unit
  col17923 = 规划公开公示（4932篇文章，每页30条）
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


class YantaiPlanningSpider(BaseSpider):
    name = "yantai_planning"
    source_name = "烟台市自然资源和规划局"

    BASE_URL = "https://gtj.yantai.gov.cn"

    # ---- CMS API 配置 ----
    API_URL = f"{BASE_URL}/api-gateway/jpaas-publish-server/front/page/build/unit"
    COLUMN_ID = "17923"  # 规划公开公示

    # API 固定参数（从 col17923 页面源码提取）
    API_BASE_PARAMS = {
        "parseType": "bulidstatic",
        "webId": "166",
        "tplSetId": "3pxbLvVe09Zu1iPgroYTv",
        "pageType": "column",
        "tagId": "栏目列表",
        "editType": "null",
        "pageId": COLUMN_ID,
    }

    PAGE_SIZE = 30  # API 每页条数

    # ---- 过滤配置 ----
    MIN_SCORE = 1       # 规划许可 = 强信号，低阈值
    SEARCH_DAYS = 7     # 每周增量：只爬最近7天

    def __init__(self):
        super().__init__()
        self.stats = {
            "api_total": 0,            # API 返回的总文章数
            "api_pages": 0,            # 已翻页数
            "list_items": 0,           # 列表解析出的条目数
            "skipped_old": 0,          # 过期跳过
            "skipped_not_planning": 0, # 非规划类跳过
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
            a_tag = li.select_one("a[href][title]")
            if not a_tag:
                continue

            title = a_tag.get("title", "").strip()
            href = a_tag.get("href", "").strip()

            if not title or not href:
                continue

            # 只收本栏目的文章
            if f"col{self.COLUMN_ID}" not in href:
                continue

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

    def _is_planning_related(self, title: str) -> bool:
        """
        只收与建设项目直接相关的规划公示。
        过滤掉：纯规划编制（无具体项目）、结果反馈、政策文件等。
        """
        # ---- 排除关键词：这些不是具体建设项目 ----
        EXCLUDE_KEYWORDS = [
            "结果反馈", "意见反馈", "草案公示", "村庄布局规划",
            "国土空间规划", "总体规划", "片区规划", "详细规划",
            "控制性详细规划", "控规", "城市设计", "山海融城",
            "海岸带", "保护区", "生态", "永久基本农田",
            "普法工作", "预算", "收费目录",
        ]

        for kw in EXCLUDE_KEYWORDS:
            if kw in title:
                # 但如果同时有具体的建设项目关键词，仍然保留
                if any(k in title for k in [
                    "项目", "工程", "园区", "厂", "小区", "住宅",
                    "安置", "改造", "新建", "扩建", "迁建",
                ]):
                    continue  # 有项目关键词，不排除
                return False

        # ---- 正向关键词：直接匹配建设项目 ----
        INCLUDE_KEYWORDS = [
            "建设工程规划许可", "用地规划许可", "选址意见书",
            "批前公示", "批后公示", "规划设计方案", "建筑方案",
            "核发公示", "核发批前", "规划调整方案",
            "用地预审", "项目规划", "项目公示",
            "厂房", "仓库", "生产线", "技改",
            "旧村改造", "棚户区", "安置房", "保障房",
            "住宅项目", "住宅小区", "产业园", "科技园",
            "物流园", "污水处理", "热源", "管网", "管线",
            "道路", "交通", "停车场", "充电",
            "学校", "医院", "养老", "体育",
            "供热", "供水", "供电", "变电站",
        ]

        for kw in INCLUDE_KEYWORDS:
            if kw in title:
                return True

        return False

    def _fetch_detail(self, url: str) -> dict:
        """
        抓取详情页，提取结构化信息。

        规划许可公示的典型字段:
          建设单位, 项目名称, 项目位置, 用地性质, 建设规模, 公示时间
        """
        resp = self._get(url)
        if not resp:
            self.stats["details_failed"] += 1
            return {"content": "", "error": "请求失败"}

        soup = BeautifulSoup(resp.text, "lxml")

        # 页面标题
        title_tag = soup.select_one("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""

        # 正文提取（共享选择器）
        content = extract_detail_content(soup)

        self.stats["details_fetched"] += 1

        # 结构化提取
        result = {
            "content": content[:5000] if content else "",
            "page_title": page_title,
            "construction_unit": "",
            "project_location": "",
            "land_use_type": "",
            "construction_scale": "",
        }

        if content:
            # 建设单位
            m = re.search(
                r"建设\s*单位\s*[：:]\s*([^\n。；;]{4,80}?)(?:$|\n|。|；|;)",
                content, re.MULTILINE
            )
            if m:
                result["construction_unit"] = m.group(1).strip()

            # 项目名称
            m = re.search(
                r"项目\s*名称\s*[：:]\s*([^\n。；;]{4,120}?)(?:$|\n|。|；|;)",
                content, re.MULTILINE
            )
            if m:
                result["project_name"] = m.group(1).strip()

            # 项目位置
            m = re.search(
                r"项目\s*位置\s*[：:]\s*([^\n。；;]{4,120}?)(?:$|\n|。|；|;)",
                content, re.MULTILINE
            )
            if m:
                result["project_location"] = m.group(1).strip()

            # 用地性质
            m = re.search(
                r"用地\s*性质\s*[：:]\s*([^\n。；;]{2,60}?)(?:$|\n|。|；|;)",
                content, re.MULTILINE
            )
            if m:
                result["land_use_type"] = m.group(1).strip()

            # 建设规模（多行匹配）
            m = re.search(
                r"建设\s*规模\s*[：:]\s*(.+?)(?:\n(?:[一二三四五六七八九十百千万亿兆a-zA-Z一-鿿]{1,6}\s*[：:]|\n\n|$))",
                content, re.MULTILINE | re.DOTALL
            )
            if m:
                scale_text = m.group(1).strip()[:400]
                result["construction_scale"] = re.sub(r"\s+", " ", scale_text)

        # 从标题提取建设单位（备用）
        if not result["construction_unit"]:
            m = re.search(
                r"(.{4,30}?(?:公司|集团|厂|中心|学院|学校|医院|局|委员会|政府|政府))",
                page_title
            )
            if m and m.group(1) != "烟台市自然资源和规划局":
                result["construction_unit"] = m.group(1)

        return result

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
        total_pages = None
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

            # ---- 过滤: 只收规划建设相关 ----
            if not self._is_planning_related(title):
                self.stats["skipped_not_planning"] += 1
                continue

            # ---- Layer 0: 流程公告预过滤 ----
            if scorer.is_process_announcement(title):
                self.stats["skipped_process"] += 1
                continue
            if scorer.is_result_announcement(title):
                self.stats["skipped_process"] += 1
                continue

            # ---- 规划许可加分 ----
            planning_bonus = 0
            if any(kw in title for kw in [
                "建设工程规划许可", "用地规划许可", "选址意见书",
                "批前公示", "规划设计方案", "用地预审",
            ]):
                planning_bonus = 4  # 规划许可 = 强建设信号
            elif any(kw in title for kw in [
                "批后公示", "批后公开", "规划调整", "建筑方案",
            ]):
                planning_bonus = 2

            # ---- Layer 1: 标题评分 ----
            score, score_detail = scorer.score_title(title)
            score += planning_bonus
            score_detail["planning_bonus"] = planning_bonus

            if score < self.MIN_SCORE:
                self.stats["skipped_low_score"] += 1
                continue

            # ---- 区县预提取 ----
            district = scorer._extract_district(title)

            # ---- 获取详情 ----
            logger.debug(f"[{self.name}] [{i+1}/{len(all_items)}] {title[:60]}...")

            detail = self._fetch_detail(url)
            content = detail.get("content", "")

            # ---- Layer 2: 内容深度分析 ----
            scale_extracted = ""
            investment_extracted = ""
            nature_extracted = ""

            if content:
                info = scorer.extract_content_info(content, title)
                scale_extracted = info.get("scale", "")
                investment_extracted = info.get("investment", "")
                nature_extracted = info.get("nature", "")

            # 正文中的建设规模
            if detail.get("construction_scale") and not scale_extracted:
                scale_extracted = detail["construction_scale"]

            # 项目位置 → 区县
            if not district and detail.get("project_location"):
                district = scorer._extract_district(detail["project_location"])

            # 用地性质 → 项目性质
            if detail.get("land_use_type") and not nature_extracted:
                land = detail["land_use_type"]
                if any(kw in land for kw in ["工业", "仓储", "物流"]):
                    nature_extracted = "工业"
                elif any(kw in land for kw in ["居住", "住宅"]):
                    nature_extracted = "住宅"
                elif any(kw in land for kw in ["商服", "商业", "商务"]):
                    nature_extracted = "商业"
                elif any(kw in land for kw in ["公共", "交通", "教育", "医疗", "市政",
                                                "道路", "供电", "供水", "供热", "环卫"]):
                    nature_extracted = "公共设施"
                else:
                    nature_extracted = land

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
                # 规划局特有字段
                "construction_unit": detail.get("construction_unit", ""),
                "project_location": detail.get("project_location", ""),
                "land_use_type": detail.get("land_use_type", ""),
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
            f"过滤: 非规划{self.stats['skipped_not_planning']}+"
            f"流程{self.stats['skipped_process']}+"
            f"低分{self.stats['skipped_low_score']}+"
            f"过期{self.stats['skipped_old']}"
        )

        return results
