#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受控渲染抓取：先探测报风险，经你同意再渲染。

两种模式：
    默认（探测）  只读 robots + 静态 HTML，**不渲染**，输出 6 字段风险报告
    --render      真开浏览器渲染，存 HTML + api_candidates

用法：
    python tools\\fetch_rendered.py https://example.com/list              # 探测
    python tools\\fetch_rendered.py https://example.com/list --render     # 渲染
    python tools\\fetch_rendered.py https://example.com/list --render --allow-robots-js
    python tools\\fetch_rendered.py --html data\\raw\\_rendered\\x.html     # 离线，0 请求

退出码：0 成功 / 1 部分（超时但有 HTML）/ 2 失败（robots 禁止、导航失败）
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
# 测试可用环境变量把落盘目录指到临时位置，避免污染真实数据目录
OUTDIR = Path(os.environ.get("FETCH_RENDERED_OUT") or (ROOT / "data" / "raw" / "_rendered"))
NAVCOUNT = OUTDIR / "_navcount.json"

# 与 crawler.py L385 逐字一致
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
import identity as _identity
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）

MAX_NAV_PER_DAY = 30
MAX_5XX_RETRY = 2           # 5xx 最多重试次数（1s、4s）
FIVEXX_WAITS = (1, 4)
CAPTCHA_HINTS = ("身份验证", "安全验证", "验证码", "人机验证", "请完成验证",
                 "访问验证", "访问受限", "滑动验证", "不是自动程序")
SHELL_BYTES = 5000
SHELL_TEXT = 500


def strip_tags(html):
    t = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def page_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def detail_links(html, base):
    out, seen = set(), set()
    for m in re.finditer(r"""href\s*=\s*["']([^"'#]+)["']""", html, flags=re.I):
        full = urljoin(base, m.group(1).strip())
        if urlparse(full).netloc != urlparse(base).netloc:
            continue
        if not re.search(r"\d{3,}", full):
            continue
        if re.search(r"(page=|p=|sort=|tag=|cat=)", full, re.I):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.add(full)
    return out


def js_disallowed(robots_text):
    """robots 里是否有 Disallow 指向 *.js*。"""
    for line in robots_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith("disallow:") and ".js" in s.lower():
            return True, s
    return False, ""


def check_robots(session, home_url):
    """返回 (状态, 规则文本, 说明)。网络异常也给状态，不往上抛。"""
    try:
        r = session.get(urljoin(home_url, "/robots.txt"), timeout=20)
    except Exception as exc:
        return "error", "", "robots 请求失败：%s" % type(exc).__name__
    code = r.status_code
    if code == 404:
        return "none", "", "404 = 没设限"
    if code in (401, 403) or code >= 500:
        return "blocked", "", "robots 返回 %s，视为拒绝" % code
    if code == 200:
        return "ok", r.text, "200"
    return "other", "", "robots 返回 %s" % code


def nav_state(host):
    """读今日导航次数与上次导航时间。"""
    OUTDIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    data = {}
    if NAVCOUNT.exists():
        try:
            data = json.loads(NAVCOUNT.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    rec = data.get(host) or {}
    if rec.get("date") != today:
        return {"n": 0, "last_ts": 0.0}
    return {"n": rec.get("n", 0), "last_ts": rec.get("last_ts", 0.0)}


def nav_guard(host):
    """同一域名每天最多 30 次导航。返回 (允许?, 今日已用)。"""
    st = nav_state(host)
    return st["n"] < MAX_NAV_PER_DAY, st["n"]


def nav_wait(host, delay):
    """同域两次导航之间至少间隔 delay[0]~delay[1] 秒。返回实际等待秒数。"""
    st = nav_state(host)
    if not st["last_ts"]:
        return 0.0
    need = random.uniform(delay[0], delay[1])
    elapsed = time.time() - st["last_ts"]
    wait = need - elapsed
    if wait > 0:
        time.sleep(wait)
        return round(wait, 2)
    return 0.0


def nav_bump(host):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    data = {}
    if NAVCOUNT.exists():
        try:
            data = json.loads(NAVCOUNT.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    rec = data.get(host) or {}
    if rec.get("date") != today:
        rec = {"date": today, "n": 0}
    rec["n"] = rec.get("n", 0) + 1
    rec["last_ts"] = time.time()
    data[host] = rec
    NAVCOUNT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cookies(path):
    """支持两种格式：JSON 数组，或一行 k=v; k2=v2。"""
    text = Path(path).read_text(encoding="utf-8")
    try:
        arr = json.loads(text)
        if isinstance(arr, list):
            return arr
    except Exception:
        pass
    out = []
    for part in text.replace("\n", ";").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip():
                out.append({"name": k.strip(), "value": v.strip()})
    return out


class Page:
    """探测阶段用的轻量请求器（不发浏览器）。"""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.count = 0

    def get(self, url, timeout=20):
        self.count += 1
        return self.s.get(url, timeout=timeout, allow_redirects=True)


def probe(home_url, allow_robots_js, cookies_file, on_5xx="retry"):
    """只读 robots + 静态 HTML，输出风险报告。"""
    host = urlparse(home_url).netloc
    p = Page()
    rep = {
        "url": home_url, "mode": "probe", "host": host,
        "blocked_by": [], "override_needed": [], "success_likely": "unknown",
        "why": "", "risk": "", "irreversible": "否（只读，不写对方服务器）",
        "http_status": None, "bytes": 0, "title": "", "text_len": 0,
        "detail_links": 0, "robots": "", "js_blocked": False,
        "overrides": [],
    }

    if cookies_file:
        rep["overrides"].append("cookies")

    st, rtext, why = check_robots(p.s, home_url)
    rep["robots"] = st
    if st == "error":
        rep["blocked_by"].append("robots_unreachable")
        rep["override_needed"].append("（无：网络不通，先查能不能访问）")
        rep["success_likely"] = "low"
        rep["why"] = why
        rep["risk"] = "不是站点拦截，是本机连不上"
        return rep, 2
    if st == "blocked":
        rep["blocked_by"].append("robots_blocked")
        rep["override_needed"].append("（无：robots 明确拒绝，不建议覆盖）")
        rep["success_likely"] = "low"
        rep["why"] = why
        rep["risk"] = "站点明确拒绝抓取；继续属于明知故犯"
        return rep, 2

    if st == "ok":
        blocked, rule = js_disallowed(rtext)
        rep["js_blocked"] = blocked
        if blocked:
            rep["blocked_by"].append("robots_js")
            if not allow_robots_js:
                rep["override_needed"].append("--allow-robots-js")
                rep["success_likely"] = "medium"
                rep["why"] = "robots 有 %s；渲染必然加载 JS 子资源" % rule
                rep["risk"] = "违反站点 robots 明文告示；对方访问日志会记录你的 IP"
                return rep, 2
            rep["overrides"].append("allow_robots_js")
            rep["risk"] = "已覆盖 robots 的 JS 限制（明知故犯）"
            rep["blocked_by"] = [b for b in rep["blocked_by"] if b != "robots_js"]

    try:
        r = p.get(home_url)
    except Exception as exc:
        rep["blocked_by"].append("nav_failed")
        rep["why"] = "请求失败：%s" % exc
        rep["risk"] = "网络问题，非站点拦截"
        return rep, 2

    rep["http_status"] = r.status_code
    rep["bytes"] = len(r.content)
    rep["retry_5xx"] = 0

    # 5xx 是"站点故障"，不是"页面内容"——按策略重试，仍失败就明确报故障，
    # 绝不能当成空壳去猜"这是 SPA"（那会误导后续决策）
    if r.status_code >= 500:
        if on_5xx == "retry":
            for wait_s in FIVEXX_WAITS[:MAX_5XX_RETRY]:
                time.sleep(wait_s)
                rep["retry_5xx"] += 1
                try:
                    r = p.get(home_url)
                except Exception:
                    continue
                rep["http_status"] = r.status_code
                rep["bytes"] = len(r.content)
                if r.status_code < 500:
                    break
        if r.status_code >= 500:
            rep["blocked_by"].append("http_5xx")
            rep["override_needed"].append("（无：等站点恢复，或换时间段重试）")
            rep["success_likely"] = "low"
            rep["why"] = ("首页返回 %d（站点故障），已重试 %d 次仍失败"
                          % (r.status_code, rep["retry_5xx"]))
            rep["risk"] = "服务器故障，不是反爬；过一段时间再来，别当场硬打"
            return rep, 2

    if r.status_code in (401, 403):
        rep["blocked_by"].append("http_%d" % r.status_code)
        rep["override_needed"].append("--cookies / --headed（或换 IP）")
        rep["success_likely"] = "low"
        rep["why"] = "首页返回 %d，服务器明确拒绝（403 不自动重试）" % r.status_code
        rep["risk"] = ("403 没有代码层面的绕过手段；要试就隔几分钟手动重跑一次，"
                       "不要连着打，重试只会加深封禁印象")
        return rep, 2

    html = r.text
    rep["title"] = page_title(html)
    text = strip_tags(html)
    rep["text_len"] = len(text)
    hints = [k for k in CAPTCHA_HINTS if k in text]
    if hints and len(text) < 5000:
        rep["blocked_by"].append("captcha")
        rep["override_needed"].append("--headed（人工过一次）或 --cookies")
        rep["success_likely"] = "medium"
        rep["why"] = "正文 %d 字符，含验证提示：%s" % (len(text), "、".join(hints[:3]))
        rep["risk"] = "破解验证码属于对抗站点；我们只做人工过一次后复用 Cookie"
        return rep, 2

    links = detail_links(html, home_url)
    rep["detail_links"] = len(links)

    if len(text) >= 300 and len(links) >= 3:
        rep["success_likely"] = "high"
        rep["why"] = ("静态 HTML 里已有内容（正文 %d 字符、%d 个详情链接），"
                      "不需要渲染" % (len(text), len(links)))
        rep["risk"] = "无额外风险（就是普通抓取）"
        rep["verdict"] = "静态可抓"
        return rep, 0

    rep["success_likely"] = "medium"
    rep["why"] = ("静态 HTML 是空壳（%d 字节 / 正文 %d 字符 / %d 个详情链接），"
                  "需要渲染后才知道有没有数据" % (rep["bytes"], len(text), len(links)))
    rep["override_needed"].append("--render")
    rep["risk"] = "渲染会加载 JS/CSS/图片等十几个子资源；对站点压力大于普通抓取"
    rep["verdict"] = "疑似 SPA，需渲染验证"
    return rep, 0


def render(home_url, out_path, allow_robots_js, cookies_file, headed, timeout, delay):
    """真开浏览器渲染。**导航前必查 robots**，被拦就停（rc=2）。返回 (报告, rc)。"""
    from playwright.sync_api import sync_playwright

    host = urlparse(home_url).netloc
    rep = {"url": home_url, "mode": "render", "host": host,
           "browser": "", "navigations": 0, "subresources": 0,
           "api_candidates": [], "overrides": [], "warning": "",
           "blocked_by": [], "override_needed": [], "success_likely": "",
           "why": "", "risk": "", "irreversible": "否（只读，不写对方服务器）",
           "robots": "", "js_blocked": False,
           "bytes": 0, "title": "", "elapsed_sec": 0, "nav_wait_sec": 0,
           "out": str(out_path)}

    if allow_robots_js:
        rep["overrides"].append("allow_robots_js")
        rep["warning"] = "已跳过 robots 的 JS 限制"
    if cookies_file:
        rep["overrides"].append("cookies")
    if headed:
        rep["overrides"].append("headed")

    # ---------- 导航前：robots 硬检查（和探测模式同一套规则）----------
    p = Page()
    st, rtext, why = check_robots(p.s, home_url)
    rep["robots"] = st
    if st == "error":
        rep["blocked_by"].append("robots_unreachable")
        rep["why"] = why
        rep["risk"] = "不是站点拦截，是本机连不上"
        rep["success_likely"] = "low"
        return rep, 2
    if st == "blocked":
        rep["blocked_by"].append("robots_blocked")
        rep["why"] = why
        rep["risk"] = "站点明确拒绝抓取；继续属于明知故犯"
        rep["success_likely"] = "low"
        rep["override_needed"].append("（无：robots 明确拒绝，不建议覆盖）")
        return rep, 2
    if st == "ok":
        blocked, rule = js_disallowed(rtext)
        rep["js_blocked"] = blocked
        if blocked and not allow_robots_js:
            rep["blocked_by"].append("robots_js")
            rep["override_needed"].append("--allow-robots-js")
            rep["why"] = "robots 有 %s；渲染必然加载 JS 子资源" % rule
            rep["risk"] = "违反站点 robots 明文告示；对方访问日志会记录你的 IP"
            rep["success_likely"] = "medium"
            return rep, 2

    # ---------- 导航预算 + 间隔 ----------
    ok, used = nav_guard(host)
    if not ok:
        rep["error"] = "该域名今天已导航 %d 次，达到上限 %d" % (used, MAX_NAV_PER_DAY)
        rep["why"] = rep["error"]
        return rep, 2

    rep["nav_wait_sec"] = nav_wait(host, delay)

    started = time.time()
    api = []

    with sync_playwright() as pw:
        browser = None
        for ch in ("chrome", "msedge"):
            try:
                browser = pw.chromium.launch(channel=ch, headless=not headed)
                rep["browser"] = "%s %s" % (ch, browser.version)
                break
            except Exception:
                browser = None
        if browser is None:
            rep["error"] = "chrome / msedge 都启动失败，无法渲染"
            return rep, 2

        try:
            ctx = browser.new_context(**_identity.for_playwright())  # 不覆盖 UA
            if cookies_file:
                ck = load_cookies(cookies_file)
                if ck:
                    for c in ck:
                        if "url" not in c and "domain" not in c:
                            c["url"] = home_url
                    ctx.add_cookies(ck)
            page = ctx.new_page()

            def on_response(resp):
                try:
                    rt = resp.request.resource_type
                    if rt in ("xhr", "fetch"):
                        api.append({
                            "url": resp.url,
                            "method": resp.request.method,
                            "content_type": (resp.headers or {}).get("content-type", ""),
                            "status": resp.status,
                        })
                    else:
                        rep["subresources"] += 1
                except Exception:
                    pass

            page.on("response", on_response)
            rep["navigations"] = 1
            nav_bump(host)

            partial = False
            resp = None
            try:
                resp = page.goto(home_url, wait_until="networkidle",
                                 timeout=timeout * 1000)
            except Exception:
                partial = True
                try:
                    resp = page.goto(home_url, wait_until="domcontentloaded",
                                     timeout=timeout * 1000)
                    page.wait_for_timeout(3000)
                except Exception as exc:
                    rep["error"] = "导航失败：%s" % exc
                    browser.close()
                    return rep, 2

            status = getattr(resp, "status", None) if resp is not None else None
            rep["http_status"] = status
            if status and status >= 500:
                rep["blocked_by"].append("http_5xx")
                rep["error"] = "导航返回 %d（站点故障），不重试" % status
                rep["why"] = rep["error"]
                rep["risk"] = "服务器故障，不是反爬；等站点恢复再来"
                rep["success_likely"] = "low"
                browser.close()
                return rep, 2
            if status in (401, 403):
                rep["blocked_by"].append("http_%d" % status)
                rep["why"] = "导航返回 %d，服务器明确拒绝" % status
                rep["risk"] = "403 没有代码层面绕过手段；要试就隔几分钟手动重跑"
                rep["success_likely"] = "low"
                browser.close()
                return rep, 2

            html = page.content()
            rep["title"] = page.title()
        finally:
            try:
                browser.close()
            except Exception:
                pass

    rep["bytes"] = len(html.encode("utf-8"))
    rep["elapsed_sec"] = round(time.time() - started, 1)
    rep["api_candidates"] = api[:50]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return rep, (1 if partial else 0)


def save(rep, html_path=None):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host = rep.get("host", "unknown").replace(":", "_")
    p = OUTDIR / ("render-%s-%s.json" % (host, stamp))
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def print_risk(rep):
    print("")
    print("站点        %s" % rep["url"])
    print("模式        %s" % rep.get("mode"))
    if rep.get("browser"):
        print("浏览器      %s" % rep["browser"])
    if rep.get("robots"):
        print("robots      %s" % rep["robots"])
    if rep.get("http_status"):
        print("首页        %s / %s B / %s" % (
            rep["http_status"], format(rep.get("bytes", 0), ","),
            ('"%s"' % rep["title"]) if rep.get("title") else "(无标题)"))
    print("-" * 46)
    print("blocked_by      %s" % (rep.get("blocked_by") or "无"))
    print("override_needed %s" % (rep.get("override_needed") or "无"))
    print("success_likely  %s" % rep.get("success_likely", "-"))
    print("why             %s" % rep.get("why", ""))
    print("risk            %s" % (rep.get("risk") or "无"))
    print("irreversible    %s" % rep.get("irreversible", "否"))
    if rep.get("api_candidates"):
        print("-" * 46)
        print("接口线索（%d 条）:" % len(rep["api_candidates"]))
        for a in rep["api_candidates"][:5]:
            print("  %s %s [%s]" % (a["method"], a["url"][:72], a["content_type"][:30]))
    if rep.get("verdict"):
        print("-" * 46)
        print("结论            %s" % rep["verdict"])


def main():
    ap = argparse.ArgumentParser(description="先探测报风险，再决定要不要渲染")
    ap.add_argument("url", nargs="?", help="目标网址")
    ap.add_argument("--html", help="离线模式：解析本地 HTML，0 请求")
    ap.add_argument("--out", help="渲染后 HTML 存哪（默认 data\\raw\\_rendered\\<host>.html）")
    ap.add_argument("--render", action="store_true", help="真渲染（默认只探测）")
    ap.add_argument("--allow-robots-js", action="store_true", help="覆盖 robots 的 JS 限制")
    ap.add_argument("--cookies", help="Cookie 文件（JSON 数组或 k=v; k2=v2）")
    ap.add_argument("--headed", action="store_true", help="有头浏览器（人工过验证用）")
    ap.add_argument("--timeout", type=int, default=30, help="单次导航超时秒数")
    ap.add_argument("--delay", nargs=2, type=float, default=[4.0, 6.0],
                    metavar=("MIN", "MAX"), help="同域两次导航间隔秒，默认 4 6")
    ap.add_argument("--on-5xx", choices=["retry", "stop"], default="retry",
                    help="遇到 5xx 是否重试（默认 retry：1s/4s 各一次）")
    args = ap.parse_args()

    # 离线模式：0 请求，只解析本地 HTML
    if args.html:
        p = Path(args.html)
        if not p.exists():
            print("文件不存在：%s" % p)
            return 2
        html = p.read_text(encoding="utf-8", errors="replace")
        base = args.url or "https://example.invalid/"
        text = strip_tags(html)
        rep = {
            "url": base, "mode": "offline", "host": "offline",
            "bytes": len(html.encode("utf-8")), "title": page_title(html),
            "text_len": len(text), "detail_links": len(detail_links(html, base)),
            "blocked_by": [], "override_needed": [], "success_likely": "high",
            "why": "离线样本直接解析", "risk": "无（0 请求）",
            "irreversible": "否", "api_candidates": [], "overrides": [],
        }
        print_risk(rep)
        print("明细已写入：%s" % save(rep).name)
        return 0

    if not args.url:
        print("需要 url，或 --html 指定离线样本")
        return 2

    url = args.url if args.url.startswith("http") else "https://" + args.url
    host = urlparse(url).netloc

    if not args.render:
        rep, rc = probe(url, args.allow_robots_js, args.cookies, args.on_5xx)
        print_risk(rep)
        print("明细已写入：%s" % save(rep).name)
        if rep.get("blocked_by") and rc == 2:
            print("")
            print("→ 被拦住了。要我覆盖吗？确认后再带对应开关跑一次。")
        return rc

    out = Path(args.out) if args.out else (OUTDIR / ("%s.html" % host.replace(":", "_")))
    rep, rc = render(url, out, args.allow_robots_js, args.cookies,
                     args.headed, args.timeout, args.delay)
    print_risk(rep)
    if rep.get("error"):
        print("")
        print("失败：%s" % rep["error"])
    else:
        print("")
        print("HTML 已存：%s" % out)
    print("明细已写入：%s" % save(rep).name)
    return rc


if __name__ == "__main__":
    sys.exit(main())