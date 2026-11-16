# -*- coding: utf-8 -*-
"""详情页超时诊断：列表页正常但详情页 45 秒无响应，逐项排查。"""
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")


LIST = "https://law.foodmate.net/mobile/index.php?moduleid=23&catid=39"
DETAIL_M = "https://law.foodmate.net/mobile/index.php?moduleid=23&itemid=239621"
DETAIL_PC = "https://law.foodmate.net/index.php?moduleid=23&itemid=239621"


def attempt(tag, sess, url, method="GET", timeout=20, **kw):
    t0 = time.time()
    try:
        if method == "HEAD":
            r = sess.head(url, timeout=timeout, allow_redirects=False, **kw)
        else:
            r = sess.get(url, timeout=timeout, **kw)
        dt = time.time() - t0
        print("  [%-16s] %s  status=%s bytes=%s %.1fs" %
              (tag, method, r.status_code, len(r.content), dt))
        return r
    except Exception as e:
        dt = time.time() - t0
        print("  [%-16s] %s  FAILED %.1fs  %s: %s" %
              (tag, method, dt, type(e).__name__, str(e)[:90]))
        return None


s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

print("### A. HEAD 详情页（看有没有响应头）###")
attempt("head-detail", s, DETAIL_M, method="HEAD", timeout=15)
time.sleep(2)

print()
print("### B. 先访问列表页，再访问详情页（同一 Session，带 cookie）###")
r = attempt("list-first", s, LIST, timeout=20)
print("    cookies:", list(s.cookies.keys()) if s.cookies else "(none)")
time.sleep(2.5)
attempt("detail-after", s, DETAIL_M, timeout=30)
time.sleep(2.5)

print()
print("### C. PC 版详情页（去掉 /mobile/）###")
attempt("detail-pc", s, DETAIL_PC, timeout=30)
time.sleep(2.5)

print()
print("### D. 换个 itemid 试试（也许是个别条目慢）###")
attempt("detail-other", s, "https://law.foodmate.net/mobile/index.php?moduleid=23&itemid=239616", timeout=25)