# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""一次性侦察脚本：拉勾网可爬性判定。请求数固定、间隔 5.5s、结果落盘离线看。"""
import os, re, sys, time, json
import requests

PYIO = sys.stdout
OUT = r"D:\agent-work\data\raw\_probe_lagou"
os.makedirs(OUT, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
})

def show(tag, r, path):
    body = r.content
    with open(os.path.join(OUT, path), "wb") as f:
        f.write(body)
    txt = body.decode("utf-8", "replace")
    print(f"[{tag}] status={r.status_code} bytes={len(body)} final={r.url}")
    ct = r.headers.get("content-type", "")
    print(f"    content-type={ct}")
    print(f"    server={r.headers.get('server')} set-cookie={len(r.cookies)}")
    keys = ["positionAjax", "search-list", "job_item", "login", "验证", "滑块",
            "__NEXT_DATA__", "window.__INITIAL", "antibot", "acc_player", "captcha"]
    hit = [k for k in keys if k in txt]
    print(f"    keyword_hits={hit}")
    print(f"    head400={txt[:400].replace(chr(10),' ')}")
    return txt

STEPS = [
    ("robots", "https://www.lagou.com/robots.txt", "robots.txt"),
    ("home", "https://www.lagou.com/", "home.html"),
    ("search", "https://www.lagou.com/wn/jobs?kd=java&city=%E5%85%A8%E5%9B%BD&pn=1", "search_p1.html"),
]

texts = {}
for tag, url, fn in STEPS:
    try:
        r = s.get(url, timeout=25, allow_redirects=True)
        texts[tag] = show(tag, r, fn)
    except Exception as e:
        print(f"[{tag}] EXC {type(e).__name__}: {e}")
    time.sleep(5.5)

# 第 4 步：老接口 POST（看是否还活、是否要登录/签名）
api = "https://www.lagou.com/jobs/positionAjax.json?city=%E5%85%A8%E5%9B%BD&needAddtionalResult=false"
try:
    r = s.post(api, data={"first": "true", "pn": "1", "kd": "java"},
               headers={"Referer": "https://www.lagou.com/wn/jobs?kd=java",
                        "X-Requested-With": "XMLHttpRequest",
                        "Origin": "https://www.lagou.com",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
               timeout=25, allow_redirects=False)
    print(f"[api] status={r.status_code} bytes={len(r.content)} allow_redirects=False")
    with open(os.path.join(OUT, "positionAjax.json"), "wb") as f:
        f.write(r.content)
    print("    body800=" + r.content.decode("utf-8", "replace")[:800].replace("\n", " "))
except Exception as e:
    print(f"[api] EXC {type(e).__name__}: {e}")

print("DONE")