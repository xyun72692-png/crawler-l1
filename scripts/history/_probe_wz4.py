# -*- coding: utf-8 -*-
"""测关键词搜索页数（找安全抓取量），并验证 key 与 jobtag 能否组合"""
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B = "https://www.wzrc.net/index.php?m=&c=Jobs&a=jobs_list&citycategory=wenzhou"

WORDS = ["外贸", "国际贸易", "进出口", "报关", "单证", "跨境", "货代", "国际商务", "商务英语",
         "剪辑", "短视频", "视频", "新媒体", "抖音", "拍摄", "摄影", "后期", "账号运营", "内容运营",
         "直播", "电商", "带货", "淘宝", "天猫", "运营", "主播", "美工"]


def peek(qs):
    r = requests.get(B + qs, headers=H, timeout=25, verify=False)
    r.encoding = r.apparent_encoding
    s = BeautifulSoup(r.text, "lxml")
    n = len(s.select("div.J_jobsList"))
    pg = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
    return n, (max(pg) if pg else 1)


print("=== 单词页数 ===")
total = 0
for w in WORDS:
    n, p = peek("&key=" + quote(w))
    flag = "  <== 疑似失效" if p > 200 else ""
    if p <= 200:
        total += p
    print(f"  {w:8s} {p:4d} 页{flag}")
print("  安全合计", total, "页")

print()
print("=== key + jobtag=147 组合验证 ===")
for w in ["外贸", "剪辑", "直播"]:
    print(f"  {w:6s}", peek("&key=" + quote(w) + "&jobtag=147"))