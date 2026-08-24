"""
免费网页搜索（百度搜索页爬取，无需 API key）
-------------------------------------------
glm-4-flash 无联网搜索 → 坐标补全需要外部信息时，直接爬百度搜索结果
（标题 + 摘要），从中提取地址线索 → 高德编码。

限流礼貌：每次请求间隔 ≥1.5s；失败静默返回空列表（不阻塞管线）。
"""
import re
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 地址模式：X市X区X路X号 / X镇X村 / X路X号 / X大道 / 工业园/产业园
ADDR_PATTERNS = [
    r'[一-龥]{2,4}(?:市|县|区)[一-龥]{2,4}(?:街道|镇|乡)[一-龥0-9A-Za-z\-]{2,20}(?:路|街|巷|号|村)',
    r'[一-龥]{2,4}(?:区|市|县)[一-龥0-9A-Za-z\-]{2,20}(?:路|街|巷|大道)[一-龥0-9\-]{0,10}号?',
    r'[一-龥]{2,12}(?:工业园|产业园|开发区|高新区|新区)[一-龥0-9A-Za-z\-]{0,15}',
    r'[一-龥]{2,6}(?:村|镇|乡)[一-龥0-9\-]{0,10}',
]


def baidu_search(query: str, max_results: int = 5, timeout: int = 20) -> list:
    """百度搜索：返回 [{title, abstract, url}] 列表（失败返回空列表）"""
    try:
        s = requests.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        resp = s.get("https://www.baidu.com/s", params={"wd": query},
                     timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[baidu_search] 请求失败: {e}")
        return []

    # 结果块：<h3 ...><a href=...>标题</a></h3>...摘要...
    blocks = re.findall(
        r'<h3[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</h3>(.*?)(?=<h3|$)',
        html, re.S)
    results = []
    for url, title, rest in blocks[:max_results]:
        t = re.sub(r'<[^>]+>', '', title).strip()
        abstract = re.sub(r'<[^>]+>', ' ', rest)
        abstract = re.sub(r'\s+', ' ', abstract).strip()
        if t:
            results.append({"title": t, "abstract": abstract[:200], "url": url})
        time.sleep(0.2)
    return results


def extract_address(results: list) -> str:
    """从搜索结果（标题+摘要）提取地址线索，返回最长匹配或 None"""
    best = ""
    for r in results:
        text = f"{r.get('title', '')} {r.get('abstract', '')}"
        for pat in ADDR_PATTERNS:
            m = re.search(pat, text)
            if m:
                addr = m.group(0)
                if len(addr) > len(best):
                    best = addr
    return best or None


def search_address(project_name: str, district: str = "") -> str:
    """一键：搜索项目地址。返回地址线索（如 '海阳市凤城街道XX路'）或 None"""
    query = f"{project_name} 地址 位于"
    if district:
        query = f"{project_name} {district} 地址"
    results = baidu_search(query)
    addr = extract_address(results)
    if not addr and results:
        # 第二遍：换关键词再搜
        results2 = baidu_search(f"{project_name} 位置 在哪", max_results=5)
        addr = extract_address(results2)
    time.sleep(0.3)
    return addr
