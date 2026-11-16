# -*- coding: utf-8 -*-
"""侦察温州人才网主站：地区筛选参数、关键词搜索、分站"""
import re

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B = "https://www.wzrc.net/index.php?m=&c=Jobs&a=jobs_list"


def peek(qs, label=""):
    try:
        r = requests.get(B + qs, headers=H, timeout=25, verify=False)
        r.encoding = r.apparent_encoding
        s = BeautifulSoup(r.text, "lxml")
        n = len(s.select("div.J_jobsList"))
        pg = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
        names = [(a.get_text(strip=True) or "")[:20] for a in s.select(".td-j-name a")]
        return n, (max(pg) if pg else 1), names[:3]
    except Exception as e:
        return -1, 0, [type(e).__name__]


print("=== 基础 ===")
for qs in ["", "&page=2"]:
    print(f"{qs or '(全站)':16s}", peek(qs))

print()
print("=== 关键词搜索 ===")
for kw in ["外贸", "剪辑", "短视频", "直播", "电商", "跨境电商", "新媒体"]:
    from urllib.parse import quote
    qs = "&keyword=" + quote(kw)
    print(f"keyword={kw:8s}", peek(qs))

print()
print("=== 地区筛选 ===")
for code in ["luchengqu", "longwanqu", "ouhaiqu", "dongtouxian", "ruianshi",
             "yongjia", "pingyang", "cangnan", "wencheng", "taishun", "longgang", "haijingqu"]:
    qs = "&citycategory=" + code
    print(f"{code:14s}", peek(qs))

print()
print("=== 筛选码表（从全站页提取）===")
r = requests.get(B, headers=H, timeout=25, verify=False)
r.encoding = r.apparent_encoding
pairs = re.findall(r"location\.href='/index\.php\?m=&c=Jobs&a=jobs_list&(\w+)=([\w\u4e00-\u9fa5~%/\.\-]+)'\"[^>]*>([^<]{1,12})<", r.text)
import collections
g = collections.defaultdict(list)
for k, v, t in pairs:
    g[k].append((v, t))
for k, v in g.items():
    print(f"-- {k} ({len(v)})", " ".join(f"{t}={c}" for c, t in v[:30]))