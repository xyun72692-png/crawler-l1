# -*- coding: utf-8 -*-
"""核实 方案-v13.4 里关于 zjhr.com 的三个数字：
   total=15171 / 最新100条台州90 / 「食品检验」376条中台州365
只读、GET robots + 2 次 POST，间隔 4 秒。
"""
import json, time, sys, collections
from pathlib import Path
import requests

FIX = Path(r"D:\agent-work\data\raw\fixtures")
BASE = "https://www.zjhr.com:443/010/guestService/guestServiceAction!findTable12List8Page5.action"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")

s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://www.zjhr.com/010/client/list.jsp",
                  "X-Requested-With": "XMLHttpRequest"})

out = {}

# 1) robots
try:
    r = s.get("https://www.zjhr.com/robots.txt", timeout=15)
    body = r.text[:400]
    out["robots"] = {"status": r.status_code, "bytes": len(r.content),
                     "looks_html": "<html" in body.lower(), "head": body[:200]}
    print("robots:", r.status_code, len(r.content), "html" if "<html" in body.lower() else "txt")
except Exception as e:
    out["robots"] = {"error": repr(e)}
    print("robots error", e)
time.sleep(4)

def post(column3=""):
    data = {"column3": column3, "column56": "", "column57": "", "column10": "",
            "column23": "", "column60": "", "column7": "", "column8": "",
            "column9": "", "q": "0", "page": 1, "rows": 100}
    r = s.post(BASE, data=data, timeout=30)
    j = r.json()
    return r.status_code, j

# 2) 全量
st, j = post()
rows = j.get("rows") or []
out["all"] = {"status": st, "total": j.get("total"), "rows": len(rows),
              "keys": sorted(rows[0].keys())[:30] if rows else []}
c = collections.Counter((x.get("column60") or "-").strip() for x in rows)
out["all"]["loc_top"] = c.most_common(12)
print("all: total=%s rows=%d" % (j.get("total"), len(rows)))
print("  loc:", c.most_common(8))
time.sleep(4)

# 3) 食品检验
st2, j2 = post("食品检验")
rows2 = j2.get("rows") or []
c2 = collections.Counter((x.get("column60") or "-").strip() for x in rows2)
out["spjy"] = {"status": st2, "total": j2.get("total"), "rows": len(rows2),
               "loc_top": c2.most_common(12)}
print("食品检验: total=%s rows=%d" % (j2.get("total"), len(rows2)))
print("  loc:", c2.most_common(8))
if rows2:
    out["spjy"]["sample"] = [{k: rows2[0].get(k) for k in ("column3", "column60", "column2", "column4")}]
    print("  sample:", out["spjy"]["sample"])

(FIX / "verify_v134_zjhr.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved ->", FIX / "verify_v134_zjhr.json")