"""
项目相关性评分引擎
------------------
所有爬虫共用的智能过滤逻辑。
从"二元关键词匹配"升级为"加权评分 + 内容分析"，
解决"法律服务项目"、"设备采购"等无关数据混入的问题。

设计原则：
  - 宁愿多抓不遗漏：评分是辅助，不是绝对拦截
  - 透明可审计：每个评分都有明细，方便人工复核
  - 阈值可调：不同数据源使用不同阈值
"""

import re
from typing import Tuple, Dict, List, Optional

from config.settings import YANTAI_DISTRICTS


# ============================================================
# 正向信号：越大的新建项目，分数越高
# ============================================================
POSITIVE_SIGNALS: List[Tuple[int, str]] = [
    # +5: 确定是大型新建工程
    (5, "施工总承包"),
    (5, "EPC总承包"),
    (5, "设计施工总承包"),
    (5, "新建"),
    (5, "住宅小区"),
    (5, "新校区"),
    (5, "新院区"),
    (5, "隧道工程"),
    (5, "隧道施工"),
    (5, "大桥工程"),
    (5, "跨海大桥"),

    # +4: 明确的大中型新项目
    (4, "棚户区改造"),
    (4, "安置房"),
    (4, "保障房"),
    (4, "产业园"),
    (4, "科技园"),
    (4, "智造园"),
    (4, "物流园"),
    (4, "医院迁建"),
    (4, "学校新建"),
    (4, "EPC项目"),
    (4, "建设项目"),

    # +3: 很可能的新建设工程
    (3, "EPC"),
    (3, "安置小区"),
    (3, "医院"),
    (3, "学校"),
    (3, "幼儿园"),
    (3, "产业园区"),
    (3, "工业园区"),
    (3, "交通枢纽"),
    (3, "住宅项目"),
    (3, "住宅楼"),
    (3, "商业综合体"),
    (3, "写字楼"),
    (3, "体育场馆"),
    (3, "体育中心"),
    (3, "会展中心"),
    (3, "地下空间"),
    (3, "综合管廊"),
    (3, "乡村振兴"),
    (3, "改扩建"),          # 改扩建工程
    (3, "开工"),            # 开工建设
    (3, "开工仪式"),        # 开工仪式

    # +2: 一般建设工程
    (2, "施工"),
    (2, "建设"),
    (2, "建筑工程"),
    (2, "道路工程"),
    (2, "市政工程"),
    (2, "公用建筑"),
    (2, "综合楼"),
    (2, "教学楼"),
    (2, "住院楼"),
    (2, "门诊楼"),
    (2, "厂房"),
    (2, "钢结构"),
    (2, "幕墙工程"),
    (2, "土建"),
    (2, "土石方"),
    (2, "高速"),            # 高速公路
    (2, "高速公路"),        # 高速公路
    (2, "铁路"),            # 铁路
    (2, "轨道交通"),        # 轨道交通
    (2, "港口"),            # 港口
    (2, "码头"),            # 码头
    (2, "航道"),            # 航道
    (2, "枢纽"),            # 交通枢纽
    (2, "封顶"),            # 封顶大吉
    (2, "建设用地"),        # 建设用地
    (2, "征地"),            # 征地
    (2, "招标"),            # 招标公告

    # +1: 可能是大项目的附属工程 / 建设信号
    (1, "配套工程"),
    (1, "附属工程"),
    (1, "室外工程"),
    (1, "基础设施"),
    (1, "管网工程"),
    (1, "景观绿化"),
    (1, "消防工程"),
    (1, "暖通工程"),
    (1, "智能化工程"),
    (1, "装饰装修"),
    (1, "电梯工程"),
    (1, "工程"),            # 通用"工程"（低权重）
    (1, "通车"),            # 通车运营
    (1, "通车运营"),        # 通车运营
    (1, "竣工"),            # 竣工验收
    (1, "竣工验收"),        # 竣工验收
    (1, "收费站"),          # 收费站
    (1, "交付"),            # 交付使用
    (1, "投入使用"),        # 投入使用
    (1, "获批"),            # 获批建设
    (1, "片区开发"),        # 片区开发
    (1, "选址"),            # 选址公示
]


# ============================================================
# 负向信号：采购、服务、咨询类 — 不是建设工程
# ============================================================
NEGATIVE_SIGNALS: List[Tuple[int, str]] = [
    # -5: 纯采购/服务（与基建无关）
    (-5, "设备采购"),
    (-5, "家具采购"),
    (-5, "服务采购"),
    (-5, "法律服务"),
    (-5, "审计服务"),
    (-5, "评估服务"),
    (-5, "咨询服务"),
    (-5, "物业管理"),
    (-5, "保安服务"),
    (-5, "保洁服务"),
    (-5, "食材配送"),
    (-5, "医疗设备"),
    (-5, "厨房设备"),
    (-5, "办公设备"),
    (-5, "印刷服务"),

    # -4: 技术/检测类服务
    (-4, "抽检"),
    (-4, "检测服务"),
    (-4, "保险服务"),
    (-4, "软件开发"),
    (-4, "系统开发"),
    (-4, "网站建设"),
    (-4, "信息安全"),
    (-4, "等保测评"),
    (-4, "监理服务"),
    (-4, "设计服务"),

    # -3: 咨询/评估/代理（与通信基建无关）
    (-3, "绩效评价"),
    (-3, "PPP咨询"),
    (-3, "招标代理"),
    (-3, "会计审计"),
    (-3, "资产评估"),
    (-3, "造价咨询"),
    (-3, "环评报告"),
    (-3, "可研报告"),
    (-3, "法律服务"),
    (-3, "法律顾问"),

    # -2: 小型维保服务
    (-2, "设备维修"),
    (-2, "零星维修"),
    (-2, "绿化养护"),
    (-2, "车辆维修"),
    (-2, "车辆保险"),
    (-2, "公务用车"),
    (-2, "制服采购"),
    (-2, "办公用品"),
    (-2, "广告服务"),
    (-2, "宣传服务"),

    # -1: 流程性公告（非新项目信号）
    (-1, "更正公告"),
    (-1, "废标公告"),
    (-1, "流标公告"),
    (-1, "中标公告"),
    (-1, "成交公告"),
    (-1, "结果公告"),
    (-1, "暂停公告"),
    (-1, "终止公告"),
    (-1, "澄清公告"),
    (-1, "变更公告"),
]


# ============================================================
# 规模检测：标题中出现规模信息，说明是实体工程
# ============================================================
SCALE_PATTERNS: List[Tuple[int, str]] = [
    (3, r'亿\s*[元圆]'),              # 亿元 → 投资额高
    (3, r'万\s*[平㎡]'),              # 万平米 → 面积大
    (3, r'万\s*平方米'),              # 万平方米
    (3, r'万\s*户'),                  # 万户 → 大型住宅
    (2, r'万\s*[元圆]'),              # 万元
    (2, r'[平㎡]\s*[方米]'),          # 平方米
    (2, r'\d{3,}\s*户'),             # 200户以上住宅
    (2, r'\d+[\.\d]*\s*km'),         # 公里
    (2, r'㎡'),                        # 平方米符号
    (1, r'平米'),                      # 口语化表述
    (1, r'm\s*[²2]'),                # m²
]


# ============================================================
# 项目性质判断（用于内容分析）
# ============================================================
NEW_CONSTRUCTION_KW = ["新建", "新校区", "新院区", "迁建", "新建项目",
                        "新征用地", "新增用地", "一期", "起步区"]
EXPANSION_KW = ["扩建", "改建", "加建", "二期", "三期", "改扩建"]
RENOVATION_KW = ["改造", "修缮", "维修", "翻新", "加固", "装修"]


class RelevanceScorer:
    """项目相关性评分器 — 所有爬虫共用单例"""

    def __init__(self):
        # 预编译正向/负向信号为正则列表（用于快速扫描）
        self._positive = [(score, kw, re.compile(re.escape(kw)))
                          for score, kw in POSITIVE_SIGNALS]
        self._negative = [(score, kw, re.compile(re.escape(kw)))
                          for score, kw in NEGATIVE_SIGNALS]
        self._scale_patterns = [(score, pattern, re.compile(pattern))
                                for score, pattern in SCALE_PATTERNS]
        self._district_patterns = {
            d: re.compile(re.escape(d)) for d in YANTAI_DISTRICTS
        }

    # ----------------------------------------------------------
    # Layer 0: 公告类型预过滤
    # ----------------------------------------------------------
    def is_process_announcement(self, title: str) -> bool:
        """
        判断是否为"流程性公告"（更正、废标、成交等），
        这些不是新项目信号，应直接丢弃。
        """
        process_kw = [
            "更正", "废标", "流标", "终止", "澄清",
            "暂停采购", "恢复采购",
            # "变更"单独太宽泛（会误伤"规划许可证变更批后公布"），
            # "变更公告"也太宽泛（会误伤"工程变更公告"），
            # 只用招标/采购上下文中才明确的"变更"组合：
            "招标变更", "采购变更", "变更采购",
            "中标变更", "成交变更", "合同变更",
        ]
        return any(kw in title for kw in process_kw)

    def is_result_announcement(self, title: str) -> bool:
        """判断是否为结果公告（中标/成交），这些也不是新项目信号"""
        result_kw = ["中标", "成交", "中标候选人", "中标结果",
                      "废标", "流标", "合同公示"]
        return any(kw in title for kw in result_kw)

    # ----------------------------------------------------------
    # Layer 1: 标题加权评分
    # ----------------------------------------------------------
    def score_title(self, title: str) -> Tuple[int, dict]:
        """
        对标题进行加权评分

        返回:
            (总分, {
                "positive": [(得分, "匹配关键词"), ...],
                "negative": [(得分, "匹配关键词"), ...],
                "scale": [(得分, "匹配文本"), ...],
            })

        用法:
            score, detail = scorer.score_title(title)
            if score >= 3:
                include(title)
        """
        detail = {"positive": [], "negative": [], "scale": []}
        total = 0

        # --- 正向信号扫描 ---
        for score, kw, pattern in self._positive:
            if pattern.search(title):
                detail["positive"].append((score, kw))
                total += score

        # --- 负向信号扫描 ---
        for score, kw, pattern in self._negative:
            if pattern.search(title):
                detail["negative"].append((score, kw))
                total += score

        # --- 规模信号扫描 ---
        for score, pattern_str, pattern in self._scale_patterns:
            match = pattern.search(title)
            if match:
                detail["scale"].append((score, match.group()))
                total += score

        return total, detail

    def should_include(self, title: str, threshold: int = 3) -> Tuple[bool, int, dict]:
        """
        快速判断标题是否应纳入结果

        返回:
            (是否纳入, 总分, 评分明细)

        用法:
            should, score, detail = scorer.should_include(title)
            if should:
                results.append(item)
        """
        score, detail = self.score_title(title)
        return score >= threshold, score, detail

    def score_with_label(self, title: str) -> Tuple[int, str]:
        """
        评分 + 质量标签

        返回: (总分, "高质量"|"中等"|"低质量"|"应丢弃")
        """
        score, _ = self.score_title(title)
        if score >= 5:
            return score, "高质量"
        elif score >= 3:
            return score, "中等"
        elif score >= 1:
            return score, "低质量"
        else:
            return score, "应丢弃"

    # ----------------------------------------------------------
    # Layer 2: 详情页内容分析
    # ----------------------------------------------------------
    def extract_content_info(self, content: str, title: str = "") -> dict:
        """
        从详情页正文提取关键结构化信息

        返回:
            {
                "scale": "11.6万㎡" | "",
                "investment": "3.73亿元" | "",
                "district": "黄渤海新区" | "",
                "nature": "新建" | "扩建" | "改造" | "",
            }
        """
        result = {
            "scale": self._extract_scale(content),
            "investment": self._extract_investment(content),
            "district": self._extract_district(content) or self._extract_district(title),
            "nature": self._detect_nature(content),
        }
        return result

    def _extract_scale(self, text: str) -> str:
        """从文本中提取建设规模"""
        # 优先匹配 "XX平方米" 或 "XX万㎡"
        patterns = [
            r'(\d+[\.\d]*)\s*万\s*[平㎡]\s*[方米]',
            r'(\d+[\.\d]*)\s*万\s*㎡',
            r'(\d+[\.\d]*)\s*万\s*平方米',
            r'建筑面积[：:]\s*(\d+[\.\d]*)\s*万?\s*[平㎡]',
            r'建设规模[：:]\s*(\d+[\.\d]*)\s*万?\s*[平㎡]',
            r'(\d+[\.\d]*)\s*[平㎡]\s*[方米]',
            r'(\d+)\s*户',
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                return match.group().strip()
        return ""

    def _extract_investment(self, text: str) -> str:
        """从文本中提取投资金额"""
        patterns = [
            r'(\d+[\.\d]*)\s*亿\s*[元圆]',
            r'投资[额]?\s*[：:约]?\s*(\d+[\.\d]*)\s*[万亿]?\s*[元圆]',
            r'预算[金额]?\s*[：:]\s*(\d+[\.\d]*)\s*[万亿]?\s*[元圆]',
            r'(\d+[\.\d]*)\s*万\s*[元圆]',
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                return match.group().strip()
        return ""

    def _extract_district(self, text: str) -> str:
        """从文本中提取烟台区县名称"""
        if not text:
            return ""
        for district, pattern in self._district_patterns.items():
            if pattern.search(text):
                return district
        return ""

    def _detect_nature(self, text: str) -> str:
        """判断项目性质：新建 / 扩建 / 改造"""
        for kw in NEW_CONSTRUCTION_KW:
            if kw in text:
                return "新建"
        for kw in EXPANSION_KW:
            if kw in text:
                return "扩建"
        for kw in RENOVATION_KW:
            if kw in text:
                return "改造"
        return ""

    # ----------------------------------------------------------
    # 便捷方法：完整分析一条项目
    # ----------------------------------------------------------
    def analyze(self, title: str, content: str = "", source_url: str = "") -> dict:
        """对一条项目做完整的 Layer 0-2 分析"""
        score, detail = self.score_title(title)
        quality = ("高质量" if score >= 5 else
                    "中等" if score >= 3 else
                    "低质量" if score >= 1 else "应丢弃")

        info = self.extract_content_info(content, title) if content else {}

        return {
            "title": title,
            "source_url": source_url,
            "relevance_score": score,
            "quality_label": quality,
            "score_detail": detail,
            "scale_extracted": info.get("scale", ""),
            "investment_extracted": info.get("investment", ""),
            "district_extracted": info.get("district", ""),
            "project_nature": info.get("nature", ""),
            "is_process": self.is_process_announcement(title),
            "is_result": self.is_result_announcement(title),
        }


# 全局单例 — 所有爬虫共用
scorer = RelevanceScorer()
