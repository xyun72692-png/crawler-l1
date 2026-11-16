#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单站探测：用 2~4 个请求摸清一个站能不能接。

替代 scripts/ 下那些一次性 _probeN.py。

用法：
    python tools\\probe_one.py https://www.cangnanrc.com
    python tools\\probe_one.py https://www.pyxrc.com --list-url "https://www.pyxrc.com/jobs/"
    python tools\\probe_one.py https://www.yqrc.com --delay 4 6

四步（每步都有产出）：
    1. robots.txt     200 解析 / 404 未设限 / 403、5xx 立刻停
    2. 首页           status、字节数、title、职位关键词、层级初判
    3. 列表页         每页条数、详情链接模板、总页数
    4. 同库校验       仅当链接形态与 wzrc 一致时（+1 请求）

红线：
    * UA 与引擎完全一致（crawler.py L385），不换
    * 间隔 4~6 秒
    * 403 / 5xx / 超时 一律停，不重试不绕过
    * 最多 4 个请求，超了直接报错（护栏）
    * 不抓详情页正文（同库校验那 1 次只读标题）
    * 不改 crawler.py（MD5 必须仍是 BC59F3546DD90EA0DCA8E237B562AEB8）

退出码：0=可接 / 1=不确定 / 2=不可接
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "reports"

# 与 crawler.py 的 CONFIG["ua"] / session_factory() 保持一致
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）
import robots_rules  # noqa: E402
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

MAX_REQUESTS = 4            # 红线：超过就是 bug
KEYWORDS = ("招聘", "职位", "岗位", "人才")
# 验证/风控页特征：红线要求遇到就停，不重试不绕过
CAPTCHA_HINTS = ("身份验证", "安全验证", "验证码", "人机验证", "请完成验证",
                 "访问验证", "访问受限", "滑动验证")
WZRC_TEMPLATE = "index.php?m=&c=jobs&a=jobs_show&id={id}"
WZRC_SEEK = "m=&c=jobs&a=jobs_show"


def looks_like_captcha(text):
    """短页面 + 验证提示词 → 判定为验证页。"""
    return len(text) < 5000 and any(k in text for k in CAPTCHA_HINTS)


class Fetcher:
    """带请求计数和间隔的取页器 —— 超上限直接抛错，防止"探着探着就抓起来了"。"""

    def __init__(self, delay):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delay = delay
        self.count = 0

    def get(self, url, timeout=20):
        if self.count >= MAX_REQUESTS:
            raise RuntimeError("请求数超过红线 %d，已中止" % MAX_REQUESTS)
        if self.count > 0:
            time.sleep(random.uniform(self.delay[0], self.delay[1]))
        self.count += 1
        return self.session.get(url, timeout=timeout, allow_redirects=True)


class OfflineFetcher:
    """离线模式：不发任何请求，get() 一律返回本地样本 HTML。

    robots.txt 返回「全部允许」，其余 URL 都返回同一份样本，
    这样主流程（robots → 首页 → 列表页）可以原样跑完，用于回归。
    """

    def __init__(self, html_text):
        self.html = html_text
        self.count = 0          # 真实请求数恒为 0

    def get(self, url, timeout=20):
        body = ("User-agent: *\nDisallow:\n"
                if "robots.txt" in url else self.html)
        return SimpleNamespace(status_code=200, text=body,
                               content=body.encode("utf-8"),
                               encoding="utf-8", headers={})


def strip_tags(html):
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def page_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# 详情链接 vs 列表/分类/公司/地图页的特征词
DETAIL_HINTS = re.compile(r"(jobs_show|show-|detail|jobinfo|/job/|position|zhiwei)", re.I)
LIST_HINTS = re.compile(r"(list|page=|p=|jobtag|tag=|cat|category|search|type=|sort=|keyword)", re.I)
NOT_DETAIL = re.compile(r"(com_show|comabout|company|a=jobs_list|jobtag|jobsort|a=map|c=map)", re.I)


def is_detail_link(full):
    """含 3 位以上数字，且像职位详情、不像列表/公司/地图/筛选页。"""
    if NOT_DETAIL.search(full):
        return False
    if not re.search(r"\d{3,}", full):
        return False
    if DETAIL_HINTS.search(full):
        return True
    # 兜底：查询串里带筛选/分页参数（jobarea1=、keyword=、page=…）的不是详情
    pu = urlparse(full)
    if pu.query and re.search(r"(^|&)(job\w*|page|p|sort|keyword|type)=", pu.query, re.I):
        return False
    return not LIST_HINTS.search(full)


def extract_links(html, base):
    """抽出疑似详情链接（去重，保序）。"""
    out, seen = [], set()
    for m in re.finditer(r"""href\s*=\s*["']([^"'#]+)["']""", html, flags=re.I):
        href = m.group(1).strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        full = urljoin(base, href)
        if urlparse(full).netloc != urlparse(base).netloc:
            continue
        if not is_detail_link(full):
            continue
        key = full.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def make_template(url):
    """把 URL 里的 id 抽掉，归纳成模板（去域名、去前导 /，id 整段替换）。"""
    p = urlparse(url)
    path = re.sub(r"[0-9a-fA-F]{8,}|\d+", "{id}", p.path.lstrip("/"))
    if p.query:
        q = re.sub(r"(\bid=)[^&]*", r"\1{id}", p.query, flags=re.I)
        q = re.sub(r"(?<![=\w{])\d+", "{id}", q)
        return path + "?" + q
    return path


def extract_main_list(html, base):
    """按 DOM 结构取主列表：**顺序最先出现**的合格卡片簇（≥3 条）。

    为什么不再用"最大簇"：推荐位/热招区往往比主列表更长，取最大会把侧栏
    算成主列表（yqrc 全页 82 条里主列表只有 20 条）。主列表在 DOM 里总是
    先出现，所以按首次出现位置取第一个合格簇。
    侧栏容器（side/recommend/hot/relate/guess/aside）直接排除。
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        groups, order = {}, {}
        for idx, a in enumerate(soup.find_all("a", href=True)):
            href = a["href"].strip()
            if not href or href.lower().startswith(("javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(base, href)
            if urlparse(full).netloc != urlparse(base).netloc:
                continue
            if not is_detail_link(full):
                continue
            p = a.find_parent(["li", "div", "tr", "article", "dd"])
            if p is None:
                continue
            cls = " ".join(p.get("class") or [])
            if re.search(r"(side|recommend|hot|relate|guess|aside|tag)", cls, re.I):
                continue
            key = (p.name, tuple(sorted(p.get("class") or [])))
            if key not in groups:
                groups[key] = []
                order[key] = idx
            groups[key].append(full)

        if groups:
            cands = [k for k in groups if len(groups[k]) >= 3]
            if cands:
                best_key = min(cands, key=lambda k: order[k])
            else:
                best_key = max(groups, key=lambda k: len(groups[k]))
            uniq, seen = [], set()
            for u in groups[best_key]:
                if u not in seen:
                    seen.add(u)
                    uniq.append(u)
            if uniq:
                return uniq
    except Exception:
        pass
    return extract_links(html, base)


def find_total_pages(html):
    patterns = [r"共\s*(\d+)\s*页", r"/(\d+)\s*页", r"页次[:：]?\s*\d+\s*/\s*(\d+)"]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def find_list_url(html, base, explicit):
    if explicit:
        return explicit, "命令行指定"
    pat = re.compile(r"职位|招聘|岗位|job|zhaopin", re.I)
    cands, seen = [], set()
    for m in re.finditer(r"""href\s*=\s*["']([^"'#]+)["']""", html, flags=re.I):
        href = m.group(1).strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        if not pat.search(href):
            continue
        full = urljoin(base, href)
        if urlparse(full).netloc != urlparse(base).netloc:
            continue
        if re.search(r"(c=map|a=map)", full, re.I):
            continue
        if full in seen:
            continue
        seen.add(full)
        cands.append(full)
    if not cands:
        return None, "未找到"
    # 优先真正的职位列表页（c=jobs&a=jobs_list / /joblist / /job），
    # 其次不带 jobtag/sort/keyword/cat 这类筛选参数，再次无查询串、路径短
    def score(u):
        pu = urlparse(u)
        is_list = 0 if (
            (re.search(r"c=jobs", u, re.I) and re.search(r"a=jobs_list", u, re.I))
            or re.search(r"/(joblist|jobs?)/?$", pu.path, re.I)
        ) else 1
        tagged = 1 if re.search(
            r"(jobsort|jobtag|sort=|tag=|cat|category|keyword|anxious|map_show)",
            u, re.I) else 0
        return (is_list, tagged, 1 if pu.query else 0, len(u))

    cands.sort(key=score)
    return cands[0], "首页自动发现"


def level_from_home(html, job_links):
    text_len = len(strip_tags(html))
    hits = sum(html.count(k) for k in KEYWORDS)
    if "__NEXT_DATA__" in html or "__INITIAL_STATE__" in html:
        return 2, "源码含 __NEXT_DATA__/__INITIAL_STATE__"
    if ("/api/" in html or "fetch(" in html) and hits < 3:
        return 1, "源码有 /api/ 或 fetch()，职位文案少"
    if len(job_links) >= 3:
        return 0, "首页可见 %d 条职位链接" % len(job_links)
    if text_len < 2048:
        return 3, "正文仅 %d 字符" % text_len
    return 3, "未见职位链接（正文 %d 字符）" % text_len


def check_status_robots(code):
    if code == 200:
        return "ok"
    if code == 404:
        return "none"
    return "blocked"      # 403 / 5xx / 其它一律当不可接


def main():
    ap = argparse.ArgumentParser(description="单站探测（2~4 个请求）")
    ap.add_argument("url", help="站点首页")
    ap.add_argument("--list-url", default=None, help="直接指定列表页")
    ap.add_argument("--delay", nargs=2, type=float, default=[4.0, 6.0],
                    metavar=("MIN", "MAX"), help="请求间隔秒，默认 4 6")
    ap.add_argument("--html", default=None,
                    help="离线模式：读本地 HTML 当列表页，0 请求（回归用）")
    args = ap.parse_args()

    home_url = args.url if args.url.startswith("http") else "https://" + args.url
    host = urlparse(home_url).netloc

    offline = args.html is not None
    offline_html = None
    if offline:
        op = Path(args.html)
        if not op.exists():
            print("样本不存在：%s" % op)
            return 2
        offline_html = op.read_text(encoding="utf-8", errors="replace")

    f = OfflineFetcher(offline_html) if offline else Fetcher(args.delay)

    result = {
        "url": home_url, "mode": "offline" if offline else "online",
        "robots": "", "robots_disallow": 0,
        "home_status": None, "home_bytes": 0, "title": "",
        "list_url": None, "list_status": None,
        "per_page": 0, "total_pages": None,
        "link_template": "", "link_samples": [],
        "level": None, "same_db_as_wzrc": None,
        "verdict": "", "est_total": None, "note": "",
    }
    rc = 1

    # ---------- 步骤 1：robots ----------
    robots_url = urljoin(home_url, "/robots.txt")
    try:
        r = f.get(robots_url)
        code = r.status_code
        result["robots"] = str(code)
        if check_status_robots(code) == "blocked":
            result["verdict"] = "不可接"
            result["note"] = "robots 返回 %s（403/5xx 视为 blocked，不重试）" % code
            _print_table(result, f.count)
            _save(result, host)
            return 2
        if code == 200:
            _kind = robots_rules.classify_robots(
                code, (getattr(r, "headers", {}) or {}).get("content-type"), r.text)
            if _kind == "unparsable":
                result["robots"] = "200/html"
                result["verdict"] = "不可接"
                result["note"] = "robots.txt 返回 200 但不是 robots 文本（HTML/挑战页）→ 视为不允许"
                _print_table(result, f.count)
                _save(result, host)
                return 2
            lines = r.text.splitlines()
            result["robots_disallow"] = len(
                [x for x in lines if x.strip().lower().startswith("disallow:")])
            rp = RobotFileParser()
            rp.parse(lines)
            if not rp.can_fetch(UA, home_url):
                result["verdict"] = "不可接"
                result["note"] = "robots 明确禁止抓取首页"
                _print_table(result, f.count)
                _save(result, host)
                return 2
    except Exception as exc:
        result["robots"] = "timeout/err"
        result["verdict"] = "不可接"
        result["note"] = "robots 请求失败：%s" % exc
        _print_table(result, f.count)
        _save(result, host)
        return 2

    # ---------- 步骤 2：首页 ----------
    try:
        r = f.get(home_url)
    except Exception as exc:
        result["verdict"] = "不可接"
        result["note"] = "首页请求失败：%s" % exc
        _print_table(result, f.count)
        _save(result, host)
        return 2

    if r.status_code != 200:
        result["home_status"] = r.status_code
        result["verdict"] = "不可接"
        result["note"] = "首页 HTTP %s" % r.status_code
        _print_table(result, f.count)
        _save(result, host)
        return 2

    html = r.text
    r.encoding = r.encoding or r.apparent_encoding
    result["home_status"] = r.status_code
    result["home_bytes"] = len(r.content)
    result["title"] = page_title(html)

    home_job_links = extract_links(html, home_url)
    level_home, level_reason = level_from_home(html, home_job_links)

    # 停放页 / 非招聘站：极小且一个关键词都没有才算（小站也可能有招聘文案）
    hits = sum(html.count(k) for k in KEYWORDS)
    if result["home_bytes"] < 500 and hits == 0:
        result["level"] = 3
        result["verdict"] = "不可接"
        result["note"] = "疑停放页或非招聘站（%d 字节，关键词 %d）" % (result["home_bytes"], hits)
        _print_table(result, f.count)
        _save(result, host)
        return 2

    # ---------- 步骤 3：列表页 ----------
    list_url, list_how = find_list_url(html, home_url, args.list_url)
    if offline:
        list_url, list_how = home_url, "离线样本"
    result["list_url"] = list_url
    list_html, list_bytes = None, 0
    if list_url:
        try:
            lr = f.get(list_url)
            result["list_status"] = lr.status_code
            if lr.status_code == 200:
                list_html = lr.text
                list_bytes = len(lr.content)
                list_text = strip_tags(list_html)
                if looks_like_captcha(list_text):
                    result["verdict"] = "不可接（列表页返回验证页）"
                    result["note"] = ("正文 %d 字符含验证提示，"
                                      "按红线停止，不重试不绕过" % len(list_text))
                    _print_table(result, f.count)
                    _save(result, host)
                    return 2
                links = extract_main_list(list_html, list_url)
                result["per_page"] = len(links)
                result["link_samples"] = links[:3]
                if links:
                    result["link_template"] = make_template(links[0])
                result["total_pages"] = find_total_pages(list_html)
        except Exception as exc:
            result["note"] = "列表页请求失败：%s" % exc

    # 层级：列表页有货就以列表页为准；列表页是空壳就单独判，别继承首页
    if result["per_page"] >= 3:
        result["level"] = 0
        level_reason = "列表页有 %d 条详情链接（服务端渲染）" % result["per_page"]
    elif list_html is not None:
        text_len = len(strip_tags(list_html))
        if "__NEXT_DATA__" in list_html or "__INITIAL_STATE__" in list_html:
            result["level"] = 2
            level_reason = "列表页含 __NEXT_DATA__/__INITIAL_STATE__（JS 加载数据）"
        elif list_bytes < 5000 or text_len < 500:
            result["level"] = 3
            level_reason = "列表页是 JS 空壳（%d 字节 / 正文 %d 字符）" % (list_bytes, text_len)
        else:
            result["level"] = level_home
            level_reason = level_reason + "（列表页未解析出详情链接）"
    else:
        result["level"] = level_home
    if not list_url:
        level_reason += "；未找到列表入口（%s）" % list_how
    result["note"] = level_reason

    # ---------- 步骤 4：同库校验（只在形态与 wzrc 一致、且探的不是 wzrc 自己时） ----------
    if result["link_template"] == WZRC_TEMPLATE and result["link_samples"] and "wzrc.net" not in host:
        m = re.search(r"id=(\d+)", result["link_samples"][0])
        if m:
            probe = "https://www.wzrc.net/index.php?m=&c=jobs&a=jobs_show&id=%s" % m.group(1)
            try:
                wr = f.get(probe)
                same = False
                if wr.status_code == 200:
                    wt = wr.text
                    same = bool(page_title(wt)) and any(k in wt for k in KEYWORDS)
                result["same_db_as_wzrc"] = same
            except Exception as exc:
                result["same_db_as_wzrc"] = None
                result["note"] += "；同库校验失败：%s" % exc
    else:
        result["same_db_as_wzrc"] = None

    # ---------- 结论 ----------
    per_page = result["per_page"]
    total_pages = result["total_pages"]
    if per_page:
        result["est_total"] = per_page * total_pages if total_pages else None

    if result["same_db_as_wzrc"] is True:
        result["verdict"] = "不可接（与 wzrc 同库）"
        rc = 2
    elif result["level"] in (0, 1, 2) and per_page >= 3:
        result["verdict"] = "可接"
        rc = 0
    elif result["level"] == 3:
        result["verdict"] = "不确定（疑似 JS 空壳，等 Playwright）"
        rc = 1
    else:
        result["verdict"] = "不确定（没找到列表页 / 页数未知）"
        rc = 1

    _print_table(result, f.count)
    _save(result, host)
    return rc


def _print_table(res, count):
    def line(k, v):
        print("%-10s %s" % (k, v))
    print("")
    line("站点", res["url"])
    line("robots", "%s（disallow %s 条）" % (res["robots"], res["robots_disallow"]))
    line("首页", "%s / %s B / %s" % (res["home_status"], format(res["home_bytes"], ","),
                                     ('"%s"' % res["title"]) if res["title"] else "(无标题)"))
    line("列表页", "%s / 每页 %s 条 / 共 %s 页" % (
        res["list_status"], res["per_page"],
        res["total_pages"] if res["total_pages"] else "未知"))
    line("链接形态", res["link_template"] or "(未取到)")
    line("层级", "%s（%s）" % (res["level"] if res["level"] is not None else "—", res["note"]))
    same = res["same_db_as_wzrc"]
    line("同库校验", "未执行（形态与 wzrc 不同）" if same is None
         else ("是（wzrc 能打开同一 id）" if same else "否（独立库）"))
    print("-" * 40)
    line("请求数", "%d / %d" % (count, MAX_REQUESTS))
    line("结论", ("✅ " if res["verdict"].startswith("可接") else "⚠️ ")
         + res["verdict"] + (
             "（预估 %s 条 / %s 页）" % (res["est_total"], res["total_pages"])
             if res["est_total"] else ""))


def _save(res, host):
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe = host.replace(":", "_").replace("/", "_")
    p = OUT / ("probe-one-%s-%s.json" % (safe, stamp))
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细已写入：%s" % p.name)


if __name__ == "__main__":
    sys.exit(main())