# -*- coding: utf-8 -*-
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B = "https://www.wzrc.net/index.php?m=&c=Jobs&a=jobs_list&citycategory=wenzhou"


def peek(qs):
    r = requests.get(B + qs, headers=H, timeout=25, verify=False)
    r.encoding = r.apparent_encoding
    s = BeautifulSoup(r.text, "lxml")
    pg = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
    return (max(pg) if pg else 1)


WORDS = ["抖音运营", "抖音直播", "直播带货", "直播主播", "直播助理", "电商运营",
         "短视频运营", "视频剪辑", "新媒体运营", "外贸业务", "跨境电商运营",
         "运营专员", "店铺运营", "电商美工", "拍摄剪辑"]
for w in WORDS:
    print("%-12s %4d 页" % (w, peek("&key=" + quote(w))))