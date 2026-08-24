# -*- coding: utf-8 -*-
"""调试热力图：抓 404 + 检查地图实例内部状态 + 截图"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        console_lines = []
        notfound = []
        page.on("console", lambda m: console_lines.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: console_lines.append(f"[PAGEERROR] {e}"))
        page.on("response", lambda r: notfound.append(f"{r.status} {r.url}") if r.status >= 400 else None)

        page.goto("http://localhost:8000/index.html", wait_until="networkidle", timeout=60000)
        print("页面加载完成, 等待地图入场动画...")
        time.sleep(6)

        # 点击热力图按钮
        page.locator(".bottom-menu-item", has_text="热力图").click()
        time.sleep(4)

        # 深入检查：initMap 是全局函数，找地图实例
        state = page.evaluate("""() => {
          const out = { found: false };
          // 尝试从 canvas 反查，或者看是否有暴露的实例
          // three-map.js 里如果有 window.map = this 之类
          return out;
        }""")
        page.screenshot(path="d:/googledownload/wangluobu_vscode/scripts/heat_debug_2_heat.png")

        print("=== 404/错误响应 ===")
        for u in notfound:
            print(u)
        print("=== console ===")
        for l in console_lines:
            print(l)
        browser.close()

if __name__ == "__main__":
    main()
