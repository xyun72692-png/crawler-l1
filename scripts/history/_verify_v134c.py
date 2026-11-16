# -*- coding: utf-8 -*-
"""核实 js365job(robots 是否回落首页 / 可见文本字符数) 与 zjrc.com 首页字节数/是否 SPA。"""
import json, re, time
from pathlib import Path
import requests

FIX = Path(r"D:\agent-work\data\raw\fixtures")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})

def visible_text(html):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = re.sub(r"\s+", "", h)
    return h

out = {}

# --- 本地：js365job 存档的可见文本
home = (FIX / "probe_js365job_home.html").read_text(encoding="utf-8", errors="replace")
vt = visible_text(home)
out["js365job_local"] = {"file_bytes": len(home.encode("utf-8")), "visible_chars": len(vt),
                         "visible_sample": vt[:60],
                         "app_div": "<div id=app>" in home or "<div id=\"app\">" in home}
print("js365job 存档: bytes=%d 可见字符=%d sample=%r" % (
    out["js365job_local"]["file_bytes"], len(vt), vt[:40]))
time.sleep(3)

# --- js365job robots
try:
    r = s.get("https://www.js365job.com/robots.txt", timeout=20)
    body = r.content.decode("utf-8", "replace")
    out["js365job_robots"] = {"status": r.status_code, "bytes": len(r.content),
                              "is_html": "<html" in body[:500].lower(),
                              "head": body[:160]}
    print("js365job robots: %d / %d B / html=%s" % (r.status_code, len(r.content),
                                                    out["js365job_robots"]["is_html"]))
except Exception as e:
    out["js365job_robots"] = {"error": repr(e)}
    print("js365job robots error:", e)
time.sleep(4)

# --- zjrc.com 首页
try:
    r = s.get("https://www.zjrc.com/", timeout=25)
    body = r.content.decode("utf-8", "replace")
    vt2 = visible_text(body)
    out["zjrc_home"] = {"status": r.status_code, "bytes": len(r.content),
                        "visible_chars": len(vt2), "visible_sample": vt2[:60],
                        "div_app": ('id="app"' in body) or ("id=app" in body),
                        "module_scripts": body.count('type="module"'),
                        "title": (re.search(r"(?is)<title>(.*?)</title>", body) or [None, ""])[1].strip()[:60]}
    print("zjrc: %d / %d B / 可见=%d / title=%s" % (r.status_code, len(r.content), len(vt2),
                                                   out["zjrc_home"]["title"]))
    (FIX / "verify_v134_zjrc_home.html").write_bytes(r.content)
except Exception as e:
    out["zjrc_home"] = {"error": repr(e)}
    print("zjrc error:", e)

(FIX / "verify_v134_spa.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved")