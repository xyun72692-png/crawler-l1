# -*- coding: utf-8 -*-
"""验证人社部「省级公共就业服务平台」名单页是否真能 1 请求拿到各省直链。"""
import re, json, sys
from pathlib import Path
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
url = "http://job.mohrss.gov.cn/jy/index.jhtml"
try:
    r = requests.get(url, timeout=25, headers={"User-Agent": UA})
except Exception as e:
    print("ERR", e); sys.exit(0)

b = r.content.decode("utf-8", "replace")
print("status=%s bytes=%d" % (r.status_code, len(r.content)))
text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", b)
links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S)
rows = []
for href, t in links:
    name = re.sub(r"<[^>]+>", "", t).strip()
    if re.search(r"(省|自治区|市|兵团)", name) and len(name) <= 20:
        rows.append((name, href))
print("疑似省级链接 %d 个：" % len(rows))
for n, u in rows[:40]:
    print("   %-14s %s" % (n, u[:70]))

FIX = Path(r"D:\agent-work\data\raw\fixtures")
FIX.mkdir(parents=True, exist_ok=True)
(FIX / "verify_mohrss_links.json").write_text(
    json.dumps({"status": r.status_code, "bytes": len(r.content), "links": rows},
               ensure_ascii=False, indent=2), encoding="utf-8")
print("saved")