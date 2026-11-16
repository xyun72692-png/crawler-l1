# -*- coding: utf-8 -*-
"""离线解析已保存的搜索页 HTML：抠 __NEXT_DATA__.props.pageProps.initData。零请求。"""
import json, re, sys

P = r"D:\agent-work\data\raw\_probe_lagou\real_chrome_search.html"
html = open(P, encoding="utf-8").read()
m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
print("next_data_found:", bool(m), "html_bytes:", len(html.encode("utf-8")))
if not m:
    sys.exit(1)
d = json.loads(m.group(1))
pp = d["props"]["pageProps"]
init = pp.get("initData") or {}
print("initData keys:", list(init.keys())[:20])
for k, v in init.items():
    if isinstance(v, list):
        print(f"  list {k}: len={len(v)}")
        if v and isinstance(v[0], dict):
            print("    item0 keys:", list(v[0].keys())[:25])
    elif isinstance(v, (int, str, bool)) or v is None:
        print(f"  scalar {k} = {v!r}"[:120])

jobs = None
for k in ("jobs", "data", "list", "positionList", "result"):
    if isinstance(init.get(k), list) and init[k] and isinstance(init[k][0], dict):
        jobs = init[k]
        print("jobs_key =", k)
        break
if jobs:
    print("jobs_count:", len(jobs))
    j = jobs[0]
    print(json.dumps({kk: j[kk] for kk in list(j.keys())}, ensure_ascii=False)[:1200])
    for j in jobs[:6]:
        print(" -", j.get("positionName") or j.get("name"), "|",
              j.get("salary"), "|", j.get("city"), "|", j.get("companyShortName") or j.get("companyName"),
              "|", (j.get("positionId") or j.get("positionIdEncrypt")))
# 顺带找总数 / 分页线索
for key in ("totalCount", "total", "pageSize", "pageNo"):
    if key in json.dumps(init)[:4000]:
        pass
print("in_init_grep:", {k: re.findall(r'"%s":\s*([^,}]{1,20})' % k, json.dumps(init))[:3]
                        for k in ("totalCount", "pageSize", "pageNo", "total")})