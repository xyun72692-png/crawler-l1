# -*- coding: utf-8 -*-
"""
foodmate 勘察第 2 步：抓 10 条列表样例 + 10 条详情样例

只读、不写数据文件；间隔 2.5 秒；不碰 robots 禁止的目录。
"""
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

LIST_URL = "https://law.foodmate.net/mobile/index.php?moduleid=23&catid=39"
DELAY = 2.5

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def get(url, timeout=25):
    r = s.get(url, timeout=timeout)
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r


def parse_detail(html, url):
    soup = BeautifulSoup(html, "lxml")

    # 标题：<h1> 或 title 去掉站点后缀
    h1 = soup.select_one("h1")
    title = h1.get_text(strip=True) if h1 else ""
    if not title and soup.title:
        title = soup.title.get_text(strip=True).split("_政策法规")[0]

    # 所有 <div><b>标签：</b>值</div>
    fields = {}
    content = soup.select_one("div.content") or soup
    for div in content.find_all("div", recursive=False):
        b = div.find("b")
        if not b:
            continue
        label = b.get_text(strip=True).rstrip("：:").strip()
        # 值 = div 里除 <b> 之外的文本
        val = div.get_text(" ", strip=True)
        val = val.replace(b.get_text(strip=True), "", 1).strip()
        fields[label] = val

    # 有效性状态：img.bz_xxzt 的文件名
    img = content.select_one("img.bz_xxzt")
    status_img = ""
    if img and img.get("src"):
        status_img = img["src"].rsplit("/", 1)[-1]

    return {
        "url": url,
        "title": title,
        "publish_date": fields.get("发布日期", ""),
        "effective_date": fields.get("生效日期", ""),
        "status_img": status_img,
        "status_text_guess": "",
        "abolish_date": fields.get("废止日期", ""),
        "issuer": fields.get("发布单位", ""),
        "doc_no": fields.get("发布文号", ""),
        "attr": fields.get("属性", ""),
        "_all_fields": fields,
    }


# ---------- 列表 ----------
print("### 列表页 page=1 ###")
r = get(LIST_URL)
print("status=%s bytes=%d" % (r.status_code, len(r.content)))
soup = BeautifulSoup(r.text, "lxml")

items = []
for a in soup.find_all("a", href=True):
    h = a["href"]
    if "moduleid=23" in h and "itemid=" in h:
        li = a.find_parent("li")
        short_date = ""
        if li:
            sp = li.find("span")
            if sp:
                short_date = sp.get_text(strip=True)
        items.append({
            "title": a.get_text(strip=True),
            "url": urljoin(LIST_URL, h),
            "list_short_date": short_date,
        })

print("列表条目数:", len(items))
print()
print("=== 列表前 10 条 ===")
for i, it in enumerate(items[:10], 1):
    print("%2d. [%s] %s" % (i, it["list_short_date"], it["title"][:60]))
    print("    %s" % it["url"])

# ---------- 详情 ----------
print()
print("### 详情（前 10 条，每条间隔 %.1f 秒）###" % DELAY)
details = []
for i, it in enumerate(items[:10], 1):
    time.sleep(DELAY)
    try:
        dr = get(it["url"], timeout=25)
        d = parse_detail(dr.text, it["url"])
        d["list_short_date"] = it["list_short_date"]
        d["list_title"] = it["title"]
        details.append(d)
        print("  [%2d] %s | 发布=%s | 状态图=%s" %
              (i, d["title"][:42], d["publish_date"] or "(空)", d["status_img"] or "(无图)"))
    except Exception as e:
        print("  [%2d] FAILED %s: %s" % (i, type(e).__name__, str(e)[:80]))

print()
print("=== 状态图片名分布 ===")
from collections import Counter
c = Counter(d["status_img"] for d in details)
for k, v in c.most_common():
    print("  %-16s %d" % (k or "(无)", v))

print()
print("=== 详情样例（完整字段）===")
for d in details[:10]:
    print(json.dumps({
        "title": d["title"],
        "publish_date": d["publish_date"],
        "status_img": d["status_img"],
        "abolish_date": d["abolish_date"],
        "issuer": d["issuer"],
        "doc_no": d["doc_no"],
        "attr": d["attr"],
        "url": d["url"],
    }, ensure_ascii=False))

with open(_path_lib(__file__).resolve().parent / "_foodlaw_samples.json", "w", encoding="utf-8") as f:
    json.dump({"list": items[:10], "details": details}, f, ensure_ascii=False, indent=2)
print()
print("样例已保存 -> tests\\_foodlaw_samples.json")