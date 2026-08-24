"""
爬虫基类
-------
所有数据源爬虫都继承此类，统一接口和异常处理。
"""
from __future__ import annotations

import re
import time
import random
import datetime
import requests
from typing import Optional
from abc import ABC, abstractmethod
from loguru import logger

from config.settings import USER_AGENT, CRAWL_INTERVAL


class BaseSpider(ABC):
    """
    爬虫基类

    子类只需实现：
      1. name: 爬虫名称
      2. crawl(): 爬取逻辑，yield 每条结果
    """

    # 子类必须设置
    name: str = "base"          # 爬虫名称
    source_name: str = "未知来源"  # 数据源显示名称
    base_url: str = ""          # 网站首页URL

    # ---- 时间窗口配置（所有爬虫统一）----
    SEARCH_DAYS: int = 30       # 搜索最近N天（日常增量运行窗口）
    START_DATE: str = ""        # 最早爬取日期 "2026-01-01"，首次全量时设置
                                 # 置空则仅用 SEARCH_DAYS；设置后取两者中更早的日期

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False  # 不使用系统代理
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })

    def get_cutoff_date(self) -> datetime.date:
        """
        计算爬取截止日期。

        规则：
          1. SEARCH_DAYS — 日常增量窗口（相对日期）
          2. START_DATE — 首次全量起点（绝对日期）
          取两者中更早的日期，确保首次全量+后续增量都能覆盖。

        用法：
          子类在 crawl() 中调用 cutoff = self.get_cutoff_date()
          然后遍历文章时 if art_date < cutoff: break
        """
        cutoff_by_days = datetime.date.today() - datetime.timedelta(
            days=self.SEARCH_DAYS
        )
        if self.START_DATE:
            start_date = datetime.datetime.strptime(
                self.START_DATE, "%Y-%m-%d"
            ).date()
            return min(cutoff_by_days, start_date)
        return cutoff_by_days

    def _get(self, url: str, params: dict = None, **kwargs) -> Optional[requests.Response]:
        """带重试的 GET 请求"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.session.get(
                    url, params=params, timeout=30, **kwargs
                )
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                logger.warning(
                    f"[{self.name}] GET {url[:80]} 失败 (第{attempt+1}次): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 1s, 2s, 4s
        return None

    def _post(self, url: str, data: dict = None, json: dict = None,
              **kwargs) -> Optional[requests.Response]:
        """带重试的 POST 请求"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.session.post(
                    url, data=data, json=json, timeout=30, **kwargs
                )
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                logger.warning(
                    f"[{self.name}] POST {url[:80]} 失败 (第{attempt+1}次): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def _build_url(self, path: str, base_url: str) -> str:
        """补全为完整 HTTPS URL（所有爬虫共用）"""
        if path.startswith("http://"):
            path = path.replace("http://", "https://", 1)
        if not path.startswith("https://"):
            path = base_url.rstrip("/") + "/" + path.lstrip("/")
        return path

    def _parse_date(self, date_str: str) -> Optional[datetime.date]:
        """解析多种日期格式（容忍换行符分割的日期，如龙口 2026-\n07-\n23）"""
        date_str = re.sub(r'\s+', '', date_str)
        date_str = date_str.strip("[]（）() ")
        m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", date_str)
        if m:
            try:
                return datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                pass
        return None

    def _sleep(self, seconds: float = None):
        """礼貌休眠，避免对目标服务器造成压力"""
        if seconds is None:
            seconds = CRAWL_INTERVAL + random.uniform(0, 2)
        time.sleep(seconds)

    @abstractmethod
    def crawl(self) -> list[dict]:
        """
        执行爬取

        返回格式：
        [
            {
                "title": "公告标题",
                "content": "公告正文（可为空）",
                "source_url": "原文链接",
                "publish_date": "2026-07-20",
            },
            ...
        ]
        """
        pass

    def run(self) -> list[dict]:
        """统一入口：执行爬取并记录日志"""
        logger.info(f"[{self.name}] 开始爬取 {self.source_name}...")
        try:
            results = list(self.crawl())
            logger.info(f"[{self.name}] 爬取完成，获取 {len(results)} 条")
            return results
        except Exception as e:
            logger.error(f"[{self.name}] 爬取异常: {e}")
            return []
