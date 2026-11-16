# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""用系统 Edge 渲染 JS 页面（政府站栏目是 JS 动态加载，requests 拿不到列表）"""
import re
import sys

from playwright.sync_api import sync_playwright

TARGETS = [
    ("乐清-人事信息", "https://www.yueqing.gov.cn/col/col1229249412/index.html"),
    ("乐清-通知公告", "https://www.yueqing.gov.cn/col/col1229887933/index.html"),
]

with sync_playwright() as p:
    try:
        browser = p.chromium.launch(channel="msedge", headless=True, args=["--no-sandbox"])
        print("启动方式: 系统 Edge (channel=msedge)")
    except Exception as e:
        print("msedge 启动失败:", e)
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        print("启动方式: 内置 chromium")

    ctx = browser.new_context(ignore_https_errors=True, locale="zh-CN",
                              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36")
    page = ctx.new_page()

    for name, url in TARGETS:
        print("=" * 60)
        print(name, url)
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2500)
            html = page.content()
            print("  渲染后长度", len(html))
            arts = re.findall(r'href="([^"]*(?:/art/|art_)[^"]*)"[^>]*>([^<]{4,80})<', html)
            print("  文章链接", len(arts))
            for h, t in arts[:12]:
                print("    ", t.strip()[:50], "|", h[-50:])
            if not arts:
                body = page.inner_text("body")
                print("  页面文本前 400 字:", re.sub(r"\s+", " ", body)[:400])
                open(rf"D:\agent-work\data\raw\_rendered_{name}.html", "w", encoding="utf-8").write(html)
        except Exception as e:
            print("  ERR", type(e).__name__, str(e)[:200])

    browser.close()
print("done")