# -*- coding: utf-8 -*-
"""吉林人才网 接口侦察：hr.jlrc.com.cn 的明文 JSON（robots + 1 次列表查询）。"""
import json, re
from pathlib import Path
import requests

FIX = Path(r"D:\agent-work\data\raw\fixtures")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
                  "Referer": "https://www.jlrc.com.cn/ww/b/c/wwbc_result.html"})

# 1) hr 子域 robots
try:
    r = s.get("https://hr.jlrc.com.cn/robots.txt", timeout=20)
    body = r.content.decode(r.apparent_encoding or "utf-8", "replace")
    print("hr robots: %s / %d B / html=%s" % (r.status_code, len(r.content), "<html" in body[:200].lower()))
    print(body[:200].replace("\n", " "))
except Exception as e:
    print("hr robots ERR", e)

# 2) 列表接口
API = "https://hr.jlrc.com.cn/api/admin/sysEnt/getAllPortalJobPage"
params = {"jobName": "", "entName": "", "size": 10, "current": 1}
r = s.get(API, params=params, timeout=25)
print("\napi: %s / %d B / ct=%s" % (r.status_code, len(r.content), r.headers.get("content-type")))
try:
    j = r.json()
except Exception as e:
    print("非 JSON:", e); print(r.text[:400]); raise SystemExit

(FIX / "probe_jlrc_api.json").write_text(
    json.dumps(j, ensure_ascii=False, indent=2)[:200000], encoding="utf-8")
print("顶层键:", list(j.keys()))
d = j.get("data") or {}
print("data 键:", list(d.keys()) if isinstance(d, dict) else type(d))
print("total =", d.get("total") if isinstance(d, dict) else None)
rows = None
for k in ("records", "rows", "list", "content"):
    if isinstance(d, dict) and isinstance(d.get(k), list):
        rows = d[k]; print("列表字段名:", k, " 条数:", len(rows)); break
if rows:
    r0 = rows[0]
    print("\n第一条记录字段（%d 个）：" % len(r0))
    for k, v in r0.items():
        sv = str(v)
        print("   %-22s %s" % (k, sv[:70]))
    (FIX / "probe_jlrc_api_row1.json").write_text(
        json.dumps(r0, ensure_ascii=False, indent=2), encoding="utf-8")