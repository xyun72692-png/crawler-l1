# -*- coding: utf-8 -*-
"""探测温州人才网全温州×双休×薪资档的页数规模"""
import re

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B = "https://www.wzrc.net/index.php?m=&c=Jobs&a=jobs_list"


def peek(qs):
    r = requests.get(B + qs, headers=H, timeout=25, verify=False)
    r.encoding = r.apparent_encoding
    s = BeautifulSoup(r.text, "lxml")
    n = len(s.select("div.J_jobsList"))
    pg = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
    return n, (max(pg) if pg else 1)


print("=== 全温州 ===")
for label, qs in [
    ("全站", ""),
    ("双休", "&jobtag=147"),
    ("双休+5K-10K", "&jobtag=147&wage=60"),
    ("双休+10K以上", "&jobtag=147&wage=61"),
    ("双休+3K-5K(边界)", "&jobtag=147&wage=59"),
    ("5K-10K(不筛双休)", "&wage=60"),
    ("10K以上(不筛双休)", "&wage=61"),
]:
    print(f"  {label:22s}", peek(qs))

print()
print("=== 各区×双休 ===")
for code, name in [("shibenji", "市本级"), ("luchengqu", "鹿城区"), ("haiqu", "瓯海区"),
                   ("longwanqu", "龙湾区"), ("dongtouxian", "洞头区"), ("leqingshi", "乐清市"),
                   ("ruianshi", "瑞安市"), ("yongjiaxian", "永嘉县"), ("wenchengxian", "文成县"),
                   ("pingyangxian", "平阳县"), ("taishunxian", "泰顺县"), ("cangnanxian", "苍南县"),
                   ("longgangshi", "龙港市"), ("oujiangkou", "海经区")]:
    print(f"  {name:6s}", peek("&citycategory=" + code + "&jobtag=147"))

print()
print("=== 行业(trade)×双休 试探 ===")
for code, name in [("11", "贸易/进出口"), ("4", "互联网/电子商务"), ("22", "广告/市场推广"),
                   ("24", "影视/媒体/艺术/出版"), ("12", "批发/零售"), ("3", "通信")]:
    print(f"  {name:20s}", peek("&trade=" + code + "&jobtag=147"))