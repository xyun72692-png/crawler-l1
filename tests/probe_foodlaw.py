# -*- coding: utf-8 -*-
"""
foodmate 目标站勘察（只读探测，不改任何 crawler 代码）

第一步只做两件事：
  1) 取 robots.txt 并判断
  2) 取列表页 page=1，看 HTML 结构、编码、条目选择器

不抓详情页、不写数据文件。
"""
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源
import sys
import time

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://law.foodmate.net"
LIST = "https://law.foodmate.net/mobile/index.php?moduleid=23&catid=39"

sess = requests.Session()
sess.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def show_resp(tag, r, maxlen=300):
    print("=" * 70)
    print("[%s] %s" % (tag, r.url))
    print("  status      :", r.status_code)
    print("  content-type:", r.headers.get("Content-Type"))
    print("  content-len :", r.headers.get("Content-Length"))
    print("  bytes       :", len(r.content))
    print("  encoding    :", r.encoding, "| apparent:", r.apparent_encoding)
    print("  redirects   :", [h.status_code for h in r.history])
    if maxlen and len(r.text) > maxlen:
        print("  text head   :", repr(r.text[:maxlen]))
    return r


# ---------- 1. robots.txt ----------
print("### 1. robots.txt ###")
try:
    r = sess.get(BASE + "/robots.txt", timeout=20)
    show_resp("robots", r, maxlen=0)
    print("  --- content ---")
    print(r.text[:3000] if r.text else "(空)")
except Exception as e:
    print("  robots 请求失败:", type(e).__name__, e)

time.sleep(2.5)

# ---------- 2. 列表页 ----------
print("")
print("### 2. 列表页 page=1 ###")
try:
    r = sess.get(LIST, timeout=25)
    show_resp("list", r, maxlen=800)
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    html = r.text
    with open(_path_lib(__file__).resolve().parent / "_foodlaw_list1.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  已保存 HTML -> tests\\_foodlaw_list1.html")

    soup = BeautifulSoup(html, "lxml")
    print("  title:", soup.title.get_text(strip=True) if soup.title else "(无)")
    # 看看有多少个 a 标签、常见容器类名
    print("  <a> 总数:", len(soup.find_all("a")))
    for sel in ["li", "tr", "div.list", "ul.list", "div.item", "table"]:
        try:
            print("  select(%-10s) -> %d" % (sel, len(soup.select(sel))))
        except Exception:
            pass
except Exception as e:
    print("  列表页请求失败:", type(e).__name__, e)