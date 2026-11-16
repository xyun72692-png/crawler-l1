# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""渲染政府招聘栏目，抽取公告标题与链接"""
import json
import re

from playwright.sync_api import sync_playwright

COLS = [
    ("乐清-就业创业", "https://www.yueqing.gov.cn/col/col1229416590/index.html"),
    ("温州人社-人事考试", "https://hrss.wenzhou.gov.cn/col/col1330455/index.html"),
    ("温州市政府-人事", "https://www.wenzhou.gov.cn/col/col1229180668/index.html"),
]
KEY = re.compile(r"招聘|招考|招录|选调|选聘|引进|编外|劳务派遣|用工|岗位")

out = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True, args=["--no-sandbox"])
    ctx = b.new_context(ignore_https_errors=True, locale="zh-CN")
    page = ctx.new_page()
    for name, url in COLS:
        print("=" * 64)
        print(name, url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            links = page.eval_on_selector_all("a", "els => els.map(e => [e.innerText.trim(), e.href])")
            allart = [(t.replace("\n", " ").strip(), h) for t, h in links
                      if h and ("/art/" in h or "art_" in h)]
            hits = [(t, h) for t, h in allart if t and KEY.search(t)]
            print(f"  文章总数 {len(allart)}，标题命中关键词 {len(hits)}")
            for t, h in allart[:6]:
                print("    [样本]", t[:56])
            for t, h in hits[:20]:
                print("    [命中]", t[:56], "|", h[-46:])
                out.append({"col": name, "title": t, "url": h})
        except Exception as e:
            print("  ERR", type(e).__name__, str(e)[:160])
    b.close()

with open(r"D:\agent-work\data\raw\_gov_jobs.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("saved", len(out))