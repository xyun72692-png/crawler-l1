# -*- coding: utf-8 -*-
import re

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B = "https://yq.wzrc.net/index.php?m=&c=Jobs&a=jobs_list"


def peek(qs):
    r = requests.get(B + qs, headers=H, timeout=25, verify=False)
    r.encoding = r.apparent_encoding
    s = BeautifulSoup(r.text, "lxml")
    n = len(s.select("div.J_jobsList"))
    pg = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
    names = [a.get_text(strip=True)[:18] for a in s.select(".td-j-name a")]
    return n, (max(pg) if pg else 1), names[:3]


for qs in ["", "&wage=60", "&wage=61", "&wage=60&page=2", "&wage=60&page=5",
           "&wage=60&page=10", "&page=30", "&page=100", "&page=229"]:
    label = qs if qs else "(全站)"
    print(f"{label:24s}", peek(qs))