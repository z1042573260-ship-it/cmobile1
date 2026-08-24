"""
山东省交通运输厅建设市场信息管理平台爬虫
-----------------------------------------
https://jtt.shandong.gov.cn/jssc/HomeShipServlet?cmd=xmxx&arg=01

采集全省交通建设项目信息，过滤烟台市及区县的新建工程。
重点关注计划交工时间在未来（未完工）的项目 —— 施工期间是基站需求窗口。

爬取策略（v2 - 分层预筛选）：
  新建信号强的类别（高速新建/国省道新建/市政/轨道/铁路）→ 全量抓详情
  其他类别 → Phase1 名称预筛选 → Phase2 详情确认

API 端点:
  列表: POST /jssc/XmDataServlet?cmd=xmxx
  详情: GET  /jssc/ejf/achievementInfo?cmd=projInfoOpenTO&id={id}&procode={proCode}
  城市: POST /jssc/XmDataServlet?cmd=address
"""
from __future__ import annotations

import re
import datetime
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger

from crawler.spiders.base_spider import BaseSpider


class ShandongTransportSpider(BaseSpider):
    name = "shandong_transport"
    source_name = "山东省交通运输厅建设市场信息管理平台"

    BASE_URL = "https://jtt.shandong.gov.cn"
    API_URL = f"{BASE_URL}/jssc/XmDataServlet?cmd=xmxx"
    DETAIL_URL = f"{BASE_URL}/jssc/ejf/achievementInfo"

    # ---- 所有项目类别 ----
    CATEGORIES: dict[str, str] = {
        "01": "高速公路新（改、扩）建工程",
        "02": "高速公路附属设施工程",
        "03": "高速公路养护工程",
        "04": "高速公路信息系统工程",
        "05": "高速公路信息系统养护工程",
        "06": "普通国省道路网新（改、扩）建工程",
        "07": "普通国省道路网附属设施工程",
        "08": "普通国省道路网养护工程",
        "09": "综合衔接工程",
        "10": "农村公路工程",
        "1459822448906-11": "市政工程（城市道路）",
        "11": "水运和支持系统工程",
        "12": "其他工程",
        "1621999756090-11": "城市轨道交通工程",
        "1621998838336-11": "铁路工程",
        "1749035337149-11": "农村公路养护工程",
    }

    # ---- 烟台市区域关键词（包含全部区县）----
    YANTAI_KEYWORDS: list[str] = [
        "烟台市", "芝罘区", "福山区", "牟平区", "莱山区", "蓬莱区",
        "龙口市", "莱阳市", "莱州市", "招远市", "栖霞市", "海阳市",
        "长岛", "开发区", "高新区", "保税港区",
    ]

    # ---- 新建信号强的类别（全量抓详情，不用名称预筛选）----
    FULL_SCAN_CATEGORIES: set[str] = {
        "01",                      # 高速公路新（改、扩）建工程
        "06",                      # 普通国省道路网新（改、扩）建工程
        "1459822448906-11",        # 市政工程（城市道路）
        "1621999756090-11",        # 城市轨道交通工程
        "1621998838336-11",        # 铁路工程
    }

    # ---- 过滤配置 ----
    MIN_SCORE = 1        # 烟台+新建已足够强
    SEARCH_DAYS = 7      # 每周增量：只爬最近7天（首次全量时设 START_DATE 绝对起点）
    START_DATE = ""      # 首次全量起点，如 "2026-01-01"；自动化增量模式置空
    PAGE_SIZE = 20       # API 每页条数
    REQUEST_INTERVAL = 3 # 请求间隔（秒）

    def __init__(self):
        super().__init__()
        self.stats = {
            "api_calls": 0,            # API 请求次数
            "api_items": 0,            # API 返回总项目数
            "name_candidates": 0,      # 名称预筛选通过的候选
            "name_skipped": 0,         # 名称预筛选跳过的
            "full_scan_candidates": 0, # 全量扫描类别候选（不走名称预筛）
            "detail_fetched": 0,       # 详情页抓取成功
            "detail_failed": 0,        # 详情页抓取失败
            "skipped_not_yantai": 0,   # 非烟台跳过（详情确认）
            "skipped_low_score": 0,    # 低分跳过
            "categories_done": 0,      # 已处理类别数
            "categories_empty": 0,     # 无数据类别数
        }

    # ============================================================
    # 列表 API
    # ============================================================

    def _fetch_api_page(
        self, category_type: str, page: int
    ) -> Optional[dict]:
        """
        调用列表 API 获取一页数据。

        返回: {"records": [...], "total": 293, "pages": 15} 或 None
        """
        resp = self._post(
            self.API_URL,
            data={
                "Type": category_type,
                "address": "",
                "name": "",
                "currentPage": str(page),
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.BASE_URL}/jssc/HomeShipServlet?cmd=xmxx&arg={category_type}",
            },
        )

        if not resp:
            logger.error(
                f"[{self.name}] API 请求失败 (Type={category_type}, page={page})"
            )
            return None

        try:
            data = resp.json()
        except Exception:
            logger.error(
                f"[{self.name}] API JSON 解析失败 (Type={category_type}, page={page})"
            )
            return None

        records = data.get("data", [])
        pagecontrol = data.get("pagecontrol", "")

        # 从 pagecontrol HTML 提取分页信息
        total = 0
        pages = 0
        m = re.search(r"共(\d+)条", pagecontrol)
        if m:
            total = int(m.group(1))
        m = re.search(r"第\d+/(\d+)页", pagecontrol)
        if m:
            pages = int(m.group(1))

        self.stats["api_calls"] += 1

        return {
            "records": records,
            "total": total,
            "pages": pages,
        }

    # ============================================================
    # 详情页抓取与解析
    # ============================================================

    def _fetch_detail(
        self, project_id: str, pro_code: str
    ) -> Optional[str]:
        """抓取详情页 HTML。"""
        url = (
            f"{self.DETAIL_URL}"
            f"?cmd=projInfoOpenTO"
            f"&id={project_id}"
            f"&procode={pro_code}"
        )

        resp = self._get(url)
        if not resp:
            self.stats["detail_failed"] += 1
            return None

        # 用 content 解码，容忍畸形字符
        html = resp.content.decode("utf-8", errors="replace")
        self.stats["detail_fetched"] += 1
        return html

    def _parse_detail(self, html: str) -> dict:
        """
        从详情页 HTML 提取结构化字段。

        解析 <table class="tab_xi"> 中 key-value 对：
          <td align="right">字段名:</td>
          <td align="left">值</td>
        """
        soup = BeautifulSoup(html, "lxml")
        result = {
            "项目名称": "",
            "项目编号": "",
            "项目类别": "",
            "是否跨市": "",
            "建设性质": "",
            "项目所在地": "",
            "项目业主单位": "",
            "项目状态": "",
            "技术等级": "",
            "计划开工时间": "",
            "实际开工时间": "",
            "计划交工时间": "",
            "实际交工时间": "",
            "计划竣工时间": "",
            "实际竣工时间": "",
            "工程概算(万元)": "",
            "建设规模及技术标准": "",
            "重点项目": "",
        }

        # 解析主表格 (基本信息 tab)
        main_table = soup.select_one("div#main0 ul.block table.tab_xi")
        if not main_table:
            # 尝试更宽泛的选择器
            main_table = soup.select_one("table.tab_xi")

        if main_table:
            rows = main_table.select("tr")
            for row in rows:
                cells = row.select("td")
                # 处理 key-value 对：每两个 td 一组
                i = 0
                while i + 1 < len(cells):
                    key_td = cells[i]
                    val_td = cells[i + 1]

                    key_text = key_td.get_text(strip=True).rstrip(":").rstrip("：")
                    val_text = val_td.get_text(strip=True)

                    # 清理 &nbsp; 和多余空白
                    val_text = val_text.replace("\xa0", "").strip()

                    if key_text in result:
                        result[key_text] = val_text
                    elif key_text:
                        # 也存入未知 key 便于调试
                        result[key_text] = val_text

                    i += 2

        # 补充：从页面标题提取
        title_tag = soup.select_one("title")
        if title_tag:
            result["_page_title"] = title_tag.get_text(strip=True)

        return result

    # ============================================================
    # 过滤与评分
    # ============================================================

    def _name_hints_yantai(self, proname: str, depname: str) -> bool:
        """
        从项目名称和建设单位名称中预判是否可能属于烟台市。

        这是详情页抓取前的快速预筛选，减少不必要的 HTTP 请求。
        可能有漏网之鱼（项目在烟台但名字不含烟台关键词），但能过滤掉大部分。
        """
        text = (proname or "") + " " + (depname or "")
        for kw in self.YANTAI_KEYWORDS:
            if kw in text:
                return True
        return False

    def _is_yantai(self, location: str) -> bool:
        """判断项目所在地是否属于烟台市（含全部区县）。"""
        if not location:
            return False
        for kw in self.YANTAI_KEYWORDS:
            if kw in location:
                return True
        return False

    def _score_project(self, info: dict) -> tuple[int, dict]:
        """
        对项目进行评分。

        评分维度：
          - 建设性质（新建/改扩建/养护）
          - 计划交工时间（未来/已过）
          - 工程概算（投资规模）
          - 项目状态（前期/在建/交工/竣工）
        """
        score = 0
        detail = {}

        nature = info.get("建设性质", "")
        status = info.get("项目状态", "")
        budget_str = info.get("工程概算(万元)", "")
        plan_delivery = info.get("计划交工时间", "")

        # ---- 建设性质 ----
        if "新建" in nature:
            score += 5
            detail["nature_new"] = 5
        elif "改扩" in nature or "扩建" in nature:
            score += 3
            detail["nature_expand"] = 3
        elif "养护" in nature:
            score += 1
            detail["nature_maintain"] = 1
        else:
            detail["nature_unknown"] = 0

        # ---- 计划交工时间 ----
        if plan_delivery:
            try:
                delivery_date = datetime.datetime.strptime(
                    plan_delivery, "%Y-%m-%d"
                ).date()
                if delivery_date >= datetime.date.today():
                    score += 3
                    detail["delivery_future"] = 3
                else:
                    detail["delivery_past"] = 0
            except ValueError:
                detail["delivery_parse_error"] = 0

        # ---- 工程概算 ----
        if budget_str:
            try:
                budget = float(budget_str)
                budget_yi = budget / 10000  # 万元 → 亿元
                if budget_yi >= 100:
                    score += 5
                    detail["budget_100yi"] = 5
                elif budget_yi >= 10:
                    score += 4
                    detail["budget_10yi"] = 4
                elif budget_yi >= 1:
                    score += 3
                    detail["budget_1yi"] = 3
                elif budget >= 1000:
                    score += 2
                    detail["budget_1000w"] = 2
                else:
                    score += 1
                    detail["budget_small"] = 1
            except ValueError:
                detail["budget_parse_error"] = 0

        # ---- 项目状态 ----
        if "在建" in status:
            score += 2
            detail["status_building"] = 2
        elif "交工" in status or "竣工" in status:
            score -= 1  # 已完工，小幅扣分（仍可能是维护需求）
            detail["status_done"] = -1

        return score, detail

    # ============================================================
    # 主爬取逻辑
    # ============================================================

    def crawl(self) -> list[dict]:
        results = []
        cutoff_date = self.get_cutoff_date()

        logger.info(
            f"[{self.name}] 开始爬取（{len(self.CATEGORIES)} 个类别, "
            f"SEARCH_DAYS={self.SEARCH_DAYS}, START_DATE={self.START_DATE or '无'}, "
            f"截止={cutoff_date}, 请求间隔={self.REQUEST_INTERVAL}s）"
        )

        # ============================================================
        # Phase 1: 遍历所有类别 → 名称预筛选 → 收集候选
        # ============================================================
        candidates: list[dict] = []  # [{id, proCode, proname, depname, inputtime, category, category_type}]
        seen_ids: set[str] = set()

        category_list = list(self.CATEGORIES.items())

        for cat_idx, (cat_type, cat_name) in enumerate(category_list, 1):
            logger.info(
                f"[{self.name}] [Phase1 {cat_idx}/{len(category_list)}] "
                f"{cat_name} (Type={cat_type})"
            )

            # 获取第一页
            page1 = self._fetch_api_page(cat_type, 1)
            if not page1:
                logger.warning(
                    f"[{self.name}]   类别 {cat_name} 第1页无数据，跳过"
                )
                self.stats["categories_empty"] += 1
                self._sleep(self.REQUEST_INTERVAL)
                continue

            total = page1["total"]
            total_pages = page1["pages"]
            all_records = list(page1["records"])

            logger.info(
                f"[{self.name}]   API: {total} 条, {total_pages} 页"
            )

            # 翻页获取剩余
            if total_pages > 1:
                for page_num in range(2, total_pages + 1):
                    self._sleep(self.REQUEST_INTERVAL)

                    page_data = self._fetch_api_page(cat_type, page_num)
                    if not page_data:
                        logger.warning(
                            f"[{self.name}]   第{page_num}页获取失败"
                        )
                        continue

                    all_records.extend(page_data["records"])

            self.stats["api_items"] += len(all_records)
            self.stats["categories_done"] += 1

            # 名称预筛选（全量扫描类别跳过此步）
            is_full_scan = cat_type in self.FULL_SCAN_CATEGORIES
            cat_candidates = 0
            for rec in all_records:
                project_id = rec.get("id", "")
                pro_code = rec.get("proCode", "")
                proname = rec.get("proname", "")
                depname = rec.get("depname", "")
                inputtime = rec.get("inputtime", "")[:10]

                if not project_id or not pro_code:
                    continue

                # 去重（同一项目可能出现在多个类别）
                if project_id in seen_ids:
                    continue
                seen_ids.add(project_id)

                # 日期预过滤
                if inputtime:
                    try:
                        rec_date = datetime.datetime.strptime(
                            inputtime, "%Y-%m-%d"
                        ).date()
                        if rec_date < cutoff_date:
                            continue
                    except ValueError:
                        pass

                # 全量扫描类别：不做名称预筛，全部加入候选
                if is_full_scan:
                    self.stats["full_scan_candidates"] += 1
                else:
                    # 名称预筛选
                    if not self._name_hints_yantai(proname, depname):
                        self.stats["name_skipped"] += 1
                        continue
                    self.stats["name_candidates"] += 1

                cat_candidates += 1
                candidates.append({
                    "id": project_id,
                    "proCode": pro_code,
                    "proname": proname,
                    "depname": depname,
                    "inputtime": inputtime,
                    "category": cat_name,
                    "category_type": cat_type,
                })

            filter_mode = "全量扫描" if is_full_scan else "名称预筛"
            logger.info(
                f"[{self.name}]   {filter_mode}: {cat_candidates} 候选 "
                f"(共 {len(all_records)} 条)"
            )

            # 类别间间隔
            self._sleep(self.REQUEST_INTERVAL)

        logger.info(
            f"[{self.name}] Phase 1 完成: "
            f"API {self.stats['api_items']} 条 → "
            f"候选 {len(candidates)} "
            f"(全量扫描 {self.stats['full_scan_candidates']} + "
            f"名称预筛 {self.stats['name_candidates']}, "
            f"跳过 {self.stats['name_skipped']} 条)"
        )

        # ============================================================
        # Phase 2: 对候选项目抓取详情页，二次确认 + 评分
        # ============================================================
        logger.info(
            f"[{self.name}] [Phase2] 开始抓取 {len(candidates)} 个候选项目详情..."
        )

        for idx, cand in enumerate(candidates):
            project_id = cand["id"]
            pro_code = cand["proCode"]
            proname = cand["proname"]
            depname = cand["depname"]
            inputtime = cand["inputtime"]
            cat_name = cand["category"]
            cat_type = cand["category_type"]

            self._sleep(self.REQUEST_INTERVAL)

            html = self._fetch_detail(project_id, pro_code)
            if not html:
                continue

            info = self._parse_detail(html)

            # ---- 二次确认: 项目所在地必须是烟台 ----
            location = info.get("项目所在地", "")
            if not self._is_yantai(location):
                self.stats["skipped_not_yantai"] += 1
                continue

            # ---- 评分 ----
            score, score_detail = self._score_project(info)

            if score < self.MIN_SCORE:
                self.stats["skipped_low_score"] += 1
                continue

            # ---- 提取关键字段 ----
            nature = info.get("建设性质", "")
            plan_delivery = info.get("计划交工时间", "")
            plan_completion = info.get("计划竣工时间", "")
            budget_str = info.get("工程概算(万元)", "")
            scale_text = info.get("建设规模及技术标准", "")
            project_status = info.get("项目状态", "")
            tech_level = info.get("技术等级", "")

            # 整理 content 正文
            content_parts = []
            for k in [
                "项目名称", "建设性质", "项目所在地", "项目状态",
                "技术等级", "计划开工时间", "计划交工时间",
                "计划竣工时间", "工程概算(万元)", "建设规模及技术标准",
            ]:
                v = info.get(k, "")
                if v:
                    content_parts.append(f"{k}: {v}")
            content = "\n".join(content_parts)

            # ---- 组装结果 ----
            results.append({
                "title": info.get("项目名称", proname),
                "content": content,
                "source_url": (
                    f"{self.DETAIL_URL}"
                    f"?cmd=projInfoOpenTO"
                    f"&id={project_id}"
                    f"&procode={pro_code}"
                ),
                "publish_date": inputtime,
                "relevance_score": score,
                "score_detail": score_detail,
                "district_extracted": location,
                "scale_extracted": scale_text[:300] if scale_text else "",
                "investment_extracted": budget_str,
                "project_nature": nature,
                # 交通项目特有字段
                "project_name": info.get("项目名称", proname),
                "project_location": location,
                "plan_delivery_date": plan_delivery,
                "plan_completion_date": plan_completion,
                "project_status": project_status,
                "tech_level": tech_level,
                "construction_unit": info.get("项目业主单位", depname),
                "category": cat_name,
                "category_type": cat_type,
            })

            if (idx + 1) % 10 == 0:
                logger.info(
                    f"[{self.name}] [Phase2] "
                    f"{idx + 1}/{len(candidates)} 详情已抓取, "
                    f"已确认 {len(results)} 条烟台项目"
                )

        # ---- 汇总统计 ----
        high = sum(1 for r in results if r["relevance_score"] >= 8)
        mid = sum(1 for r in results if 5 <= r["relevance_score"] < 8)
        low = sum(1 for r in results if 1 <= r["relevance_score"] < 5)

        logger.info(
            f"[{self.name}] 全部完成: {len(results)} 条 "
            f"(高{high}/中{mid}/低{low}) | "
            f"Phase1: API {self.stats['api_calls']}次/{self.stats['categories_done']}类 → "
            f"候选 {len(candidates)} "
            f"(全量{self.stats['full_scan_candidates']}+预筛{self.stats['name_candidates']}, "
            f"跳过{self.stats['name_skipped']}) | "
            f"Phase2: 详情 {self.stats['detail_fetched']}成功/"
            f"{self.stats['detail_failed']}失败 | "
            f"二次过滤: 非烟台{self.stats['skipped_not_yantai']}+"
            f"低分{self.stats['skipped_low_score']}"
        )

        # 按评分降序
        results.sort(key=lambda r: r["relevance_score"], reverse=True)

        return results
