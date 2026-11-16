# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
抓 ①主表里每个岗位的 JD 原文（**只存不解析**）。

为什么只抓不解析：现在按标题判断对口会误判，但 29 篇短文人读一遍就完了；
写关键词解析器是额外风险，收益不匹配。

规则（按指令）：
  · 每个域名先取一次 robots.txt（404=允许）；不允许 → 直接停，不硬来
  · 随机间隔 3~5 秒（不比正式抓取更快）
  · timeout=25；5xx/超时重试 1 次（间隔 2 秒）
  · 落盘 data\\raw\\_jd\\<url sha1 前 12 位>.html
  · index.csv: url,title,company,http_status,bytes,path
  · 软封兜底：页面 < 5000 字节或出现 no_page_group → 立刻停，已抓的保留

用法：
    python tools\\fetch_jd.py --dry-run    # 只看要抓哪些，不发请求
    python tools\\fetch_jd.py              # 真抓
"""
import argparse
import csv
import hashlib
import random
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

import requests

AGENT = Path(str(_HOME))
SRC_JSON = AGENT / "out" / "温州岗位清单_20261111.json"
OUT_DIR = AGENT / "data" / "raw" / "_jd"
INDEX = OUT_DIR / "index.csv"

import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）
TIMEOUT = 25
RETRIES = 1
SOFT_MIN_BYTES = 5000          # 低于这个字节数视为可疑（正常详情页 60~90KB）
MARKERS = ("no_page_group",)


def sleep_gap():
    t = random.uniform(3.0, 5.0)
    print("    …等待 %.1f 秒" % t, flush=True)
    time.sleep(t)


def robots_ok(sess, origin):
    """404=允许；200=按规则；401/403/其它=不允许。"""
    url = origin + "/robots.txt"
    try:
        r = sess.get(url, timeout=TIMEOUT)
    except Exception as e:
        print("  robots 取不到（%s）→ 按不允许处理，停" % type(e).__name__)
        return False, "error"
    print("  robots %s → HTTP %d" % (url, r.status_code))
    if r.status_code == 404:
        return True, "404"
    if r.status_code in (401, 403):
        return False, str(r.status_code)
    if r.status_code != 200:
        return False, str(r.status_code)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    return True, "200"      # 逐 URL 再判


def allowed(rp_cache, origin, url, robots_text):
    if robots_text is None:
        return True
    rp = rp_cache.get(origin)
    return rp.can_fetch(UA, url) if rp else True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import json
    recs = json.loads(SRC_JSON.read_text(encoding="utf-8"))
    seen, todo = set(), []
    for r in recs:
        u = (r.get("detail_url") or "").strip()
        if u and u not in seen:
            seen.add(u)
            todo.append(r)

    origins = sorted({"%s://%s" % (urlsplit(r["detail_url"]).scheme,
                                   urlsplit(r["detail_url"]).netloc) for r in todo})
    print("待抓 %d 个详情页；域名 %d 个：%s" % (len(todo), len(origins), ", ".join(origins)))
    print("预计请求数：%d（详情）+ %d（robots）= %d"
          % (len(todo), len(origins), len(todo) + len(origins)))
    if a.dry_run:
        for r in todo[:5]:
            print("  ", r["title"][:20], r["detail_url"])
        print("  …（--dry-run，未发请求）")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA,
                         "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                         "Accept-Language": "zh-CN,zh;q=0.9"})

    # 1) robots：每个域名一次
    robots_text = {}
    rp_cache = {}
    for origin in origins:
        ok, why = robots_ok(sess, origin)
        if not ok:
            print("!! %s robots 不允许（%s）→ 直接停，不抓任何详情页" % (origin, why))
            return 2
        robots_text[origin] = None if why == "404" else "200"
        if why == "200":
            r = sess.get(origin + "/robots.txt", timeout=TIMEOUT)
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(r.text.splitlines())
            rp_cache[origin] = rp
        sleep_gap()

    # 2) 逐个详情页
    rows, stopped = [], None
    for i, rec in enumerate(todo, 1):
        url = rec["detail_url"]
        origin = "%s://%s" % (urlsplit(url).scheme, urlsplit(url).netloc)
        if not allowed(rp_cache, origin, url, robots_text.get(origin)):
            print("[%2d/%d] robots 禁止：%s" % (i, len(todo), url))
            rows.append([url, rec.get("title", ""), rec.get("company", ""),
                         "robots_denied", 0, ""])
            continue

        sleep_gap()
        status, body, size = None, None, 0
        for attempt in (1, 2):
            try:
                r = sess.get(url, timeout=TIMEOUT)
                status, body, size = r.status_code, r.content, len(r.content)
                print("[%2d/%d] HTTP %d  %6d 字节  %s"
                      % (i, len(todo), status, size, rec.get("title", "")[:18]), flush=True)
                if status >= 500 and attempt == 1:
                    print("        5xx → 2 秒后重试")
                    time.sleep(2.0)
                    continue
                break
            except Exception as e:
                print("[%2d/%d] 异常 %s" % (i, len(todo), type(e).__name__), flush=True)
                if attempt == 1:
                    time.sleep(2.0)
                    continue
                status, body, size = "error", None, 0
                break

        path = ""
        if body and status == 200:
            name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12] + ".html"
            fp = OUT_DIR / name
            fp.write_bytes(body)
            path = str(fp)
            text = body.decode("utf-8", errors="replace")
            hit = [m for m in MARKERS if m in text]
            if size < SOFT_MIN_BYTES or hit:
                print("        !! 可疑页面（%d 字节，标记 %s）→ 当软封，立刻停" % (size, hit))
                stopped = url
                rows.append([url, rec.get("title", ""), rec.get("company", ""),
                             "soft_block_suspected", size, path])
                break

        rows.append([url, rec.get("title", ""), rec.get("company", ""), status, size, path])

    with INDEX.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "title", "company", "http_status", "bytes", "path"])
        w.writerows(rows)

    ok_n = sum(1 for r in rows if r[3] == 200)
    print()
    print("=" * 60)
    print("完成 %d 条：200 的 %d 条，其他 %d 条" % (len(rows), ok_n, len(rows) - ok_n))
    print("落盘目录：%s" % OUT_DIR)
    print("索引：%s" % INDEX)
    if stopped:
        print("!! 中途因可疑页面停止：%s" % stopped)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())