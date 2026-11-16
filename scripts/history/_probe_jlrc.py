# -*- coding: utf-8 -*-
"""吉林人才网 jlrc.com.cn 侦察：robots + 首页导航链接（2 请求）。"""
import re, json
from pathlib import Path
from urllib.parse import urljoin
import requests

FIX = Path(r"D:\agent-work\data\raw\fixtures")
FIX.mkdir(parents=True, exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
BASE = "https://www.jlrc.com.cn"
out = {}

# 1) robots
try:
    r = s.get(BASE + "/robots.txt", timeout=20)
    body = r.content.decode(r.apparent_encoding or "utf-8", "replace")
    out["robots"] = {"status": r.status_code, "bytes": len(r.content), "body": body[:800],
                     "is_html": "<html" in body[:300].lower()}
    print("robots: %s / %d B / html=%s" % (r.status_code, len(r.content), out["robots"]["is_html"]))
    print(body[:500])
except Exception as e:
    out["robots"] = {"error": repr(e)}
    print("robots ERR", e)

# 2) 首页
try:
    r = s.get(BASE + "/ww/index.html", timeout=25)
    raw = r.content
    enc = r.apparent_encoding or "utf-8"
    body = raw.decode(enc, "replace")
    (FIX / "probe_jlrc_home.html").write_bytes(raw)
    title = (re.search(r"(?is)<title>(.*?)</title>", body) or [None, ""])[1].strip()
    out["home"] = {"status": r.status_code, "bytes": len(raw), "encoding": enc, "title": title[:80]}
    print("\nhome: %s / %d B / enc=%s / title=%s" % (r.status_code, len(raw), enc, title[:60]))

    # 抽链接
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
    seen, rows = set(), []
    for href, t in links:
        txt = re.sub(r"<[^>]+>", "", t).strip()
        u = urljoin(BASE + "/ww/index.html", href)
        if u in seen:
            continue
        seen.add(u)
        if re.search(r"(job|zhaopin|rc|list|search|职位|招聘|找工作|岗位|求职)", u + txt, re.I):
            rows.append({"text": txt[:24], "url": u})
    out["nav"] = rows[:60]
    print("疑似列表/职位链接 %d 个：" % len(rows))
    for x in rows[:40]:
        print("   %-22s %s" % (x["text"], x["url"][:90]))
except Exception as e:
    out["home"] = {"error": repr(e)}
    print("home ERR", e)

(FIX / "probe_jlrc.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nsaved ->", FIX / "probe_jlrc.json")