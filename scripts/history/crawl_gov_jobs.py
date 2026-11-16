# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""政府渠道招聘公告：抓列表 → 抓正文 → 抽学历/薪资/地点 → 输出 JSON

数据源（实测有招聘公告的两个栏目）：
  温州市政府 [人事]        https://www.wenzhou.gov.cn/col/col1229180668/index.html
  温州人社局 人事考试       https://hrss.wenzhou.gov.cn/col/col1330455/index.html
  （乐清市政府"人事信息"栏目实测全是干部任免通知，"就业创业"栏目全是社保补贴公示，
   均无企业/事业单位招聘内容 → 乐清本地招聘只能来自招聘网站与企业）

判读：公务员遴选、事业单位统考类公告基本要求本科以上；真正可能有
      「大专/不限学历」的是编外人员、劳务派遣、工勤技能岗。
      所以抓正文后按学历关键词分组，不要只看标题。
"""
import json
import re
import time

import requests
from playwright.sync_api import sync_playwright

COLS = [
    ("温州市政府-人事", "https://www.wenzhou.gov.cn/col/col1229180668/index.html", 2),
    ("温州人社-人事考试", "https://hrss.wenzhou.gov.cn/col/col1330455/index.html", 2),
]
KEY = re.compile(r"招聘|招考|招录|选调|选聘|引进|编外|劳务派遣|用工")
EDU_LOW = re.compile(r"大专|专科|高中|中专|中技|职高|学历不限|不限学历")
EDU_HIGH = re.compile(r"本科|硕士|研究生|博士")
LABOR = re.compile(r"编外|劳务派遣|合同制|工勤|辅助岗|辅助人员")

HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}


def get_next_pages(page, base, n):
    """jcms 列表分页通常是 index_1.html、index_2.html"""
    urls = [base]
    stem, _, tail = base.rpartition("/index.html")
    for i in range(1, n):
        urls.append(f"{stem}/index_{i}.html")
    return urls


rows = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True, args=["--no-sandbox"])
    ctx = b.new_context(ignore_https_errors=True, locale="zh-CN")
    page = ctx.new_page()
    for name, base, pages in COLS:
        for u in get_next_pages(page, base, pages):
            try:
                page.goto(u, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)
                links = page.eval_on_selector_all("a", "els => els.map(e => [e.innerText.trim(), e.href])")
                got = 0
                for t, h in links:
                    t = (t or "").replace("\n", " ").strip()
                    if not t or not h or ("/art/" not in h and "art_" not in h):
                        continue
                    if not KEY.search(t):
                        continue
                    rows.append({"col": name, "title": t, "url": h})
                    got += 1
                print(f"{name} {u[-28:]} 命中 {got}")
            except Exception as e:
                print("ERR", u[-30:], type(e).__name__, str(e)[:80])
    b.close()

# 去重
seen = set()
uniq = []
for r in rows:
    if r["url"] in seen:
        continue
    seen.add(r["url"])
    uniq.append(r)
print("公告总数", len(uniq))

sess = requests.Session()
sess.headers.update(HEAD)
for i, r in enumerate(uniq, 1):
    try:
        resp = sess.get(r["url"], timeout=25, verify=False)
        resp.encoding = resp.apparent_encoding
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text)
        r["body_len"] = len(text)
        r["has_low_edu"] = bool(EDU_LOW.search(text))
        r["has_high_edu"] = bool(EDU_HIGH.search(text))
        r["is_labor"] = bool(LABOR.search(text))
        r["in_yueqing"] = "乐清" in text
        m = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})", text[:600])
        r["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""
        # 抓学历相关的原句，便于人工核
        snippet = ""
        mm = EDU_LOW.search(text)
        if mm:
            snippet = text[max(0, mm.start() - 60):mm.start() + 90]
        r["edu_snippet"] = snippet
    except Exception as e:
        r["body_len"] = 0
        r["err"] = f"{type(e).__name__}: {str(e)[:60]}"
    if i % 10 == 0:
        print("  正文进度", i, "/", len(uniq))
    time.sleep(0.8)

with open(r"D:\agent-work\data\raw\gov_jobs.json", "w", encoding="utf-8") as f:
    json.dump(uniq, f, ensure_ascii=False, indent=2)

low = [r for r in uniq if r.get("has_low_edu")]
yq = [r for r in uniq if r.get("in_yueqing")]
lab = [r for r in uniq if r.get("is_labor")]
print()
print(f"公告 {len(uniq)} 条；正文提到大专/高中/中专/不限学历 {len(low)} 条；提到乐清 {len(yq)} 条；编外/劳务派遣 {len(lab)} 条")
print()
print("=== 提到大专及以下的公告 ===")
for r in low:
    print(f"  [{r['date']}] {r['title'][:52]}")
    print(f"      乐清={r['in_yueqing']} 编外={r['is_labor']} | {r['edu_snippet'][:110]}")