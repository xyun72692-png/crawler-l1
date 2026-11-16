# -*- coding: utf-8 -*-
"""页大小探测（提案3）：每页到底能放几条？

背景：温州人才网（74cms）的 `pagesize` 参数**实测无效**（5 条→5 条）。
但别的站（或本站将来改版）可能有效，所以把探测做成一个**只用 4 个请求**的独立脚本，
不要凭猜写进正式配置。

判定三件事：
    1. 卡片数变了没有（5 → N）
    2. 页面声明的总页数变了没有（949 → 更少）
    3. 有没有被换成假页面（no_page_group / 0 卡片）

三档结论：
    effective   卡片数真的变多 → 参数有效
    ineffective 卡片数不变（但总页数可能变；只改分页控件不算有效）
    unknown     被假页面拦截 / robots 不允许 / 冷却中 / 请求失败 —— 不下结论

用法：
    python scripts\\probe_pagesize.py --site mocksoft
    ... --site wzrc_all --param pagesize --value 50 --dry-run

安全约束（写死在代码里，不给参数改）：
    ≤ 4 个请求；每次间隔 5~6 秒；先查 robots；先查冷却文件；出现假页面立刻停。
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crawlers"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 DataCrawler/1.0")

MAX_REQUESTS = 4


def _sleep():
    time.sleep(random.uniform(5.0, 6.0))


def _load_site(name):
    from importlib import import_module
    return import_module("sites." + name)


def _cooldown_state(cfg):
    """
    读冷却文件（和爬虫同一套规则：存在且未到期就不探测）。

    关键：必须先把 crawler.CONFIG["state_dir"] 换成**该站点自己的** state_dir，
    否则会去默认目录找一个根本不存在的冷却文件（等于没检查）。
    """
    import crawler
    from crawler import cooldown_group, load_cooldown, cooldown_until
    from datetime import datetime
    from crawler import TZ
    if cfg.get("state_dir"):
        crawler.CONFIG["state_dir"] = cfg["state_dir"]
    if cfg.get("soft_block"):
        crawler.CONFIG["soft_block"] = cfg["soft_block"]
    host = urlsplit(cfg["url_template"].format(page=cfg.get("page_start", 1))).netloc.lower()
    key = cooldown_group(host)
    cd = load_cooldown(key)
    if cd:
        until = cooldown_until(cd)
        if until is not None and datetime.now(TZ) < until:
            return key, cd.get("until")
    return key, None


def _robots_ok(sess, base, path_prefix):
    """只想确认 robots 允不允许，最多 1 个请求。"""
    from urllib import robotparser
    r = sess.get(base + "/robots.txt", timeout=15)
    if r.status_code == 404:
        return True, "robots 404（未设限）"
    if r.status_code != 200:
        return False, "robots HTTP %d（按不允许处理）" % r.status_code
    rp = robotparser.RobotFileParser()
    rp.parse((r.text or "").splitlines())
    ok = rp.can_fetch(UA, base + path_prefix)
    return ok, ("robots 允许" if ok else "robots 禁止该路径")


def main():
    ap = argparse.ArgumentParser(description="页大小探测（≤4 请求）")
    ap.add_argument("--site", required=True, help="站点模块名，如 wzrc_all")
    ap.add_argument("--param", default="pagesize", help="要探测的参数名")
    ap.add_argument("--value", default="50", help="参数取值")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="只打印将要请求的 URL，不发请求")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    mod = _load_site(a.site)
    cfg = mod.CONFIG
    url0 = cfg["url_template"].format(page=a.page)
    sep = "&" if "?" in url0 else "?"
    url1 = url0 + sep + "%s=%s" % (a.param, a.value)

    out = {"site": a.site, "param": a.param, "value": a.value,
           "url_base": url0, "url_probe": url1,
           "requests": 0, "checks": {}, "verdict": "unknown", "note": ""}

    if a.dry_run:
        out["note"] = "dry-run：没发请求"
        print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else
              "将请求（预计 %d 个）：\n  %s\n  %s" % (MAX_REQUESTS, url0, url1))
        return 0

    # ---- 前置：冷却 ----
    key, until = _cooldown_state(cfg)
    if until:
        out["note"] = "冷却中：%s 到 %s 之前不探测" % (key, until)
        print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else out["note"])
        return 6

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA,
                         "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                         "Accept-Language": "zh-CN,zh;q=0.9"})

    # ---- 前置：robots（1 个请求）----
    base = "%s://%s" % (urlsplit(url0).scheme, urlsplit(url0).netloc)
    ok, why = _robots_ok(sess, base, urlsplit(url0).path or "/")
    out["requests"] += 1
    out["checks"]["robots"] = why
    if not ok:
        out["note"] = "robots 不允许 → 不探测"
        print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else out["note"])
        return 2

    def probe(u, label):
        _sleep()
        r = sess.get(u, timeout=25, headers={"Referer": base + "/"})
        html = r.text or ""
        cards = len(re.findall(r'class="[^"]*J_jobsList', html)) if "J_jobsList" in html else None
        if cards is None:                      # 非 wzrc 系站点：数通用卡片
            cards = len(re.findall(r'<div class="[^"]*item', html))
        links = re.findall(r'href="([^"]+)"', html)
        links = [x for x in links if "/d/" in x or "jobinfo" in x or "jobs/" in x]
        m = re.search(r"</span>\s*/\s*(\d+)\s*页", html)
        fake = ("no_page_group" in html) or (r.status_code == 200 and cards == 0)
        return {"label": label, "status": r.status_code, "bytes": len(r.content),
                "cards": cards, "declared_pages": int(m.group(1)) if m else None,
                "fake_page": fake, "links": links}

    url2 = cfg["url_template"].format(page=2)
    sep2 = "&" if "?" in url2 else "?"
    url2 = url2 + sep2 + "%s=%s" % (a.param, a.value)

    base_res = probe(url0, "baseline")
    out["requests"] += 1
    out["checks"]["baseline"] = base_res
    if base_res["fake_page"]:
        out["note"] = "基线页就是假页面（被限流或被拦）→ 不下结论"
        out["verdict"] = "unknown"
        print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else out["note"])
        return 6

    pr = probe(url1, "probe")
    out["requests"] += 1
    out["checks"]["probe"] = pr
    if pr["fake_page"]:
        out["note"] = "带参数的那页变成假页面 → 参数可能触发风控，不下结论"
        out["verdict"] = "unknown"
        print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else out["note"])
        return 6

    # ---- 判定 ----
    same_cards = (pr["cards"] == base_res["cards"])
    pages_changed = (pr["declared_pages"] != base_res["declared_pages"])
    if not same_cards and out["requests"] < MAX_REQUESTS:
        # 卡片真的变多了：再验一件更关键的事——**分页有没有被搞坏**。
        # 参数生效但页码错位（第 2 页和第 1 页内容重复）比"参数无效"更危险：
        # 会让人以为抓了 N 条，实际大量重复。
        p2 = probe(url2, "page2")
        out["requests"] += 1
        out["checks"]["page2"] = p2
        overlap = set(pr["links"]) & set(p2["links"])
        if p2["fake_page"]:
            out["verdict"] = "unknown"
            out["note"] = "第 2 页变成假页面，不下结论"
            print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else out["note"])
            return 6
        if overlap:
            out["verdict"] = "broken_pagination"
            out["note"] = ("卡片数变多（%s→%s）但第 2 页与第 1 页有 %d 条重复 → "
                           "分页被打乱，不能直接用这个参数"
                           % (base_res["cards"], pr["cards"], len(overlap)))
            print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else
                  "结论：broken_pagination\n%s（共 %d 个请求）" % (out["note"], out["requests"]))
            return 3
        out["verdict"] = "effective"
        out["note"] = "卡片数 %s → %s，参数有效；第 2 页无重叠" % (base_res["cards"], pr["cards"])
    elif not same_cards:
        out["verdict"] = "effective"
        out["note"] = "卡片数 %s → %s，参数有效（请求额度已用完，未验第 2 页）" % (
            base_res["cards"], pr["cards"])
    elif pages_changed:
        out["verdict"] = "ineffective"
        out["note"] = ("卡片数没变（%s），但声明总页数 %s → %s；"
                       "只改分页控件不算有效" % (base_res["cards"],
                                          base_res["declared_pages"], pr["declared_pages"]))
    else:
        out["verdict"] = "ineffective"
        out["note"] = "卡片数与总页数都没变（%s 条 / %s 页），参数无效" % (
            base_res["cards"], base_res["declared_pages"])

    print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else
          "结论：%s\n%s\n（共 %d 个请求）" % (out["verdict"], out["note"], out["requests"]))
    return 0 if out["verdict"] == "effective" else 1


if __name__ == "__main__":
    sys.exit(main())