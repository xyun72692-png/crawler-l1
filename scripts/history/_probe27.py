# -*- coding: utf-8 -*-
import re

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
     "Accept-Language": "zh-CN,zh;q=0.9"}

# 1) 通知公告栏目
for col in ["1229887933", "1229249412"]:
    u = f"https://www.yueqing.gov.cn/col/col{col}/index.html"
    r = requests.get(u, headers=H, timeout=20, verify=False)
    r.encoding = r.apparent_encoding
    s = BeautifulSoup(r.text, "lxml")
    arts = [(a.get_text(strip=True), a["href"]) for a in s.find_all("a", href=True) if "/art/" in a["href"]]
    print(f"== col{col} {r.status_code} len={len(r.text)} art={len(arts)}")
    for t, h in arts[:8]:
        print("    ", t[:50], "|", h[-46:])

# 2) 站内搜索
print()
print("=== 站内搜索尝试 ===")
for su in [
    "https://www.yueqing.gov.cn/jsearchfront/search.do?websiteid=330382000000000&q=%E6%8B%9B%E8%81%98&p=1&pg=&tp=0&sort=&sw=&serviceid=&replystyle=&cateid=&fuzzy=&tpl=&q1=&q2=&q3=",
    "https://www.yueqing.gov.cn/jsearchfront/search.do?q=%E6%8B%9B%E8%81%98",
]:
    try:
        r = requests.get(su, headers=H, timeout=20, verify=False)
        r.encoding = r.apparent_encoding
        print(f"  {r.status_code} len={len(r.text)} {su[:90]}")
        s = BeautifulSoup(r.text, "lxml")
        arts = [(a.get_text(strip=True), a["href"]) for a in s.find_all("a", href=True) if "/art/" in a["href"] or "art_" in a["href"]]
        print("   结果条数", len(arts))
        for t, h in arts[:6]:
            print("      ", t[:50], "|", h[-46:])
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:60])

# 3) 乐清人才网 政府/事业单位 分类
print()
print("=== yqrc trade 分类 ===")
for code, name in [("42", "政府部门/事业单位"), ("11", "贸易进出口"), ("45", "其他行业")]:
    u = f"https://www.yqrc.com/job?trade={code}"
    r = requests.get(u, headers=H, timeout=25, verify=False)
    r.encoding = r.apparent_encoding
    s = BeautifulSoup(r.text, "lxml")
    n = len(s.select("div.jobs-item"))
    pg = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
    print(f"  trade={code} {name}: {n} 条/页, maxpage={max(pg) if pg else 1}")