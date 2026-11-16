# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
招聘站点侦查（建 registry 初版）。

红线（按指令）：
  · 不爬搜索引擎结果页；不碰 BOSS直聘/智联/58/前程无忧（只登记"已知存在"）
  · 每站只发 2 个请求（首页 + robots）；疑似第 0/1/2 层再多发 1 个列表页
  · 不并发，间隔 3~5 秒；403/验证码 → 记 blocked，不重试不绕过
  · 总请求 ≤60

用法：
    python tools\\probe_registry.py --plan     # 只打印计划与预算，不发请求
    python tools\\probe_registry.py            # 真探测
"""
import argparse
import json
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

AGENT = Path(str(_HOME))
OUT_JSON = AGENT / "sites" / "registry.json"
OUT_LOG = AGENT / "logs" / "_registry_probe.txt"

import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）
TIMEOUT = 25
BUDGET = 60

# ---------------------------------------------------------------- 候选
# probe_robots=False 表示"同一套系统的分站"，robots 直接沿用主站结论，省请求
CANDIDATES = [
    # —— 温州人才网（74cms）各县市区分站：同一套系统，独立域名
    dict(name="温州人才网·鹿城", url="https://lc.wzrc.net/", region="鹿城", kind="区级分站",
         probe_robots=False),
    dict(name="温州人才网·瓯海", url="https://oh.wzrc.net/", region="瓯海", kind="区级分站",
         probe_robots=False),
    dict(name="温州人才网·龙湾", url="https://lw.wzrc.net/", region="龙湾", kind="区级分站",
         probe_robots=False),
    dict(name="温州人才网·洞头", url="https://dt.wzrc.net/", region="洞头", kind="区级分站",
         probe_robots=False),
    dict(name="温州人才网·乐清", url="https://yq.wzrc.net/", region="乐清", kind="县级分站",
         probe_robots=False),
    dict(name="温州人才网·瑞安", url="https://ra.wzrc.net/", region="瑞安", kind="县级分站",
         probe_robots=False),
    dict(name="温州人才网·永嘉", url="https://yj.wzrc.net/", region="永嘉", kind="县级分站",
         probe_robots=False),
    dict(name="温州人才网·文成", url="https://wc.wzrc.net/", region="文成", kind="县级分站",
         probe_robots=False),
    dict(name="温州人才网·平阳", url="https://py.wzrc.net/", region="平阳", kind="县级分站",
         probe_robots=False),
    dict(name="温州人才网·泰顺", url="https://ts.wzrc.net/", region="泰顺", kind="县级分站",
         probe_robots=False),
    dict(name="温州人才网·苍南", url="https://cn.wzrc.net/", region="苍南", kind="县级分站",
         probe_robots=False),

    # —— 已知在册
    dict(name="温州人才网", url="https://www.wzrc.net/", region="温州", kind="市级官方",
         probe_robots=True, status="已接入", site_module="sites/wzrc_all.py",
         note="全温州覆盖；双休 tag=147 时 109 页", known_scale="949 页 / 约 4700 条"),
    dict(name="乐清人才网", url="https://www.yqrc.com/", region="乐清", kind="县级官方",
         probe_robots=True, status="已接入", site_module="sites/yqrc.py",
         note="骑士CMS系；列表 20 条/页", known_scale="约 220 条"),

    # —— 政府/省级（可能是公告类，不是职位库）
    dict(name="温州市人社局", url="https://hrss.wenzhou.gov.cn/", region="温州", kind="政府",
         probe_robots=True),
    dict(name="浙江人才网", url="https://www.zjrc.com/", region="浙江", kind="省级官方",
         probe_robots=True),
    dict(name="杭州人才网", url="https://www.hzrc.com/", region="杭州", kind="市级官方",
         probe_robots=True),

    # —— 县级独立站的候选（可能是通不过 DNS 的猜测，成本≈0）
    dict(name="瑞安人才网(候选)", url="https://www.ruianrc.com/", region="瑞安", kind="县级官方",
         probe_robots=True),
    dict(name="瑞安人才网(候选2)", url="https://www.rahr.com/", region="瑞安", kind="县级官方",
         probe_robots=True),
    dict(name="苍南人才网(候选)", url="https://www.cangnanrc.com/", region="苍南", kind="县级官方",
         probe_robots=True),
    dict(name="平阳人才网(候选)", url="https://www.pyxrc.com/", region="平阳", kind="县级官方",
         probe_robots=True),
    dict(name="永嘉人才网(候选)", url="https://www.yjrcw.com/", region="永嘉", kind="县级官方",
         probe_robots=True),
]

# 红线：只登记，不探测
KNOWN_BLOCKED = [
    dict(name="BOSS直聘", url="https://www.zhipin.com", region="全国", kind="平台",
         status="blocked", note="强风控 + 明确禁止抓取；按红线不探测"),
    dict(name="智联招聘", url="https://www.zhaopin.com", region="全国", kind="平台",
         status="blocked", note="同上，不探测"),
    dict(name="前程无忧", url="https://www.51job.com", region="全国", kind="平台",
         status="blocked", note="同上，不探测"),
    dict(name="58同城", url="https://www.58.com", region="全国", kind="平台",
         status="blocked", note="同上，不探测"),
]

LOG = []


def log(msg):
    print(msg, flush=True)
    LOG.append(msg)


def gap():
    t = random.uniform(3.0, 5.0)
    time.sleep(t)


def classify_level(html):
    """返回 (level, 依据)。"""
    low = html[:400000]
    if "__NEXT_DATA__" in low or "__INITIAL_STATE__" in low or "window.__NUXT__" in low:
        return 2, "内嵌 JSON（__NEXT_DATA__/__INITIAL_STATE__）"
    if re.search(r"/api/|fetch\(|\$\.(get|post)\(|\.json[\"']", low):
        return 1, "源码里出现 /api/、fetch(、.json 线索"
    # 第 0 层：源码里直接有职位列表标记
    if re.search(r"(jobs_list|job_list|jobslist|职位列表|招聘列表|job-item|jobs-item)", low, re.I):
        return 0, "源码里出现列表容器/职位列表标记"
    return 3, "源码里没有列表痕迹（大概率纯前端/重 JS）"


def find_scale(text):
    for pat, fmt in ((r"共\s*(\d+)\s*页", "%s 页"),
                     (r"共\s*(\d+)\s*条", "%s 条"),
                     (r"(\d+)\s*个职位", "%s 个职位")):
        m = re.search(pat, text)
        if m:
            return fmt % m.group(1)
    return "unknown"


def is_recruit(text):
    hot = ("招聘", "职位", "岗位", "人才")
    corp = ("公司", "企业")
    return any(k in text for k in hot) and any(k in text for k in corp)


def probe(sess, cand, stats):
    url = cand["url"]
    rec = {
        "name": cand["name"], "url": url.rstrip("/"), "region": cand["region"],
        "kind": cand["kind"], "level": None, "robots": None, "scale": "unknown",
        "status": "不相关", "site_module": cand.get("site_module"),
        "last_run": cand.get("last_run"), "note": cand.get("note", ""),
    }
    try:
        r = sess.get(url, timeout=TIMEOUT)
        stats["requests"] += 1
        rec["_http"] = r.status_code
        log("  %-22s HTTP %d  %7d 字节" % (cand["name"], r.status_code, len(r.content)))
        if r.status_code in (403, 429, 503):
            rec["status"] = "blocked"
            rec["note"] = (rec["note"] + "；" if rec["note"] else "") + "首页 HTTP %d（疑风控）" % r.status_code
            return rec
        html = r.text
    except Exception as e:
        stats["requests"] += 1
        rec["note"] = (rec["note"] + "；" if rec["note"] else "") + "首页取不到（%s）" % type(e).__name__
        rec["_http"] = "error"
        log("  %-22s 异常 %s（域名可能不存在）" % (cand["name"], type(e).__name__))
        return rec

    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    rec["_title"] = title
    alive = bool(title)
    recruit = is_recruit(html)

    lvl, why = classify_level(html)
    rec["level"] = lvl
    rec["_level_why"] = why
    scale = find_scale(html) if html else "unknown"
    if scale == "unknown" and cand.get("known_scale"):
        scale = cand["known_scale"]
    rec["scale"] = scale

    if cand.get("status") == "已接入":
        rec["status"] = "已接入"
    elif alive and recruit:
        rec["status"] = "待接入"
    else:
        rec["status"] = "不相关"
        rec["note"] = (rec["note"] + "；" if rec["note"] else "") + (
            "首页活但不像招聘站" if alive else "首页无 <title>")
    return rec


def probe_list_page(sess, rec, cand, stats):
    """对疑似第 0/1/2 层再发 1 个列表页请求，确认源码里到底有没有内容。"""
    base = rec["url"] + "/"
    guesses = []
    if "wzrc.net" in base or "74cms" in base:
        guesses.append("index.php?m=&c=Jobs&a=jobs_list")
    guesses += ["jobs/", "job/", "zhaopin/", "?page=2"]
    for g in guesses[:2]:
        u = urljoin(base, g)
        gap()
        try:
            r = sess.get(u, timeout=TIMEOUT)
            stats["requests"] += 1
            html = r.text
            has_list = bool(re.search(r"(jobs_list|job_list|job-item|jobs-item|职位名称)", html, re.I))
            log("      列表页 %s → HTTP %d  %7d 字节  含列表标记=%s"
                % (u.replace(rec["url"], ""), r.status_code, len(r.content), has_list))
            rec["_list_probe"] = {"url": u, "http": r.status_code, "bytes": len(r.content),
                                  "has_list_marker": has_list}
            if r.status_code == 200 and has_list:
                return
        except Exception as e:
            stats["requests"] += 1
            log("      列表页异常 %s" % type(e).__name__)
    return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()

    planned = sum(1 + (1 if c.get("probe_robots", True) else 0) for c in CANDIDATES)
    log("候选 %d 个；首页+robots 计划请求 %d；留给列表页 %d"
        % (len(CANDIDATES), planned, BUDGET - planned))
    if a.plan:
        for c in CANDIDATES:
            log("  %-22s %-34s robots=%s" % (c["name"], c["url"], "查" if c.get("probe_robots", True) else "省"))
        return 0

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    stats = {"requests": 0}
    out = []

    for i, cand in enumerate(CANDIDATES, 1):
        log("[%2d/%d] %s" % (i, len(CANDIDATES), cand["name"]))
        rec = probe(sess, cand, stats)

        # robots（同系统分站跳过，省请求）
        if cand.get("probe_robots", True):
            gap()
            try:
                rr = sess.get(urljoin(rec["url"] + "/", "robots.txt"), timeout=TIMEOUT)
                stats["requests"] += 1
                rec["robots"] = str(rr.status_code)
                if rr.status_code == 403:
                    rec["robots"] = "robots_blocked"
                log("      robots HTTP %d" % rr.status_code)
            except Exception:
                stats["requests"] += 1
                rec["robots"] = "error"
        else:
            rec["robots"] = "同主站(404)"

        # 疑似 0/1/2 层且判定为待接入/已接入 → 再看一个列表页
        if rec.get("level") in (0, 1, 2) and rec["status"] in ("待接入", "已接入"):
            probe_list_page(sess, rec, cand, stats)

        out.append(rec)
        if stats["requests"] >= BUDGET - 2:
            log("!! 接近预算上限，停止")
            break
        gap()

    # 补充"不探测"的已知平台
    for k in KNOWN_BLOCKED:
        out.append({**k, "level": None, "robots": "未探测", "scale": "unknown",
                    "site_module": None, "last_run": None})

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.write_text("\n".join(LOG), encoding="utf-8")

    log("")
    log("=" * 60)
    log("真实请求合计：%d（预算 %d）" % (stats["requests"], BUDGET))
    log("registry：%s（%d 条）" % (OUT_JSON, len(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())