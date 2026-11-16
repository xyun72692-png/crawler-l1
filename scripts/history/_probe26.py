# -*- coding: utf-8 -*-
import re

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
     "Accept-Language": "zh-CN,zh;q=0.9"}

CANDS = [
    "https://www.yueqing.gov.cn/module/jpage/dataproxy.jsp?startrecord=1&endrecord=20&perpage=20&columnid=1229249412&unitid=598618&webid=1828",
    "https://www.yueqing.gov.cn/module/web/jpage/dataproxy.jsp?startrecord=1&endrecord=20&perpage=20&columnid=1229249412&unitid=598618&webid=1828&path=/&language=zh-cn",
    "https://www.yueqing.gov.cn/col/col1229249412/index_1.html",
]
for u in CANDS:
    try:
        r = requests.get(u, headers=H, timeout=20, verify=False)
        r.encoding = r.apparent_encoding
        t = r.text
        n_art = len(re.findall(r"/art/", t))
        print("===", r.status_code, len(t), "art链接", n_art, u[:110])
        if n_art == 0:
            print("   ", re.sub(r"\s+", " ", t)[:300])
    except Exception as e:
        print("ERR", u[:80], type(e).__name__, str(e)[:80])

print()
print("=== 温州人社局 首页栏目 ===")
r = requests.get("https://hrss.wenzhou.gov.cn/", headers=H, timeout=25, verify=False)
r.encoding = r.apparent_encoding
s = BeautifulSoup(r.text, "lxml")
seen = set()
for a in s.find_all("a", href=True):
    t = a.get_text(strip=True)
    h = a["href"]
    if not t or len(t) > 20:
        continue
    if any(k in t for k in ["招聘", "考试", "公示", "公告", "就业", "人才", "事业单位"]) and h not in seen:
        seen.add(h)
        print(f"  {t:20s} {h[:100]}")