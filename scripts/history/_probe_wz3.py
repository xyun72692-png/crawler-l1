# -*- coding: utf-8 -*-
"""测各行业 × 高薪档的页数（不筛双休），找量小又精准的抓取组合"""
import re

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B = "https://www.wzrc.net/index.php?m=&c=Jobs&a=jobs_list&citycategory=wenzhou"


def peek(qs):
    r = requests.get(B + qs, headers=H, timeout=25, verify=False)
    r.encoding = r.apparent_encoding
    s = BeautifulSoup(r.text, "lxml")
    n = len(s.select("div.J_jobsList"))
    pg = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
    return n, (max(pg) if pg else 1)


TRADES = [("4", "互联网/电子商务"), ("11", "贸易/进出口"), ("12", "批发/零售"),
          ("22", "广告/市场推广"), ("24", "影视/媒体/艺术/出版"), ("3", "通信"),
          ("35", "餐饮/娱乐/休闲"), ("15", "家具/家电/工艺"), ("13", "消费品")]
print("=== 行业 × 5K-10K（不筛双休）===")
total = 0
for code, name in TRADES:
    n, p = peek("&trade=%s&wage=60" % code)
    total += p
    print(f"  {name:20s} {n} 条/页, {p} 页")
print("  合计页数", total)

print()
print("=== 行业 × 10K以上（不筛双休）===")
total2 = 0
for code, name in TRADES:
    n, p = peek("&trade=%s&wage=61" % code)
    total2 += p
    print(f"  {name:20s} {n} 条/页, {p} 页")
print("  合计页数", total2)