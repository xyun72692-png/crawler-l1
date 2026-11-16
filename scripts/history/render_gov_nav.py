# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""渲染政府站首页/导航，找出真正的招聘公告栏目"""
import re

from playwright.sync_api import sync_playwright

SITES = [
    ("乐清市政府", "https://www.yueqing.gov.cn/"),
    ("温州人社局", "https://hrss.wenzhou.gov.cn/"),
    ("温州市政府", "https://www.wenzhou.gov.cn/"),
]
KEY = re.compile(r"招聘|招考|招录|就业|人事|考试|人才|事业|编外|用工|岗位")

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True, args=["--no-sandbox"])
    ctx = b.new_context(ignore_https_errors=True, locale="zh-CN")
    page = ctx.new_page()
    for name, url in SITES:
        print("=" * 64)
        print(name, url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            links = page.eval_on_selector_all(
                "a",
                "els => els.map(e => [e.innerText.trim(), e.href])"
            )
            seen = set()
            hits = []
            for t, h in links:
                t = (t or "").replace("\n", "").strip()
                if not t or len(t) > 24:
                    continue
                if KEY.search(t) and h not in seen:
                    seen.add(h)
                    hits.append((t, h))
            print("  命中栏目", len(hits))
            for t, h in hits[:25]:
                print(f"    {t:22s} {h[:100]}")
        except Exception as e:
            print("  ERR", type(e).__name__, str(e)[:160])
    b.close()