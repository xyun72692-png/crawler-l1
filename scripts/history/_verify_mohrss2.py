# -*- coding: utf-8 -*-
"""统计人社部名单页里的省级公共就业平台直链（用于核实「1 请求拿 N 省」）。"""
import re, json
from pathlib import Path

p = Path(r"D:\agent-work\data\raw\fixtures\verify_mohrss_page.html")
b = p.read_text(encoding="utf-8", errors="replace")
urls = [u for u in re.findall(r'href="([^"]+)"', b) if u.startswith("http")]
uniq = []
for u in urls:
    if u not in uniq:
        uniq.append(u)
print("http 链接总数:", len(urls), " 去重:", len(uniq))
for u in uniq:
    print("  ", u)
Path(r"D:\agent-work\data\raw\fixtures\verify_mohrss_prov.json").write_text(
    json.dumps(uniq, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved")