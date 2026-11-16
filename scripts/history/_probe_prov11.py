# -*- coding: utf-8 -*-
"""探测 11 个待补省份的官方公共就业平台：每站 1 个 GET 首页。
记录 status / 字节 / 可见字符 / title / 是否 SPA / 是否跳登录。
"""
import json, re, time, sys
from pathlib import Path
import requests

FIX = Path(r"D:\agent-work\data\raw\fixtures")
FIX.mkdir(parents=True, exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")

TARGETS = [
    ("辽宁", "https://rlzy.lnrc.com.cn/"),
    ("吉林", "https://www.jlrc.com.cn/ww/index.html"),
    ("吉林IP", "http://111.41.62.147:13332/"),
    ("福建", "https://www.fj99.org.cn/"),
    ("河南", "https://www.hn91w.com/"),
    ("湖北", "https://www.hbggzp.cn/"),
    ("四川", "http://www.sc91.org.cn/"),
    ("贵州", "https://gzggzpw.gzsrs.cn/"),
    ("陕西", "https://qinyunjiuye.cn/"),
    ("青海", "https://qhrsggfw.org.cn/qhrst/index/qhrs/talant/index.jspx"),
    ("新疆", "https://www.xjrc365.com/recruit/page/index"),
]

def visible(html):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", "", h)

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
out = []
for prov, url in TARGETS:
    rec = {"省": prov, "url": url}
    try:
        r = s.get(url, timeout=20, allow_redirects=True)
        body = r.content.decode(r.apparent_encoding or "utf-8", "replace")
        vt = visible(body)
        title = (re.search(r"(?is)<title>(.*?)</title>", body) or [None, ""])[1].strip()
        rec.update({"status": r.status_code, "bytes": len(r.content),
                    "final_url": r.url, "title": title[:60],
                    "visible_chars": len(vt),
                    "spa": ("id=app" in body or 'id="app"' in body or body.count("type=\"module\"") >= 2),
                    "login_hint": bool(re.search(r"(login|登录|统一身份|政务服务网)", vt[:200]))})
    except Exception as e:
        rec["error"] = repr(e)[:160]
    out.append(rec)
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    time.sleep(3)

(FIX / "verify_prov11_probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE ->", FIX / "verify_prov11_probe.json")