# -*- coding: utf-8 -*-
"""补充：拉「食品检验」全部 4 页（376 条），统计台州/杭州/宁波/温州占比。"""
import json, time, collections
from pathlib import Path
import requests

FIX = Path(r"D:\agent-work\data\raw\fixtures")
BASE = "https://www.zjhr.com:443/010/guestService/guestServiceAction!findTable12List8Page5.action"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://www.zjhr.com/010/client/list.jsp",
                  "X-Requested-With": "XMLHttpRequest"})

allrows = []
total = None
for page in (1, 2, 3, 4):
    data = {"column3": "食品检验", "column56": "", "column57": "", "column10": "",
            "column23": "", "column60": "", "column7": "", "column8": "",
            "column9": "", "q": "0", "page": page, "rows": 100}
    r = s.post(BASE, data=data, timeout=30)
    j = r.json()
    total = j.get("total")
    rows = j.get("rows") or []
    allrows += rows
    print("page %d: %d rows (total=%s)" % (page, len(rows), total))
    if len(rows) < 100:
        break
    time.sleep(4)

c = collections.Counter((x.get("column60") or "-").strip() for x in allrows)
print("抓取条数:", len(allrows), " 报告 total:", total)
for k, v in c.most_common(15):
    print("  %-8s %d  (%.1f%%)" % (k, v, 100.0 * v / max(1, len(allrows))))
for city in ("台州市", "杭州市", "宁波市", "温州市", "丽水市", "金华市"):
    print("  %s = %d" % (city, c.get(city, 0)))

out = {"total": total, "fetched": len(allrows), "dist": c.most_common(30)}
(FIX / "verify_v134_zjhr_spjy_all.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved")