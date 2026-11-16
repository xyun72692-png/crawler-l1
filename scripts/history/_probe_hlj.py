# -*- coding: utf-8 -*-
"""黑龙江省级公共就业平台：候选域名逐个 1 请求（只看 status/标题/字节）。"""
import json, re, time
from pathlib import Path
import requests

FIX = Path(r"D:\agent-work\data\raw\fixtures")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
CANDS = [
    "https://job.hlj.gov.cn/",
    "http://www.hljjob.com/",
    "https://rlzy.hlj.gov.cn/",
    "http://www.hljyjob.com/",
]
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
out = []
for u in CANDS:
    rec = {"url": u}
    try:
        r = s.get(u, timeout=15, allow_redirects=True)
        body = r.content.decode(r.apparent_encoding or "utf-8", "replace")
        t = (re.search(r"(?is)<title>(.*?)</title>", body) or [None, ""])[1].strip()
        v = re.sub(r"(?s)<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body))
        v = re.sub(r"\s+", "", v)
        rec.update({"status": r.status_code, "bytes": len(r.content), "final_url": r.url,
                    "title": t[:60], "visible_chars": len(v)})
    except Exception as e:
        rec["error"] = repr(e)[:120]
    out.append(rec)
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    time.sleep(3)
(FIX / "verify_hlj_cands.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")