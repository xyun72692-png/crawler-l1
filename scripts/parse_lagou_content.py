# -*- coding: utf-8 -*-
"""深挖 initData.content 结构（离线）。"""
from pathlib import Path as _Path
import json, re

P = str(_Path(__file__).resolve().parents[1] / "data" / "raw" / "_probe_lagou" / "real_chrome_search.html")
html = open(P, encoding="utf-8").read()
d = json.loads(re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S).group(1))
init = d["props"]["pageProps"]["initData"]
c = init["content"]
print("content type:", type(c).__name__, "keys:", list(c.keys())[:20] if isinstance(c, dict) else "")
if isinstance(c, dict):
    for k, v in c.items():
        desc = f"{type(v).__name__}"
        if isinstance(v, list):
            desc += f" len={len(v)}"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            desc += f" = {str(v)[:60]}"
        elif isinstance(v, dict):
            desc += f" keys={list(v.keys())[:12]}"
        print(" ", k, "->", desc)
    pr = c.get("positionResult") or {}
    if pr:
        print("\npositionResult keys:", list(pr.keys()))
        res = pr.get("result") or []
        print("result len:", len(res))
        for k in ("totalCount", "pageSize", "pageNo"):
            print(" ", k, "=", pr.get(k))
        if res:
            j = res[0]
            print("\nitem0 keys:", list(j.keys()))
            print(json.dumps(j, ensure_ascii=False)[:1500])
            print("\n前 8 条：")
            for j in res[:8]:
                print("  -", j.get("positionName"), "|", j.get("salary"), "|", j.get("city"),
                      j.get("district"), "|", j.get("companyShortName"), "|",
                      j.get("positionId"), "|", j.get("positionLables"), "|", j.get("createTime"))