"""
山东省交通运输厅 招标信息 爬虫
-----------------------------------------
https://jtt.shandong.gov.cn/jssc/HomeShipServlet?cmd=zbxx&looktype=5

采集招标计划（zbjh）数据，筛选烟台市相关项目。
API 按发布时间降序排列，翻页到 2026-02-01 截止。

爬取策略：
  Phase 1: 翻页列表 API（limit=40 最大化效率）→ 多维度筛选烟台候选
  Phase 2: 对候选调详情 API → 补充 investment/bid_content

API 端点:
  列表: POST /jssc/ZbDataServlet?cmd=zbjh
  详情: POST /jssc/ZbDataServlet?cmd=zbjhData
"""
from __future__ import annotations

import datetime
from typing import Optional

from loguru import logger

from crawler.spiders.base_spider import BaseSpider


class ShandongZbxxSpider(BaseSpider):
    name = "shandong_zbxx"
    source_name = "山东省交通运输厅招标信息"

    BASE_URL = "https://jtt.shandong.gov.cn"
    API_URL = f"{BASE_URL}/jssc/ZbDataServlet?cmd=zbjh"
    DETAIL_API_URL = f"{BASE_URL}/jssc/ZbDataServlet?cmd=zbjhData"
    DETAIL_PAGE_URL = f"{BASE_URL}/jssc/HomeShipServlet?cmd=zbjhnews"

    # ---- 烟台市区域关键词（包含全部区县）----
    YANTAI_KEYWORDS: list[str] = [
        "烟台市", "芝罘区", "福山区", "牟平区", "莱山区", "蓬莱区",
        "龙口市", "莱阳市", "莱州市", "招远市", "栖霞市", "海阳市",
        "长岛", "开发区", "高新区", "保税港区",
    ]

    # ---- 过滤配置 ----
    SEARCH_DAYS = 7   # 每周增量：只爬最近7天
    START_DATE = ""   # 数据起始日期（置空=用 SEARCH_DAYS 每周增量窗口；首次全量时设绝对日期）
    PAGE_SIZE = 40             # 每页条数（最大值）
    REQUEST_INTERVAL = 3       # 请求间隔（秒）

    def __init__(self):
        super().__init__()
        self.stats = {
            "api_calls": 0,
            "api_items": 0,
            "candidates": 0,
            "detail_fetched": 0,
            "detail_failed": 0,
            "pages_scanned": 0,
            "stopped_by_date": False,
        }

    # ============================================================
    # 列表 API
    # ============================================================

    def _fetch_list_page(self, page: int) -> Optional[dict]:
        """调用列表 API 获取一页数据。"""
        resp = self._post(
            self.API_URL,
            data={
                "page": str(page),
                "limit": str(self.PAGE_SIZE),
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.BASE_URL}/jssc/HomeShipServlet?cmd=zbxx&looktype=5",
            },
        )

        if not resp:
            logger.error(f"[{self.name}] API 请求失败 (page={page})")
            return None

        try:
            data = resp.json()
        except Exception:
            logger.error(f"[{self.name}] API JSON 解析失败 (page={page})")
            return None

        self.stats["api_calls"] += 1
        return data

    # ============================================================
    # 详情 API
    # ============================================================

    def _fetch_detail(self, item_id: int) -> Optional[dict]:
        """调用详情 API 获取额外字段（investment/bid_content 等）。"""
        resp = self._post(
            self.DETAIL_API_URL,
            data={"id": str(item_id)},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.BASE_URL}/jssc/HomeShipServlet?cmd=zbjhnews&id={item_id}",
            },
        )

        if not resp:
            self.stats["detail_failed"] += 1
            return None

        try:
            data = resp.json()
        except Exception:
            self.stats["detail_failed"] += 1
            return None

        self.stats["detail_fetched"] += 1
        return data.get("data", {})

    # ============================================================
    # 烟台判断
    # ============================================================

    # 通用关键词（全国多地都有，单独命中不可靠）
    _GENERIC_KEYWORDS: set[str] = {"高新区", "开发区", "保税港区"}

    def _hints_yantai(self, item: dict) -> bool:
        """
        多维度判断是否可能属于烟台市。

        检查维度（按可靠性排序）：
          1. adminsupervisiondept — 监管部门（最可靠）
          2. user_name — 招标人（烟台单位）
          3. plan_name / track_name — 项目名/招标计划名
          4. situation — 项目概况文本（最弱，可能有跨区域道路提及）
        """
        # 维度1: 监管部门 — 最可靠
        dept = item.get("adminsupervisiondept", "")
        if "烟台" in dept:
            return True

        # 维度2-4: 名称关键词匹配
        text_fields = [
            item.get("user_name", ""),
            item.get("plan_name", ""),
            item.get("track_name", ""),
            item.get("situation", ""),
        ]
        combined = " ".join(text_fields)

        matched_specific = False
        matched_generic = False
        for kw in self.YANTAI_KEYWORDS:
            if kw in combined:
                if kw in self._GENERIC_KEYWORDS:
                    matched_generic = True
                else:
                    matched_specific = True
                    break  # 有具体地名命中即可

        # 只命中通用关键词（高新区/开发区/保税港区）不可靠，需要监管部门或招标人佐证
        if matched_generic and not matched_specific:
            user = item.get("user_name", "")
            if "烟台" not in user:
                return False

        return matched_specific or matched_generic

    def _score_bid(self, item: dict, detail: dict | None) -> tuple[int, dict]:
        """
        招标计划评分。维度：
          - 投资规模（合同预估金额）
          - 是否含新建/改扩建关键词
          - 监管部门是否为烟台市（市级项目更相关）
        """
        score = 0
        detail_map = {}

        # 投资规模
        investment_str = ""
        if detail:
            investment_str = detail.get("investment", "")
        if investment_str and investment_str not in ("/", "", "0"):
            try:
                inv = float(investment_str)
                inv_yi = inv / 10000
                if inv_yi >= 10:
                    score += 5
                    detail_map["investment_10yi"] = 5
                elif inv_yi >= 1:
                    score += 4
                    detail_map["investment_1yi"] = 4
                elif inv >= 1000:
                    score += 3
                    detail_map["investment_1000w"] = 3
                elif inv >= 100:
                    score += 2
                    detail_map["investment_100w"] = 2
                else:
                    score += 1
                    detail_map["investment_small"] = 1
            except ValueError:
                pass

        # 新建/改扩建信号
        text_fields = [
            item.get("plan_name", ""),
            item.get("track_name", ""),
            item.get("situation", ""),
        ]
        if detail:
            text_fields.append(detail.get("bid_content", ""))
        combined = " ".join(text_fields)

        if any(w in combined for w in ["新建", "新（改", "改扩建", "改建"]):
            score += 4
            detail_map["nature_new"] = 4
        elif any(w in combined for w in ["路面改造", "修复养护", "预防养护"]):
            score += 2
            detail_map["nature_maintain"] = 2
        elif "养护" in combined:
            score += 1
            detail_map["nature_routine"] = 1

        # 烟台市级监管部门
        dept = item.get("adminsupervisiondept", "")
        if "烟台" in dept:
            score += 2
            detail_map["yantai_dept"] = 2

        return score, detail_map

    # ============================================================
    # 主爬取逻辑
    # ============================================================

    def crawl(self) -> list[dict]:
        results = []

        logger.info(
            f"[{self.name}] 开始爬取招标计划 "
            f"(START_DATE={self.START_DATE}, "
            f"PAGE_SIZE={self.PAGE_SIZE}, "
            f"间隔={self.REQUEST_INTERVAL}s)"
        )

        start_date = self.get_cutoff_date()  # SEARCH_DAYS 增量窗口（START_DATE 置空时）

        # ============================================================
        # Phase 1: 翻页列表 → 筛选烟台候选
        # ============================================================
        candidates: list[dict] = []
        seen_ids: set[int] = set()
        page = 1

        while True:
            page_data = self._fetch_list_page(page)
            if not page_data:
                logger.warning(f"[{self.name}] 第{page}页获取失败，停止翻页")
                break

            records = page_data.get("data", [])
            total = page_data.get("count", 0)
            self.stats["api_items"] += len(records)
            self.stats["pages_scanned"] += 1

            if page == 1:
                logger.info(
                    f"[{self.name}] 总计 {total} 条, "
                    f"约 {total // self.PAGE_SIZE + 1} 页"
                )

            logger.info(
                f"[{self.name}] [Phase1] 第{page}页: {len(records)} 条"
            )

            for rec in records:
                item_id = rec.get("id")
                if not item_id:
                    continue
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                # 日期截止
                planpubtime = rec.get("planpubtime", "")
                if planpubtime:
                    try:
                        pub_date = datetime.datetime.strptime(
                            planpubtime[:10], "%Y-%m-%d"
                        ).date()
                        if pub_date < start_date:
                            self.stats["stopped_by_date"] = True
                            logger.info(
                                f"[{self.name}] 到达截止日期 "
                                f"(planpubtime={planpubtime[:10]} < {self.START_DATE}), "
                                f"停止翻页"
                            )
                            break
                    except ValueError:
                        pass

                # 烟台判断
                if self._hints_yantai(rec):
                    self.stats["candidates"] += 1
                    candidates.append(rec)

            # 检查是否需要停止（break from inner loop）
            if self.stats["stopped_by_date"]:
                break

            # 检查是否还有下一页
            if len(records) < self.PAGE_SIZE:
                logger.info(f"[{self.name}] 已到最后一页")
                break

            page += 1
            self._sleep(self.REQUEST_INTERVAL)

        logger.info(
            f"[{self.name}] Phase 1 完成: "
            f"扫描 {self.stats['pages_scanned']} 页/"
            f"{self.stats['api_items']} 条 → "
            f"{len(candidates)} 候选"
        )

        # ============================================================
        # Phase 2: 对候选调详情 API → 补充 investment/bid_content
        # ============================================================
        logger.info(
            f"[{self.name}] [Phase2] 抓取 {len(candidates)} 个候选详情..."
        )

        for idx, cand in enumerate(candidates):
            item_id = cand.get("id")
            self._sleep(self.REQUEST_INTERVAL)

            detail = self._fetch_detail(item_id)

            # 从详情或列表提取字段
            plan_name = cand.get("plan_name", "")
            track_name = cand.get("track_name", "")
            user_name = cand.get("user_name", "")
            situation = cand.get("situation", "")
            planpubtime = cand.get("planpubtime", "")
            track_no = cand.get("track_no", "")
            pro_venue = cand.get("pro_venue", "")
            adminsupervisiondept = cand.get("adminsupervisiondept", "")

            investment = ""
            bid_type = ""
            bid_content = ""
            plan_pub_month = ""

            if detail:
                investment = detail.get("investment", "")
                bid_type = detail.get("bid_type", "")
                bid_content = detail.get("bid_content", "")
                plan_pub_month = detail.get("data", "")

            # 评分
            score, score_detail = self._score_bid(cand, detail)

            # 组装 content 正文
            content_parts = []
            for label, val in [
                ("项目名称", track_name),
                ("招标人", user_name),
                ("招标方式", bid_type),
                ("合同预估金额(万元)", investment),
                ("招标内容", bid_content),
                ("项目主要建设内容", situation),
                ("项目批准文号", track_no),
                ("拟交易场所", pro_venue),
                ("监管部门", adminsupervisiondept),
            ]:
                if val:
                    content_parts.append(f"{label}: {val}")
            content = "\n".join(content_parts)

            results.append({
                "title": plan_name,
                "content": content,
                "source_url": f"{self.DETAIL_PAGE_URL}&id={item_id}",
                "publish_date": planpubtime[:10] if planpubtime else "",
                "relevance_score": score,
                "score_detail": score_detail,
                # 招标特有字段
                "project_name": track_name,
                "plan_name": plan_name,
                "bidder": user_name,
                "bid_type": bid_type,
                "investment": investment,
                "bid_content": bid_content,
                "plan_pub_month": plan_pub_month,
                "track_no": track_no,
                "pro_venue": pro_venue,
                "supervision_dept": adminsupervisiondept,
                "situation": (situation or "")[:500],
            })

            if (idx + 1) % 5 == 0:
                logger.info(
                    f"[{self.name}] [Phase2] "
                    f"{idx + 1}/{len(candidates)} 详情已抓取"
                )

        # ---- 汇总 ----
        logger.info(
            f"[{self.name}] 全部完成: {len(results)} 条 | "
            f"Phase1: {self.stats['api_calls']}次API/"
            f"{self.stats['pages_scanned']}页/{self.stats['api_items']}条 → "
            f"{len(candidates)}候选 | "
            f"Phase2: {self.stats['detail_fetched']}成功/"
            f"{self.stats['detail_failed']}失败"
        )

        return results
