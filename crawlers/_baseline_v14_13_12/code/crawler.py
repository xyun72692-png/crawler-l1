# -*- coding: utf-8 -*-
"""
通用爬虫模板（crawler.py）
=========================

换一个网站要改的地方只有两处，都在下面标了 【改这里】：

    1. CONFIG          —— 网址规律、翻几页、间隔多少秒
    2. parse_list()    —— 从一页 HTML 里把字段抠出来

其它东西（限速、重试、断点续跑、去重、血缘字段、日志、落盘）都是通用的，不用动。

低调原则（本脚本内置）：
    * 每个请求之间随机等 1.2~2.5 秒，不并发、不抢带宽
    * 失败重试最多 3 次，指数退避，不会死循环轰炸对方
    * 开跑前检查 robots.txt；对方写了不允许就立刻退出
    * HTTP 429/503 当成"请慢一点"，退避重试；403/401/451 是拒绝，不重试
    * 断点续跑：中断后重跑不会从头再来，也不会重复抓

运行：
    D:\\agent-work\\venv\\Scripts\\python.exe D:\\agent-work\\crawlers\\crawler.py
"""

import hashlib
import ipaddress
from datetime import date
import json
import os
import random
import re
import socket
import sys
import time
import urllib.robotparser        # 仅保留兼容；判定已改用 robots_rules（RFC 9309）
import robots_rules
import identity            # v14 阶段 0：唯一身份源
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, urlencode, parse_qsl

import requests

import gate as gate_mod
from gate import RequestBudgetExceeded, TimeBudgetExceeded
from bs4 import BeautifulSoup

# 让中文在 Windows 控制台不乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

# =====================================================================
# 详情阶段默认参数
#
# 背景：阶段0 之前，"进详情页补字段"这件事是由 sites/<job>.py 里的
# detail_hook 自己实现的 —— 每个站要复制 100 行，而且复制时容易漏掉
# 重试、robots、状态码这些公共部分。通用化之后：
#   引擎管：robots / 限速 / 超时 / 重试 / 退避 / 状态码 / 时间戳 / 失败计数 / 熔断
#   站点管：parse_detail(html) -> dict        （只有这一个函数）
#
# 想覆盖任何一项，在站点 CONFIG 里写 "detail": {...} 即可，只写要改的那几项。
# =====================================================================
DETAIL_DEFAULTS = {
    "enabled": False,        # 默认关；站点写了 enabled=True 才进详情页
    "delay_min": 1.0,        # 详情页间隔（比列表页可以快一点，因为单页更小）
    "delay_max": 2.0,
    "timeout": 25,
    "retries": 2,            # 详情页失败要能重来一次（旧实现完全没有重试）
    "backoff": 2.0,
    "abort_on": [401, 403, 429, 451],   # 遇到就整体停（不是"这页跳过"，是"别再说了"）
    # 熔断：失败条数 / 计划条数 >= 这个比例就停，避免站方已经挂了还硬扫几百条。
    # 注意口径：分母是"这一页计划抓多少条"，不是"已经试了多少条"。
    #   20 条里失败 10 条 → 10/20 = 0.5 → 触发（这就是 codex 指出的那个口径问题）
    # 设 0 表示关闭熔断。
    "max_fail_ratio": 0.5,
    "required": [],          # 详情结果里必须有值的字段，缺了算这条失败
    "respect_robots": True,  # 详情 URL 也要过 robots（旧实现没有这一项）
    "max_items_per_page": 0, # 0=不限；调试时可只抓前 N 条
}


# =====================================================================
# 阶段A：Retry-After / canary 软封 / 全局冷却
#
# 为什么要有这一套：2026-11-11 那次 wzrc 被封后，我们仍然继续发了 53 次请求。
# 站点不是返回 403，而是"HTTP 200 + 3103 字节的空页"——引擎把它当成"空页"，
# 一路翻到最后一页。这属于"被封了还在敲门"，必须从机制上堵住。
# =====================================================================

# 一次运行内的 Retry-After 统计（单线程，用模块级 dict 就够了）
_RETRY_META = {"waits": 0, "max_sec": 0}

# 最后一次响应的元信息（供报告与软封证据用；每天状态下都是"刚刚那次响应"）
_LAST_META = {"bytes": 0, "server": "", "cf_ray": "", "url": "", "referer": ""}


def _retry_after_seconds(value):
    """
    把 Retry-After 解析成秒数；解析不了返回 None。

    两种合法格式：纯数字（秒）、HTTP-date（GMT 时间）。
    夹到 0..300 —— 站点说"等 3 天"的时候我们不能真等 3 天。
    """
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if v.isdigit():
        sec = int(v)
    else:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(v)
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            sec = int((dt - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            return None
    return max(0, min(300, sec))


def _note_resp(resp, referer=""):
    """记下这次响应的字节数与几个可作证据的响应头。"""
    try:
        # 用原始字节：resp.text 是解码后的字符串，
        # 页面没声明 charset（或被猜成 gbk/iso-8859-1）时 encode 回去的长度不等于真实字节数。
        raw = getattr(resp, "content", None)
        _LAST_META["bytes"] = len(raw) if raw is not None else len(
            (resp.text or "").encode("utf-8", errors="ignore"))
    except Exception:
        _LAST_META["bytes"] = 0
    try:
        h = resp.headers or {}
        _LAST_META["server"] = h.get("Server", "") or ""
        _LAST_META["cf_ray"] = h.get("CF-RAY", "") or ""
    except Exception:
        _LAST_META["server"] = ""
        _LAST_META["cf_ray"] = ""
    _LAST_META["url"] = getattr(resp, "url", "") or ""
    _LAST_META["referer"] = referer or ""


SOFT_BLOCK_DEFAULTS = {
    "enabled": False,
    # 冷却分组：同一家站点的多个子域共用一把锁（WAF 通常按 IP 封，子站会一起死）。
    # 留空 = 按 host 各自锁。
    "group": "",
    # 已知一定有结果的页面（canary）。空页出现时用它区分"真空"和"被封"。
    "canary_url": "",
    # 冷却阶梯：第 1 次封 → 2 小时；第 2 次 → 6 小时；之后 24 小时
    "cooldown_sec": [7200, 21600, 86400],
    # 只作证据，不作唯一判据（站点改模板就失效，不能拿它当判决书）
    "markers": ["no_page_group"],
}


def soft_block_cfg():
    """把 SOFT_BLOCK_DEFAULTS 与站点 CONFIG["soft_block"] 合并。"""
    c = dict(SOFT_BLOCK_DEFAULTS)
    c.update(CONFIG.get("soft_block") or {})
    return c


def query_fingerprint(url):
    """
    把 URL 里的"筛选条件"压成一个短指纹（去掉 page）。

    为什么需要：同一个 --job 换筛选（WZ_SETTR / WZ_CITY / WZ_WAGE / WZ_TRADE…）时，
    第 1 页已经不是同一批数据了。若沿用旧断点：
      · pages_done 里有 1..5 → 新条件的第 1..5 页被"跳过"，一个请求都不发
      · pages_declared 是旧条件的 M → coverage 算成 1.0
      · 最后报告 success —— 最恶劣的那种"假成功"
    所以条件一变，页码映射就作废；去重键 seen_keys 必须保留（它跟页码无关）。
    """
    try:
        parts = urlsplit(url)
        pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
        pairs.sort()
        raw = (parts.path or "/") + "?" + urlencode(pairs)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    except Exception:
        return ""


def total_pages_supported(site_mod=None):
    """这个站点到底有没有配"总页数声明"的来源？没配就静默跳过，不写 anomaly。"""
    if CONFIG.get("total_pages_pattern"):
        return True
    return site_mod is not None and hasattr(site_mod, "parse_total_pages")


def coverage_mode():
    """'full'（默认，要求抓完整个结果集）/ 'window'（只维护最近窗口，覆盖不全属正常）"""
    v = (CONFIG.get("coverage_mode") or "full").strip().lower()
    return v if v in ("full", "window") else "full"


def declared_total_pages(payload, page_url, site_mod=None):
    """
    从**服务器渲染的第一页 HTML**里读"共 M 页"。

    优先级：
      1. 站点模块提供 parse_total_pages(html, page_url) → 用它的返回值
      2. CONFIG["total_pages_pattern"] 正则（第 1 个分组）
    取不到 / 解析失败 / 值不合理（<1）→ 返回 None（调用方按配置页数继续跑）。

    为什么要读它：配置里的页数是拍脑袋的。
      配多了 → 后面全是空页 → 假告警（partial/empty_page_seen）
      配少了 → 只抓一部分却报 success → 假成功（更危险）
    """
    if not payload or not isinstance(payload, str):
        return None
    pat = CONFIG.get("total_pages_pattern") or ""
    if site_mod is not None and hasattr(site_mod, "parse_total_pages"):
        try:
            m = site_mod.parse_total_pages(payload, page_url)
            if m:
                return int(m)
        except Exception:
            pass
    if not pat:
        return None
    try:
        mo = re.search(pat, payload)
        if not mo:
            return None
        m = int(mo.group(1))
        return m if m >= 1 else None
    except Exception:
        return None


def probe_canary(sess, log, sb, parse_html):
    """
    打一次 canary 并解析出卡片数。

    返回 (cards, bytes, skip_reason)：
        cards      int ≥0 = 解析到的卡片数；None = 无法判定
        skip_reason  "" 或 "robots_denied"（canary 自己也被 robots 禁）

    canary 必须和普通页一样过 robots：它也是对这个站点发请求，
    不能因为"它是探针"就绕开规则（robots 规则已缓存，查一次零成本）。
    """
    curl = sb.get("canary_url") or ""
    if not curl:
        return None, 0, "no_canary_url"
    if CONFIG.get("respect_robots", True) and not url_allowed(curl, log):
        log("  canary 被 robots 禁止 → 无法用它判定（不算软封）")
        return None, 0, "robots_denied"
    ref = "%s://%s/" % (urlsplit(curl).scheme, urlsplit(curl).netloc)
    try:
        code, payload = fetch_page(sess, curl, log, referer=ref)
    except (RequestBudgetExceeded, TimeBudgetExceeded):
        raise                          # 闸门停止：交给页面循环统一收尾
    except Exception as e:
        log("  canary 抓取失败 %s → 无法判定" % type(e).__name__)
        return None, int(_LAST_META.get("bytes") or 0), "error"
    nbytes = int(_LAST_META.get("bytes") or 0)
    if not payload:
        return None, nbytes, "empty_payload"
    try:
        rows = parse_html(payload, curl)
    except Exception as e:
        log("  canary 解析失败 %s → 无法判定" % type(e).__name__)
        return None, nbytes, "parse_error"
    return len(rows), nbytes, ""


def cooldown_group(host):
    """冷却按组算：站点配了 soft_block.group 就用它，否则用 host。"""
    g = (soft_block_cfg().get("group") or "").strip()
    return g or host


def cooldown_path(host):
    """
    冷却文件路径。**必须**从 state_dir 派生：
    测试用 CRAWLER_STATE_DIR 隔离，写死全局目录会污染真实运行目录。
    传进来的是"组名"（cooldown_group 的结果），不是裸 host。
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", host or "unknown")
    return os.path.join(CONFIG["state_dir"], "_cooldown_%s.json" % safe)


def load_cooldown(host, log=None):
    """
    读冷却文件。文件不存在 → None（正常放行）。

    **文件存在但读不出来 → 按损坏处理，并且一次做三件事**：
      1. 把坏文件改名隔离成 `*.corrupt-<时间戳>`（留证据，不直接删）
      2. 写一份**合法**冷却 JSON（reason=cooldown_file_corrupt，2 小时）
      3. 日志写明原路径/隔离后路径/恢复方式

    为什么必须落一份合法文件：只在内存里造一个"now+2h"的假冷却，
    下次启动又会从坏文件重新算出新的 now+2h —— 等于**永久锁死这个站**。
    落盘之后，第二次读到的就是合法文件，到期自然放行。
    """
    p = cooldown_path(host)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("不是 JSON 对象")
        if cooldown_until(data) is None:
            # JSON 合法但 until 丢了/写坏了：同样属于"读不出有效期"，按损坏处理
            raise ValueError("until 字段缺失或无法解析")
        return data
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:60])
        stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
        quarantine = "%s.corrupt-%s" % (p, stamp)
        try:
            os.replace(p, quarantine)
        except Exception:
            quarantine = "(改名失败，原文件仍在原地)"
        data, sec = save_cooldown(host, "cooldown_file_corrupt", 0,
                                  {"parse_error": err, "quarantined_to": quarantine})
        if log:
            log("!! 冷却文件损坏（%s）" % err)
            log("!!   原文件：%s" % p)
            log("!!   已隔离：%s" % quarantine)
            log("!!   已写入合法冷却 %d 秒（到 %s）；到期自动恢复，也可手工删掉该文件"
                % (sec, data.get("until")))
        return data


def cooldown_until(cd):
    """返回冷却到期时间（datetime）或 None。"""
    if not cd:
        return None
    try:
        return datetime.fromisoformat(cd.get("until"))
    except Exception:
        return None


def save_cooldown(host, reason, strikes, evidence):
    """写冷却文件；strikes 递增决定冷却时长。"""
    sb = soft_block_cfg()
    ladder = list(sb.get("cooldown_sec") or SOFT_BLOCK_DEFAULTS["cooldown_sec"])
    idx = min(max(strikes - 1, 0), len(ladder) - 1)
    sec = int(ladder[idx])
    until = datetime.now(TZ) + timedelta(seconds=sec)
    data = {
        "host": host,
        "until": until.isoformat(timespec="seconds"),
        "reason": reason,
        "strikes": strikes,
        "evidence": evidence,
        "updated_at": now_iso(),
    }
    p = cooldown_path(host)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return data, sec


def detail_cfg():
    """把 DETAIL_DEFAULTS 与站点 CONFIG["detail"] 合并，返回一份独立副本。"""
    c = dict(DETAIL_DEFAULTS)
    c.update(CONFIG.get("detail") or {})
    return c


# =====================================================================
# 【改这里 1/2】站点配置
# =====================================================================
CONFIG = {
    "job": "books",                                    # 任务名，决定所有文件名
    "url_template": "https://books.toscrape.com/catalogue/page-{page}.html",
    "page_start": 1,
    "page_end": 50,                                    # 练习站一共 50 页、1000 本书

    # 速度：随机区间（秒）。不要低于 1.0，这是"不引人注意"的核心
    "delay_min": 1.2,
    "delay_max": 2.5,

    "timeout": 20,
    "retries": 3,
    "backoff": 2.0,                                    # 重试等待 = backoff ** 次数
    "ua": identity.UA,

    "respect_robots": True,
    # v14 阶段 1：传输层三档。plain=现在的 GatedSession（默认，行为不变）
    # cffi=curl_cffi 适配层（TLS 指纹对齐，闸门照旧）；browser=阶段 2 渲染通道（未接）
    "transport": "plain",
    "dedup_key": "detail_url",                         # 用哪个字段判重

    # ---- 分页方式（阶段2）----
    # number：按页码模板翻页（url_template 里的 {page}），断点记 pages_done
    # next  ：从当前页 HTML 里读"下一页"链接，断点记 urls_done + next_url
    # 两种模式的断点【分开存】，绝不互相污染。
    "paginate": "number",
    "max_pages": 200,       # next 模式的安全阀：最多翻这么多页就停

    # 详情阶段：留空=用 DETAIL_DEFAULTS（即不启用）；站点 CONFIG 里覆盖
    "detail": {},
    # 列表数据是 HTML 还是 JSON（阶段3）。json 时站点不用写 parse_list，
    # 解析全看下面的 CONFIG["json"]。
    "response": "html",
    "json": {},
    # 附件下载（阶段4）：留空=不启用
    "attachments": {},
    # 开跑前先把"上次没抓全的详情"补上（不重抓列表页、不重抓已成功的）
    "repair_details": True,

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
}


# =====================================================================
# 【改这里 2/2】把一页 HTML 解析成若干条记录
# =====================================================================
def parse_list(html, page_url):
    """
    输入：一页的 HTML 文本 + 这个页面的网址
    输出：list[dict]，每个 dict 是一行数据

    换站点时只要保证"输出是 list[dict]"就行，字段名自己定。
    返回空 list 表示这页没数据（不会报错，会记一笔"空页"）。
    """
    soup = BeautifulSoup(html, "lxml")
    rows = []

    for art in soup.select("article.product_pod"):
        a = art.select_one("h3 a")
        if a is None:
            continue

        title = (a.get("title") or a.get_text(strip=True) or "").strip()
        href = a.get("href") or ""
        detail_url = urljoin(page_url, href)

        price_el = art.select_one("p.price_color")
        price = price_el.get_text(strip=True) if price_el else ""

        # 评分藏在 class 里，形如 class="star-rating Three"
        rating = ""
        star = art.select_one("p.star-rating")
        if star:
            for c in star.get("class", []):
                if c != "star-rating":
                    rating = c
                    break

        avail_el = art.select_one("p.instock.availability")
        availability = avail_el.get_text(" ", strip=True) if avail_el else ""

        thumb = art.select_one("div.image_container img")
        thumb_url = urljoin(page_url, thumb.get("src", "")) if thumb else ""

        rows.append({
            "title": title,
            "price_raw": price,
            "rating": rating,
            "availability": availability,
            "detail_url": detail_url,
            "thumb_url": thumb_url,
        })

    return rows


# =====================================================================
# 以下都是通用引擎，正常情况下不需要改
# =====================================================================

def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


class Logger:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8", newline="\n")

    def __call__(self, msg):
        line = "[%s] %s" % (datetime.now(TZ).strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()

    def close(self):
        try:
            self.fh.close()
        except Exception:
            pass


class GatedSession(requests.Session):
    """所有出网请求都过闸门的 Session。

    为什么挂 send() 而不是 request()：requests 跟随 301/302 时走的是 Session.send()，
    挂在 request() 上会让**每一次重定向跳转都漏计**，预算和速率都会被低估。
    """

    def send(self, request, **kw):
        host = (urlsplit(request.url).hostname or "").lower()   # hostname 去端口，netloc 会带 :port
        g = gate_mod.current_gate()
        if g is not None and not gate_mod.host_exempt(host):
            g.before(host)
        _note_request(host)
        return super().send(request, **kw)


def session_factory():
    # transport=cffi → 走适配层（闸门在适配层里逐跳调用，语义与 GatedSession 一致）
    if (CONFIG.get("transport") or "plain").lower() in ("cffi", "curl", "curl_cffi"):
        import curl_adapter
        return curl_adapter.build_session(
            "cffi", timeout=CONFIG.get("timeout", 20),
            headers={"User-Agent": CONFIG["ua"],
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    s = GatedSession()
    s.headers.update({
        "User-Agent": CONFIG["ua"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })
    return s


_ROBOTS = {"text": None, "loaded": False, "url": "", "ignore": False,
           "status": "", "bytes": 0, "groups": 0}

# 本进程真实出网次数（与闸门计数交叉核对用）
_REQ_META = {"total": 0, "by_host": {}}


def _note_request(host):
    _REQ_META["total"] = _REQ_META.get("total", 0) + 1
    hb = _REQ_META.setdefault("by_host", {})
    hb[host] = hb.get(host, 0) + 1
# 判定留痕：每次被 robots 拒绝都记一条，供报告与"停下来问你"用
_ROBOTS_DECISIONS = []
ROBOTS_DECISION_LIMIT = 10          # 详情/附件被禁累计到这个数就停
ROBOTS_DECISION_RATIO = 0.20        # 或达到尝试数的 20% 也停
_ROBOTS_STOP = {"reason": ""}


def record_robots_decision(url, stage, rule, line_no, action):
    _ROBOTS_DECISIONS.append({
        "url": url, "stage": stage, "rule": rule,
        "rule_line": line_no, "verdict": "deny", "action": action,
    })


def robots_decision_block(log, stage, url, rule, line_no, extra=""):
    """被禁时打印决策块——让人一眼看懂发生了什么、有哪些选项。"""
    log("")
    log("[!] robots 禁止抓取（%s）" % stage)
    log("    站点   %s" % url)
    log("    规则   %s   （第 %s 行）" % (rule or "（无规则，取不到 robots）", line_no or "-"))
    if extra:
        log("    %s" % extra)
    log("    → 该操作已立即禁止，一个请求都没发。要继续有三种办法：")
    log("       ① 看 robots 里有没有针对我们 UA 的更宽组（需要你确认）")
    log("       ② --ignore-robots 强制覆盖（写进报告 overrides，终端告警）")
    log("       ③ 放弃这个站/这一类页面")
    log("")


def load_robots(sess, url, log):
    """
    取一次 robots.txt 并构造解析器，供后面每一个页面复用。

    为什么改成这样：早期版本只对第一页做检查，robots 完全可以允许 /page-1
    而禁止 /page-50。现在每页都用同一份规则逐个判断。

    保守原则（失败即拒绝）：
      * 404 = 没有 robots 文件 = 未设限 → 放行
      * 401/403 = 站点拒绝你读规则 → 视为不允许
      * 其它非 200 / 网络异常 → 视为不允许
    """
    if not CONFIG["respect_robots"]:
        log("robots: 检查已关闭（respect_robots=False）")
        _ROBOTS["loaded"] = True
        _ROBOTS["text"] = None
        return True

    from urllib.parse import urlsplit
    parts = urlsplit(url)
    robots_url = "%s://%s/robots.txt" % (parts.scheme, parts.netloc)
    _ROBOTS["url"] = robots_url

    try:
        # robots.txt 会偶发超时/5xx（foodmate 实测过）。单次失败就结束整次采集太脆：
        # 超时/5xx 重试一次；401/403 是明确拒绝，不重试。
        r = None
        for attempt in (1, 2):
            try:
                r = sess.get(robots_url, timeout=CONFIG["timeout"])
            except Exception as e:
                if attempt == 1:
                    log("robots: 第 1 次请求失败（%s）→ 1 秒后重试" % type(e).__name__)
                    time.sleep(1.0)
                    continue
                log("robots: 检查失败（%s）→ 保守起见视为不允许，退出" % e)
                return False
            if r.status_code >= 500 and attempt == 1:
                log("robots: 第 1 次返回 HTTP %d → 1 秒后重试" % r.status_code)
                time.sleep(1.0)
                continue
            break

        if r.status_code == 404:
            log("robots: %s 不存在（404）→ 未设限，全部放行" % robots_url)
            _ROBOTS["text"] = None
            _ROBOTS["loaded"] = True
            _ROBOTS["status"] = "absent"
            _ROBOTS["bytes"] = 0
            _ROBOTS["groups"] = 0
            return True
        if r.status_code in (401, 403):
            log("robots: %s 返回 %s（拒绝我读规则）→ 视为不允许抓取，退出"
                % (robots_url, r.status_code))
            _ROBOTS["status"] = "denied"
            return False
        if r.status_code != 200:
            log("robots: %s 返回 %s → 保守起见视为不允许，退出"
                % (robots_url, r.status_code))
            _ROBOTS["status"] = "denied"
            return False

        text = r.text or ""
        ctype = r.headers.get("content-type") or ""
        kind = robots_rules.classify_robots(200, ctype, text)
        if kind == "unparsable":
            # 2026-11-15：WAF/软 404 会把 HTML 当 robots 返回。
            # 旧实现只看状态码 200，于是"零规则 = 全放行"——把禁止读成了允许。
            first = text.strip().splitlines()[0][:80] if text.strip() else "（空）"
            log("robots: %s 返回 200，但内容不是 robots（%s，%d 字符）→ 视为不允许抓取，退出"
                % (robots_url, ctype or "未知类型", len(text)))
            log("        首行：%s" % first)
            _ROBOTS["status"] = "unparsable"
            _ROBOTS["bytes"] = len(text.encode("utf-8", "ignore"))
            _ROBOTS["groups"] = 0
            return False
        _ROBOTS["text"] = text
        _ROBOTS["loaded"] = True
        _ROBOTS["status"] = "ok"
        _ROBOTS["bytes"] = len(text.encode("utf-8", "ignore"))
        _ROBOTS["groups"] = len(robots_rules.parse_groups(text))
        log("robots: %s 已加载（%d 字节 / %d 组规则），将逐页判断"
            % (robots_url, _ROBOTS["bytes"], _ROBOTS["groups"]))
        _cd = robots_crawl_delay()
        if _cd > 0:
            log("robots: Crawl-delay=%.1f 秒 → 站内请求间隔按 max(配置, %.1f) 执行"
                % (_cd, _cd))
        return True
    except Exception as e:
        log("robots: 检查失败（%s）→ 保守起见视为不允许，退出" % e)
        return False


def url_allowed(url, log, stage="page"):
    """对单个 URL 判断 robots 是否允许（RFC 9309：通配符 + 最长匹配 + Allow 优先）。"""
    if not _ROBOTS["loaded"]:
        return False
    if _ROBOTS["text"] is None:
        return True                      # robots 404 / 已关闭 = 未设限
    allowed, rule, line_no = robots_rules.decide(_ROBOTS["text"], CONFIG["ua"], url)
    if allowed:
        return True
    if _ROBOTS.get("ignore"):
        record_robots_decision(url, stage, rule, line_no, "overridden")
        log("  [覆盖] --ignore-robots 生效，放行：%s（原本被 %s 禁止）" % (url, rule))
        return True
    record_robots_decision(url, stage, rule, line_no, "skipped")
    log("  robots 禁止抓取该页：%s  ← %s（第 %d 行）" % (url, rule, line_no))
    return False


def robots_crawl_delay():
    """robots 里针对我们 UA 的 Crawl-delay（秒）；没有则 0。

    v14.13.3：以前只有附件用它，列表页/详情页没接。
    """
    text = _ROBOTS.get("text")
    if not _ROBOTS.get("loaded") or not text:
        return 0.0
    try:
        return float(robots_rules.crawl_delay(text, CONFIG["ua"]) or 0)
    except Exception:
        return 0.0


def polite_sleep(delay_min, delay_max):
    """站内请求间隔 = max(配置抖动, robots Crawl-delay)。

    站点写了 Crawl-delay 就按它来，哪怕比我们的 12 次/分更慢。
    """
    wait = random.uniform(float(delay_min), float(delay_max))
    floor = robots_crawl_delay()
    if floor > wait:
        wait = floor
    if wait > 0:
        time.sleep(wait)
    return wait


def _fetch_core(sess, url, log, retries, timeout, backoff, tag="", referer=None):
    """
    带重试的 GET 内核。参数全显式传，不读全局 CONFIG ——
    这样详情页可以用自己的一套（重试 2 次/超时 25 秒），不跟列表页绑死。

    返回 (status_code, text) 或 (None, None)（= 重试耗尽）。
    429/503 视为"太快了"退避重试；403/401/451 是拒绝，直接返回不重试。
    """
    pre = ("[%s] " % tag) if tag else ""
    hdr = {"Referer": referer} if referer else None
    for attempt in range(1, retries + 1):
        try:
            r = sess.get(url, timeout=timeout, headers=hdr, allow_redirects=True)
            code = r.status_code
            _note_resp(r, referer)

            if code == 200:
                # 编码兜底：没有声明 charset 时按 apparent_encoding
                if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                    r.encoding = r.apparent_encoding or "utf-8"
                return code, r.text

            if code in (429, 503):
                # 站点若给了 Retry-After，就按它说的等；没有才用自己的退避。
                ra = _retry_after_seconds(r.headers.get("Retry-After"))
                back = backoff ** attempt * 3
                wait = max(ra or 0, back)
                why = ("Retry-After=%ds" % ra) if ra is not None else ("退避=%.1fs" % back)
                _RETRY_META["waits"] += 1
                _RETRY_META["max_sec"] = max(_RETRY_META["max_sec"], int(wait))
                log("  %sHTTP %s 被限速 → 等 %.1f 秒（%s，第 %d/%d 次）"
                    % (pre, code, wait, why, attempt, retries))
                time.sleep(wait)
                continue

            if code == 403:
                # 403 是"我不想给你看"，不是"你太快了"。重试只会让站点更烦。
                log("  %sHTTP 403 被拒 → 不重试（这是拒绝，不是限速）" % pre)
                return code, None

            if code in (401, 451):
                log("  %sHTTP %s → 不重试（需要授权/因法律原因不可用）" % (pre, code))
                return code, None

            # 其它 4xx 不重试（重试也没用）
            if 400 <= code < 500:
                log("  %sHTTP %s（4xx，不重试）" % (pre, code))
                return code, None

            wait = backoff ** attempt
            log("  %sHTTP %s → 等 %.1f 秒重试（第 %d/%d 次）"
                % (pre, code, wait, attempt, retries))
            time.sleep(wait)

        except requests.RequestException as e:
            wait = backoff ** attempt
            log("  %s网络异常 %s → 等 %.1f 秒重试（第 %d/%d 次）"
                % (pre, type(e).__name__, wait, attempt, retries))
            time.sleep(wait)

    return None, None


def fetch(sess, url, log, referer=None):
    """列表页用的 GET：沿用 CONFIG 里的重试/超时/退避。referer 按页传。"""
    return _fetch_core(sess, url, log,
                       CONFIG["retries"], CONFIG["timeout"], CONFIG["backoff"],
                       referer=referer)


# =====================================================================
# 阶段4：附件下载
#
# 站点只要在记录里给一个 attachments 字段（字符串列表或 [{url,name}] 列表），
# 引擎负责剩下的一切：robots、类型、大小、配额、重定向后的最终地址、落盘、SHA256。
#
# 安全默认值：拒绝非 http(s)、拒绝内网/回环地址、拒绝可执行扩展名。
# 测试时用 allow_private_hosts=True 放行 127.0.0.1（mock 只能跑在本机）。
# =====================================================================
ATTACH_DEFAULTS = {
    "enabled": False,
    "dir": r"D:\agent-work\data\attachments",
    "max_files_per_record": 5,
    "max_total_bytes": 500 * 1024 * 1024,     # 整轮任务累计上限
    "max_file_bytes": 50 * 1024 * 1024,       # 单文件上限
    "timeout": 60,
    "retries": 1,                             # 网络错误/5xx 的重试次数
    "max_redirects": 5,
    "respect_robots": True,
    "follow_crawl_delay": True,               # 遵守 robots 里的 Crawl-delay
    "delay_min": 0.5,                         # 附件之间的请求间隔（下限）
    "delay_max": 1.0,
    "allow_hosts": [],                        # 非空时：只允许这些 host（优先于 allow_private_hosts）
    "allow_private_hosts": False,             # 生产环境保持 False
    "content_type_allow": [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",           # 很多站把 pdf 报成这个；靠扩展名再判一次
        "text/plain",
        "text/csv",
    ],
    "ext_deny": [".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".msi",
                 ".ps1", ".vbs", ".js", ".jar", ".sh", ".py", ".apk", ".dmg"],
    # 扩展名白名单：留空=不启用；填了就只收这些扩展名（比"只靠黑名单"稳）
    "ext_allow": [],
    # 文件头校验：按扩展名对照 magic bytes，防"改名成 .pdf 的 exe"
    "sniff_magic": False,
    "check_dns": True,          # 解析域名并检查 IP（防 DNS 指向内网）
}

class BadDataFile(Exception):
    """数据文件有坏行：宁可中止，也不能在重写时把它们丢掉。"""


# 附件里"可以再试一次"的状态（永久性拒绝不在其中：类型不对、太大、超条数、
# robots 明确禁止、地址不安全，这些重试也不会变）
ATTACH_RETRY_STATES = {"download_failed", "robots_check_failed", "skipped_budget"}

# 常见文档类型的文件头（够用即可，不追求全覆盖）
MAGIC_BY_EXT = {
    ".pdf": [b"%PDF-"],
    ".zip": [b"PK\x03\x04"],
    ".docx": [b"PK\x03\x04"],
    ".xlsx": [b"PK\x03\x04"],
    ".pptx": [b"PK\x03\x04"],
    ".doc": [b"\xd0\xcf\x11\xe0"],
    ".xls": [b"\xd0\xcf\x11\xe0"],
    ".ppt": [b"\xd0\xcf\x11\xe0"],
}


def attach_cfg():
    c = dict(ATTACH_DEFAULTS)
    c.update(CONFIG.get("attachments") or {})
    return c


def _origin_of(url):
    p = urlsplit(url)
    return "%s://%s" % ((p.scheme or "http").lower(), (p.netloc or "").lower())


def _host_is_private(host):
    """回环/内网/链路本地/保留地址一律算私有。"""
    host = (host or "").split(":")[0].strip("[]").lower()
    if not host or host in ("localhost", "localhost.localdomain"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False            # 域名：不做解析，交给 DNS/网络层
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


# 每个 origin 的 robots 规则缓存：origin -> ("allow"|"rules"|"fail", payload, note)
_ORIGIN_ROBOTS = {}
_ORIGIN_LAST = {}
_DNS_CACHE = {}


def _fake_dns_map():
    """测试钩子：CRAWLER_FAKE_DNS="name=ip,name2=ip2"。生产默认空。"""
    raw = os.environ.get("CRAWLER_FAKE_DNS") or ""
    out = {}
    for part in raw.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip().lower()] = v.strip()
    return out


def _resolve_ips(host):
    """
    解析域名到 IP 列表（带缓存；测试可用 CRAWLER_FAKE_DNS 注入）。

    为什么要做：只判字面 host 挡不住"域名正常、DNS 却指向 127.0.0.1 / 169.254.169.254"
    这类 SSRF。解析失败就返回空列表（交给调用方决定）。
    """
    host = (host or "").split(":")[0].strip("[]").lower()
    if not host:
        return []
    if host in _DNS_CACHE:
        return _DNS_CACHE[host]

    fake = _fake_dns_map()
    if host in fake:
        val = fake[host]
        # 测试钩子用 FAIL 模拟"解析失败"（生产不会走到）
        ips = None if val.upper() in ("FAIL", "") else [val]
    else:
        ips = []
        try:
            for info in socket.getaddrinfo(host, None):
                ip = info[4][0]
                if ip not in ips:
                    ips.append(ip)
        except Exception:
            ips = None          # 解析失败 = None（区别于"解析到 0 个地址"）
        if ips == []:
            ips = None
    _DNS_CACHE[host] = ips
    return ips


def _ip_is_private(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True          # 认不出来的一律当不安全
    return (a.is_private or a.is_loopback or a.is_link_local
            or a.is_reserved or a.is_multicast or a.is_unspecified)


def origin_robots(sess, url, log, cache=None):
    """
    取某个 origin 的 robots 规则（每个 origin 只请求一次）。

    返回 (verdict, parser_or_None, note)：
        ("allow", None, "404")         → robots.txt 不存在，视为未设限
        ("rules", parser, "200")       → 按规则逐 URL 判断
        ("fail",  None, "HTTP 500")    → 取不到规则：**不能当允许**，调用方应跳过
    """
    cache = _ORIGIN_ROBOTS if cache is None else cache
    origin = _origin_of(url)
    if origin in cache:
        return cache[origin]

    robots_url = origin + "/robots.txt"
    verdict = ("fail", None, "未请求")
    for attempt in (1, 2):
        try:
            r = sess.get(robots_url, timeout=min(int(CONFIG.get("timeout") or 20), 15))
        except Exception as e:
            verdict = ("fail", None, "请求失败 %s" % type(e).__name__)
            if attempt == 1:
                time.sleep(1.0)
                continue
            break

        if r.status_code == 404:
            verdict = ("allow", None, "404 视为未设限")
            break
        if r.status_code == 200:
            text = r.text or ""
            kind = robots_rules.classify_robots(200, r.headers.get("content-type"), text)
            if kind == "unparsable":
                verdict = ("fail", None, "200 但内容不是 robots（%s）"
                           % (r.headers.get("content-type") or "未知类型"))
                break
            verdict = ("rules", text, "200（%d 字节）" % len(text))
            break
        # 401/403/5xx：站点不让我们读规则 → 保守当作不允许
        verdict = ("fail", None, "robots.txt HTTP %d" % r.status_code)
        if attempt == 1 and r.status_code >= 500:
            time.sleep(1.0)
            continue
        break

    cache[origin] = verdict
    log("  附件 robots：%s → %s（%s）" % (origin, verdict[0], verdict[2]))
    return verdict


def attachment_allowed_by_robots(sess, url, log, cache=None):
    """(是否允许, 状态字符串, 说明)

    与 url_allowed 用同一套判定（RFC 9309），只是规则按 origin 分别缓存。
    """
    kind, text, note = origin_robots(sess, url, log, cache)
    if kind == "allow":
        return True, "", note
    if kind == "fail":
        return False, "robots_check_failed", note     # 取不到规则 ≠ 允许
    allowed, rule, line_no = robots_rules.decide(text or "", CONFIG["ua"], url)
    if allowed:
        return True, "", note
    if _ROBOTS.get("ignore"):
        record_robots_decision(url, "attachment", rule, line_no, "overridden")
        log("  [覆盖] --ignore-robots 生效，放行附件：%s" % url)
        return True, "", note
    record_robots_decision(url, "attachment", rule, line_no, "skipped")
    return False, "robots_denied", "%s（第 %d 行）" % (rule, line_no)


# content_hash 的规范化规则：
#   * 不参与哈希：时间戳、血缘字段、状态码、路径（这些一变，"内容"其实没变）
#   * 参与哈希：业务字段 + 附件的稳定投影（url/status/bytes/sha256，不含本地路径和文件名）
# 为什么不含文件名：文件名是"我们怎么存"，不是"对方给了什么"；改名不该改哈希。
HASH_VOLATILE = {
    "source_url", "fetched_at", "http_status", "content_hash", "run_id",
    "detail_fetched_at", "detail_http_status", "detail_attempts",
    "detail_fetch", "detail_error", "detail_missing",
}


def _canon_value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return v.strip()
    return str(v)


# 站点级指纹排除（v14.5）：CONFIG["hash_exclude"]，与 HASH_VOLATILE 合并生效。
# 用途：某个站的字段本身会随抓取时刻变化（如 wzrc 的 published="30分钟前"），
# 它不属于"内容变化"，不该让 content_hash 漂移。**只影响该站，不动全局集合。**
HASH_EXCLUDE = set()
_GUARD_SEEN = set()      # 同一个字段只报一次


def hash_volatile():
    """本次生效的"不参与指纹"字段集合 = 全局血缘字段 ∪ 站点声明排除。"""
    return HASH_VOLATILE | HASH_EXCLUDE


def reanchor_and_guard(rec, anomalies, seen_flag):
    """v14.6（P1a）两件事：

    ① **重锚**：站点的 parse 用 now() 算 published_at，但正确锚点是抓取时刻
       fetched_at。这里用 fetched_at 重算一次并覆盖（幂等：同锚点结果一致）。
    ② **守卫**：若某字段值"看起来是相对时间"，却没在 hash_exclude 里声明，
       写一条 anomaly —— 防"新接的站忘了声明，content_hash 静默漂移"。
    """
    import timeline
    anchor = rec.get("fetched_at") or ""
    try:
        from datetime import datetime
        anch = datetime.fromisoformat(anchor) if anchor else None
    except Exception:
        anch = None
    if anch is not None and "published" in rec:
        at, prec, qual = timeline.parse_relative_time(rec.get("published"), anch)
        rec["published_at"] = at
        rec["published_precision"] = prec
        rec["published_quality"] = qual
    # 守卫
    try:
        for k, v in list(rec.items()):
            if k in ("published",) or k.endswith("_raw"):
                if timeline.looks_relative(v) and k not in hash_volatile():
                    if k not in seen_flag:
                        seen_flag.add(k)
                        anomalies.append({
                            "page": "guard", "anomaly": "relative_time_not_excluded",
                            "field": k, "sample": str(v)[:24],
                            "hint": "该字段是相对时间但站点没声明 hash_exclude，content_hash 会漂",
                        })
    except Exception:
        pass
    return rec


def canonical_for_hash(row):
    """把一条记录规整成"只反映内容"的结构，保证同一内容每次哈希一致。"""
    vol = hash_volatile()
    out = {}
    for k in sorted(row):
        if k in vol:
            continue
        v = row[k]
        if k == "attachments":
            proj = []
            for a in (v or []):
                if isinstance(a, dict):
                    proj.append([str(a.get("url") or ""),
                                 str(a.get("status") or ""),
                                 int(a.get("bytes") or 0),
                                 str(a.get("sha256") or "")])
                else:
                    proj.append([str(a)])
            out[k] = sorted(proj)
            continue
        if isinstance(v, list):
            out[k] = [_canon_value(x) for x in v]
        elif isinstance(v, dict):
            out[k] = {kk: _canon_value(vv) for kk, vv in sorted(v.items())}
        else:
            out[k] = _canon_value(v)
    return out


def content_hash_of(row):
    payload = json.dumps(canonical_for_hash(row), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def rebuild_field_signature(out_file):
    """从已有数据文件恢复"字段并集"（不含血缘字段）——二跑时签名也不会空。"""
    keys = set()
    if not os.path.exists(out_file):
        return []
    with open(out_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            keys.update(r.keys())
    keys -= {"source_url", "fetched_at", "http_status", "content_hash", "run_id"}
    return sorted(keys)


DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".zip", ".rar", ".7z", ".txt", ".csv"}


def _safe_filename(name, url, idx):
    url_base = urlsplit(url).path.rsplit("/", 1)[-1] or ""
    base = (name or "").strip() or url_base or "file"

    def _real_ext(n):
        e = os.path.splitext(n)[1].lower()
        # 只有"点 + 字母数字、长度<=6"才算扩展名；"1. 依法设置…申请书" 不算
        return e if (e and len(e) <= 6 and re.fullmatch(r"\.[a-z0-9]+", e)) else ""

    url_ext = _real_ext(url_base)
    base_ext = _real_ext(base)

    # 扩展名优先级：URL 的文档扩展名 > 名字里的文档扩展名 > URL 的其它扩展名
    # 例：名字 .doc + URL .docx → 用 .docx（URL 是服务器亲口说的类型）
    #     名字 .pdf + URL .php  → 保留 .pdf（.php 不是文档扩展名，是脚本页）
    if url_ext in DOC_EXTS:
        target_ext = url_ext
    elif base_ext in DOC_EXTS:
        target_ext = base_ext
    else:
        target_ext = url_ext or base_ext

    stem = base[:len(base) - len(base_ext)] if base_ext else base
    # 名字没有信息量（"附件："这种）→ 直接用 URL 的文件名
    if not re.sub(r"[附件:：\s_\-]", "", stem):
        stem = url_base[:len(url_base) - len(url_ext)] if url_ext else url_base
    base = (stem + target_ext) if target_ext else stem
    base = base.replace("\\", "_").replace("/", "_")
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base).strip(". ")
    if not base:
        base = "file%d" % idx
    if len(base) > 120:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:110] + "." + ext) if dot and len(ext) <= 10 else base[:120]
    return base


def repair_pending_attachments(out_file, sess, log, anomalies, stat):
    """
    附件补抓：扫数据文件里"可重试"的附件，单独重下一次。

    为什么需要它：页面级的 parts_done 一旦标记完成，重跑也不会再碰这一页；
    详情有 repair_pending_details() 兜着，附件以前没有——失败就只能人工处理。
    只重试 ATTACH_RETRY_STATES（下载失败 / robots 暂不可用）；
    类型不对、太大、超条数、robots 明确禁止这类永久性结果一律不碰。
    """
    ac = attach_cfg()
    if not ac.get("enabled") or not os.path.exists(out_file):
        return 0

    # 坏行不能静默跳过：跳过就意味着后面重写文件时这些行会**永久消失**。
    # 宁可整轮中止，也不能悄悄丢数据。
    rows = []
    bad = []
    with open(out_file, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                bad.append((lineno, type(e).__name__))
    if bad:
        raise BadDataFile("数据文件有 %d 行不是合法 JSON（首处第 %d 行 %s）→ 中止，文件不动"
                          % (len(bad), bad[0][0], bad[0][1]))

    pending = []
    for i, r in enumerate(rows):
        for j, a in enumerate(r.get("attachments") or []):
            if isinstance(a, dict) and a.get("status") in ATTACH_RETRY_STATES:
                pending.append((i, j))

    stat["attach_repair_planned"] = len(pending)
    if not pending:
        log("附件补抓：0 个待补（现有附件都是终态）")
        return 0

    log("附件补抓：%d 个待补（%s）"
        % (len(pending), ", ".join(sorted(ATTACH_RETRY_STATES))))

    ok = fail = 0
    for (i, j) in pending:
        one = dict(rows[i])
        one["attachments"] = [dict(rows[i]["attachments"][j])]
        try:
            download_attachments([one], sess, log, CONFIG, anomalies, stat,
                                 CONFIG.get("job"))
        except (RequestBudgetExceeded, TimeBudgetExceeded):
            raise                      # 闸门停止：补抓半途收工，状态留在文件里可续跑
        except Exception as e:
            fail += 1
            anomalies.append({"page": "attachment",
                              "url": one["attachments"][0].get("url", ""),
                              "reason": "补抓异常 %s" % type(e).__name__})
            continue
        got = one["attachments"][0]
        rows[i]["attachments"][j] = got
        if got.get("status") == "ok":
            ok += 1
        else:
            fail += 1

    for r in rows:
        r["content_hash"] = content_hash_of(r)

    tmp = str(out_file) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_file)

    stat["attach_repaired_ok"] = ok
    stat["attach_repaired_fail"] = fail
    log("附件补抓：成功 %d / 仍失败 %d" % (ok, fail))
    return ok


def _site_id(row, dedup_key, idx):
    """每条记录一个稳定的目录名（用去重键的哈希，空的就用序号）。"""
    key = str(row.get(dedup_key) or "").strip()
    if not key:
        key = "row-%d" % idx
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _host_allowed(netloc, ac):
    """
    附件目标是否允许：字面 host + DNS 解析后的 IP 都要过。
    重定向的每一跳都会调用这里，所以解析到内网的中转地址也会被拦。

    返回 (是否允许, 状态, 原因)。
    注意：解析失败一律【拒绝】（fail-closed）—— 解析不出来就没法判断它是不是内网，
    放行等于把安全边界当摆设。allow_hosts 命中时跳过 DNS（白名单本身要可信）。
    """
    host = (netloc or "").split(":")[0].lower().strip("[]")
    allow_hosts = [h.lower() for h in (ac.get("allow_hosts") or [])]
    if allow_hosts:
        if host not in allow_hosts:
            return False, "private_host", "host 不在允许名单：%s" % host
        return True, "", ""

    # allow_private_hosts=True 是"明确允许私有地址"（内网部署/测试），
    # 这种情况字面检查和 DNS 检查都跳过；生产保持 False。
    if ac.get("allow_private_hosts"):
        return True, "", ""

    if _host_is_private(netloc):
        return False, "private_host", "内网/回环地址：%s" % netloc

    if ac.get("check_dns", True):
        ips = _resolve_ips(host)
        if ips is None:
            return False, "dns_resolve_failed", "域名解析失败：%s" % host
        for ip in ips:
            if _ip_is_private(ip):
                return False, "private_host", "域名 %s 解析到内网地址 %s" % (host, ip)
    return True, "", ""


def _unique_path(dest_dir, name):
    """同名文件不覆盖：a.pdf → a_1.pdf → a_2.pdf ……"""
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem, dot, ext = name.rpartition(".")
    base, suffix = (stem, "." + ext) if dot else (name, "")
    n = 1
    while True:
        cand = dest_dir / ("%s_%d%s" % (base, n, suffix))
        if not cand.exists():
            return cand
        n += 1


def _attach_throttle(url, ac, log):
    """附件请求间隔：取 max(配置随机间隔, robots 的 Crawl-delay)，按 origin 记上次时间。"""
    origin = _origin_of(url)
    crawl_delay = 0.0
    kind, rtext, _note = _ORIGIN_ROBOTS.get(origin, (None, None, ""))
    if ac.get("follow_crawl_delay") and kind == "rules" and rtext:
        try:
            crawl_delay = float(robots_rules.crawl_delay(rtext, CONFIG["ua"]) or 0)
        except Exception:
            crawl_delay = 0.0
    want = max(random.uniform(float(ac["delay_min"]), float(ac["delay_max"])), crawl_delay)
    last = _ORIGIN_LAST.get(origin)
    if last is not None:
        wait = want - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
    _ORIGIN_LAST[origin] = time.time()


def _fetch_attachment(sess, url, ac, log):
    """
    取附件响应，返回 (resp|None, final_url, fail_status, why)。

    关键点：重定向手动跟随，**每一跳在发请求之前**就校验 scheme / host / robots。
    自动跟随的话，请求早就打到内网或被禁地址上了，事后再检查没有意义。
    """
    cur = url
    hops = int(ac.get("max_redirects") or 5)
    retries = int(ac.get("retries") or 0)

    retries_used = 0
    for hop in range(hops + 1):
        p = urlsplit(cur)
        if (p.scheme or "").lower() not in ("http", "https"):
            return None, cur, "bad_scheme", "地址不是 http(s)：%s" % cur, retries_used
        host_ok, host_status, host_why = _host_allowed(p.netloc, ac)
        if not host_ok:
            return None, cur, host_status, host_why, retries_used
        if ac.get("respect_robots"):
            allowed, status, note = attachment_allowed_by_robots(sess, cur, log)
            if not allowed:
                prefix = "重定向后 " if hop else ""
                return None, cur, (status or "robots_denied"), prefix + (note or ""), retries_used

        attempt = 0
        while True:
            _attach_throttle(cur, ac, log)
            try:
                r = sess.get(cur, stream=True, allow_redirects=False,
                             timeout=int(ac["timeout"]))
            except (RequestBudgetExceeded, TimeBudgetExceeded):
                raise                  # 闸门停止：整轮收工，不记成单条附件失败
            except Exception as e:
                if attempt < retries:
                    attempt += 1
                    retries_used += 1
                    time.sleep(1.0 * attempt)
                    continue
                return None, cur, "download_failed", "%s: %s" % (type(e).__name__, str(e)[:60]), retries_used

            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                nxt = urljoin(cur, r.headers["Location"])
                try:
                    r.close()
                except Exception:
                    pass
                cur = nxt
                break

            if r.status_code >= 500 and attempt < retries:
                attempt += 1
                retries_used += 1
                try:
                    r.close()
                except Exception:
                    pass
                time.sleep(1.0 * attempt)
                continue

            return r, cur, "", "", retries_used

    return None, cur, "download_failed", "重定向超过 %d 次" % hops, retries_used


def download_attachments(rows, sess, log, cfg, anomalies, stat, job):
    """
    下载每条记录的 attachments，结果写回该字段。

    几条硬规矩：
      * 目录按【记录】分：<dir>/<job>/<记录ID>/，不同记录的同名文件不会互相覆盖
      * 同名冲突 resolved 成 a_1.pdf、a_2.pdf，绝不覆盖已有文件
      * 累计配额是【整个任务】的（跨页累计），不是每页重置
      * 重定向逐跳校验，内网/被禁地址在发请求之前就拦下
    """
    ac = attach_cfg()
    if not ac.get("enabled"):
        return {}

    base_dir = Path(ac["dir"]) / str(job)
    counters = {k: 0 for k in (
        "attach_seen", "attach_ok", "attach_too_many", "attach_too_large",
        "attach_quota", "attach_robots_denied", "attach_robots_check_failed",
        "attach_type_rejected", "attach_private_host", "attach_bad_scheme",
        "attach_denied_ext", "attach_download_failed", "attach_retried",
        "attach_dns_failed",
    )}
    counters["attach_bytes"] = 0

    # stat 里先把所有计数键置 0：报告要能读到 0，而不是缺字段
    for _k in counters:
        stat.setdefault(_k, 0)

    def bump(key, n=1):
        """计数同时写 counters 和 stat：中途抛异常也不会丢已经发生的结果。"""
        counters[key] = counters.get(key, 0) + n
        stat[key] = stat.get(key, 0) + n

    total_budget = int(ac["max_total_bytes"])
    max_files = int(ac["max_files_per_record"])
    max_file = int(ac["max_file_bytes"])
    # 跨页累计：从 stat 里接着算，不能每页从 0 开始
    used = int(stat.get("attach_bytes", 0) or 0)

    status_to_counter = {
        "robots_denied": "attach_robots_denied",
        "robots_check_failed": "attach_robots_check_failed",
        "type_rejected": "attach_type_rejected",
        "private_host": "attach_private_host",
        "bad_scheme": "attach_bad_scheme",
        "denied_ext": "attach_denied_ext",
        "content_mismatch": "attach_type_rejected",
        "dns_resolve_failed": "attach_dns_failed",
        "http_404": "attach_download_failed",
        "http_410": "attach_download_failed",
        "download_failed": "attach_download_failed",
    }

    # 计数用 finally 落盘：中途抛异常时，已经发生的附件结果也要记进 stat，
    # 否则累计配额会少算（下次可能突破上限），报告里数字也会偏低。
    for ridx, row in enumerate(rows, 1):
        raw = row.get("attachments")
        if not raw:
            continue
        items = []
        for x in raw:
            if isinstance(x, str):
                items.append({"url": x})
            elif isinstance(x, dict) and x.get("url"):
                items.append(dict(x))
        if not items:
            row["attachments"] = []
            continue

        site_id = _site_id(row, CONFIG["dedup_key"], ridx)
        # 把整条记录的附件**先**换成 dict 列表（status 留空），后面原地更新。
        # 这样闸门在中途停止时：已完成的带着 ok/失败状态，没轮到的仍是空 status，
        # 上层能把它们统一标成 skipped_budget —— 总数不会少、状态也不会丢。
        row["attachments"] = items
        out = items
        for i, it in enumerate(items, 1):
            bump("attach_seen", 1)
            u = str(it.get("url") or "").strip()
            rec = items[i - 1]          # 原地更新，别新建 dict（否则中途停止会丢状态）
            rec.update({"url": u, "name": "", "status": "", "http_status": 0,
                        "bytes": 0, "sha256": "", "path": ""})

            def fail(status, why=""):
                rec["status"] = status
                if why:
                    rec["error"] = why
                k = status_to_counter.get(status)
                if k:
                    bump(k, 1)
                anomalies.append({"page": "attachment", "url": u,
                                  "reason": "%s %s" % (status, why)})

            if i > max_files:
                rec["status"] = "too_many"
                bump("attach_too_many", 1)
                anomalies.append({"page": "attachment", "url": u,
                                  "reason": "超过单条记录附件数上限 %d，只记链接" % max_files})
                # （rec 已在 out 里，原地更新）
                continue

            rec["name"] = _safe_filename(it.get("name"), u, i)

            if used >= total_budget:
                rec["status"] = "quota_exceeded"
                bump("attach_quota", 1)
                anomalies.append({"page": "attachment", "url": u,
                                  "reason": "已达任务累计上限 %d 字节，只记链接" % total_budget})
                # （rec 已在 out 里，原地更新）
                continue

            p = urlsplit(u)
            ext = os.path.splitext(p.path)[1].lower()
            if ext in set(x.lower() for x in ac.get("ext_deny") or []):
                fail("denied_ext", "可执行/脚本类扩展名：%s" % ext)
                # （rec 已在 out 里，原地更新）
                continue

            # 扩展名白名单（配置了才生效）：只收表格/文档/压缩包里那几类
            ext_allow = [x.lower() for x in (ac.get("ext_allow") or [])]
            if ext_allow and ext not in ext_allow:
                fail("denied_ext", "扩展名 %s 不在白名单 %s" % (ext, ",".join(ext_allow)))
                # （rec 已在 out 里，原地更新）
                continue

            host_ok, host_status, host_why = _host_allowed(p.netloc, ac)
            if not host_ok:
                fail(host_status, host_why)
                # （rec 已在 out 里，原地更新）
                continue

            resp, final_url, status, why, retries_used = _fetch_attachment(sess, u, ac, log)
            if retries_used:
                bump("attach_retried", retries_used)
            if resp is None:
                fail(status, why)
                # （rec 已在 out 里，原地更新）
                continue

            rec["http_status"] = resp.status_code
            if resp.status_code != 200:
                code = resp.status_code
                try:
                    resp.close()
                except Exception:
                    pass
                if code in (404, 410):
                    # 404/410 是"这东西没了"，重试多少次都一样，明确标永久失败
                    fail("http_%d" % code, "HTTP %d（永久失败，不重试）" % code)
                else:
                    fail("download_failed", "HTTP %d" % code)
                # （rec 已在 out 里，原地更新）
                continue

            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            allow_types = [t.lower() for t in (ac.get("content_type_allow") or [])]
            if allow_types and ctype and not any(ctype.startswith(t) for t in allow_types):
                try:
                    resp.close()
                except Exception:
                    pass
                fail("type_rejected", "Content-Type %s 不在白名单" % ctype)
                # （rec 已在 out 里，原地更新）
                continue

            clen = resp.headers.get("Content-Length")
            if clen and clen.isdigit() and int(clen) > max_file:
                try:
                    resp.close()
                except Exception:
                    pass
                rec["status"] = "too_large"
                rec["bytes"] = int(clen)
                bump("attach_too_large", 1)
                anomalies.append({"page": "attachment", "url": u,
                                  "reason": "文件 %d 字节 > 单文件上限 %d，只记链接"
                                            % (int(clen), max_file)})
                # （rec 已在 out 里，原地更新）
                continue

            dest_dir = base_dir / site_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_path(dest_dir, rec["name"])

            h = hashlib.sha256()
            written = 0
            too_big = False
            magic_bad = False
            chunks = resp.iter_content(64 * 1024)
            try:
                first_chunk = b""
                if ac.get("sniff_magic") and ext in MAGIC_BY_EXT:
                    # iter_content 每次给多少并不保证；文件头可能被切成 2~3 块传过来，
                    # 所以先攒够"最长 magic 长度"再判，不能拿第一块直接比。
                    want = max(len(m) for m in MAGIC_BY_EXT[ext])
                    buf = b""
                    while len(buf) < want:
                        piece = next(chunks, b"")
                        if not piece:
                            break
                        buf += piece
                    first_chunk = buf
                    if not any(first_chunk.startswith(m) for m in MAGIC_BY_EXT[ext]):
                        magic_bad = True
                if magic_bad:
                    try:
                        resp.close()
                    except Exception:
                        pass
                    fail("content_mismatch",
                         "文件头与扩展名 %s 不符（前 8 字节：%r）" % (ext, first_chunk[:8]))
                    # （rec 已在 out 里，原地更新）
                    continue
                else:
                    import itertools as _it
                    stream = _it.chain([first_chunk], chunks) if first_chunk else chunks
                with open(dest, "wb") as f:
                    for chunk in stream:
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > max_file:
                            too_big = True
                            break
                        if used + written > total_budget:
                            too_big = "quota"
                            break
                        h.update(chunk)
                        f.write(chunk)
            except (RequestBudgetExceeded, TimeBudgetExceeded):
                # 闸门停止：这一条不标失败，交给 main 统一收尾（数据保留、可续跑）
                try:
                    resp.close()
                except Exception:
                    pass
                try:
                    dest.unlink()
                except Exception:
                    pass
                raise
            except Exception as e:
                try:
                    resp.close()
                except Exception:
                    pass
                try:
                    dest.unlink()
                except Exception:
                    pass
                fail("download_failed", "%s: %s" % (type(e).__name__, str(e)[:60]))
                # （rec 已在 out 里，原地更新）
                continue
            finally:
                try:
                    resp.close()
                except Exception:
                    pass

            if too_big:
                try:
                    dest.unlink()
                except Exception:
                    pass
                if too_big == "quota":
                    rec["status"] = "quota_exceeded"
                    bump("attach_quota", 1)
                    anomalies.append({"page": "attachment", "url": u,
                                      "reason": "下载中触达任务累计上限 %d 字节" % total_budget})
                else:
                    rec["status"] = "too_large"
                    rec["bytes"] = written
                    bump("attach_too_large", 1)
                    anomalies.append({"page": "attachment", "url": u,
                                      "reason": "实际 %d 字节 > 单文件上限 %d" % (written, max_file)})
                # （rec 已在 out 里，原地更新）
                continue

            used += written
            rec["status"] = "ok"
            rec["bytes"] = written
            rec["sha256"] = h.hexdigest()
            rec["path"] = str(dest)
            rec["content_type"] = ctype
            rec["final_url"] = final_url
            bump("attach_ok", 1)
            bump("attach_bytes", written)
            log("  附件 ok %s（%d 字节）" % (dest.name, written))
            # （rec 已在 out 里，原地更新，不需要 append）

        row["attachments"] = out

    if counters["attach_robots_denied"] or counters["attach_robots_check_failed"]:
        log("!! 有 %d 个附件被 robots 禁止、%d 个附件 robots 取不到规则 → 都只记了链接没下载。"
            % (counters["attach_robots_denied"], counters["attach_robots_check_failed"]))
        log("!! 要不要继续抓这些附件由你决定（现在的行为是跳过）")

    return counters


def merge_detail_into(row, d, required):
    """
    把 parse_detail 的结果合并进一条记录。详情阶段和"补抓"共用这一套规则，
    避免两处各写一遍导致字段行为不一致。

    返回 (是否成功, 缺失字段列表)。
    """
    for k, v in d.items():
        if k == "title":
            row["detail_title"] = v
        else:
            row[k] = v
    row["detail_fetched_at"] = now_iso()

    missing = [k for k in required if str(row.get(k) or "").strip() == ""]
    if missing:
        row["detail_fetch"] = "field_missing"
        row["detail_missing"] = ",".join(missing)
        return False, missing
    row["detail_fetch"] = "ok"
    row.pop("detail_missing", None)
    row.pop("detail_error", None)
    return True, []


# =====================================================================
# 阶段3：JSON / API 响应
#
# 站点 CONFIG["response"] = "html"(默认) | "json"。
# 选 json 时，列表数据的解析不再由站点写 parse_list，而是走下面这套配置：
#   CONFIG["json"] = {
#       "method": "GET" | "POST",
#       "params": {...},          # 查询参数；"{page}" 会被替换成页码
#       "form_body": {...},       # POST 表单（和 json_body 二选一）
#       "json_body": {...},       # POST JSON body
#       "headers": {...},
#       "list_path": "data.items",  # 列表在响应里的位置（点路径；空=响应本身就是数组）
#       "field_map": {"title": "name"},   # 记录字段名 -> JSON 里的键名（空=键名原样）
#       "ok_path": "code", "ok_value": 0, # 业务成功判定（HTTP 200 也可能业务失败）
#       "total_path": "data.total",       # 可选，只记录进报告
#       "next_path": "data.next",         # 下一页 URL（放在响应里）
#       "cursor_path": "data.next_cursor",# 游标：拼成下一页 URL 的查询参数
#       "cursor_req_key": "cursor",
#   }
# 为什么要 field_map：接口字段名（name/link/created_at）和我方字段名
# （title/detail_url/publish_date）通常不一样，映射写在配置里，代码不用改。
# =====================================================================
JSON_DEFAULTS = {
    "method": "GET",
    "params": {},
    "form_body": None,
    "json_body": None,
    "headers": {},
    "list_path": "",
    "field_map": {},
    "ok_path": "",
    "ok_value": None,
    "total_path": "",
    # total 的口径：
    #   "global" —— 接口给的是"整个结果集总数"（默认），只有确认本轮抓完了才拿它比对
    #   "page"   —— 接口给的是"当前页条数"，只记录、不参与全局比较
    "total_scope": "global",
    "next_path": "",
    "cursor_path": "",
    "cursor_req_key": "cursor",
    # 游标"结束"的判定值。留空 = 假值（None/""/0）即结束；
    # 有些 API 允许 0 当合法游标，那就必须显式声明 cursor_end_value（例如 -1）。
    "cursor_end_value": None,
    # 站点只有一个页、没有下一页也没有游标时，必须显式声明，否则引擎会报配置错误。
    "single_page": False,
}


def _subst(obj, page):
    """
    递归把结构里的 "{page}" 替换成页码。
    params / form_body / json_body 都要用 —— POST 的分页参数通常藏在 body 里，
    只替换 params 的话第二页会原封不动地再要一次第一页。
    """
    if isinstance(obj, dict):
        return {k: _subst(v, page) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst(v, page) for v in obj]
    if isinstance(obj, str):
        if obj == "{page}":
            return page
        if "{page}" in obj:
            return obj.replace("{page}", str(page))
    return obj


def json_cfg():
    c = dict(JSON_DEFAULTS)
    c.update(CONFIG.get("json") or {})
    return c


def response_mode():
    """
    返回 CONFIG["response"] 的规范化值，不做"非法就退回 html"的兜底 ——
    静默退回会让 json 站点被当成 html 去解析，报出来的错完全指错方向。
    合法性由 main() 开头统一校验。
    """
    return (CONFIG.get("response") or "html").strip().lower()


def _json_get(obj, path):
    """
    点路径取值：data.items / data.list.0.name。
    取不到一律返回 None（不抛异常）——字段缺失是常态，不能让它把整轮抓取炸掉。
    """
    if not path:
        return obj
    cur = obj
    for part in str(path).split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def fetch_page(sess, url, log, page=None, referer=None):
    """
    抓"一页数据"，按 response 模式返回 (code, payload)：
        html → payload 是页面文本
        json → payload 是解析后的 dict/list（解析失败时是 None，并已记日志）

    与之前 fetch() 的区别：多了 POST/参数/头支持，且会做 JSON 解析。
    """
    if response_mode() != "json":
        return fetch(sess, url, log, referer=referer)

    jc = json_cfg()
    method = (jc.get("method") or "GET").upper()
    # params / body 里的 {page} 都要替换（递归），否则 POST 分页会一直要第一页
    params = _subst(jc.get("params") or {}, page)

    body_kw = {}
    if method == "POST":
        if jc.get("json_body") is not None:
            body_kw["json"] = _subst(jc["json_body"], page)
        elif jc.get("form_body") is not None:
            body_kw["data"] = _subst(jc["form_body"], page)

    headers = dict(jc.get("headers") or {})
    if referer:
        headers.setdefault("Referer", referer)

    retries = CONFIG["retries"]
    timeout = CONFIG["timeout"]
    backoff = CONFIG["backoff"]

    for attempt in range(1, retries + 1):
        try:
            r = sess.request(method, url, params=params or None, headers=headers or None,
                             timeout=timeout, **body_kw)
            code = r.status_code
            _note_resp(r, referer)

            if code == 200:
                try:
                    return code, r.json()
                except ValueError:
                    # 200 但不是 JSON：很常见（被登录页/风控页顶替了）
                    log("  HTTP 200 但响应不是 JSON（前 80 字）：%s"
                        % (r.text or "")[:80].replace("\n", " "))
                    return code, None

            if code in (429, 503):
                wait = backoff ** attempt * 3
                log("  HTTP %s 被限速 → 等 %.1f 秒（第 %d/%d 次）"
                    % (code, wait, attempt, retries))
                time.sleep(wait)
                continue

            if code in (401, 403, 451) or 400 <= code < 500:
                log("  HTTP %s → 不重试" % code)
                return code, None

            wait = backoff ** attempt
            log("  HTTP %s → 等 %.1f 秒重试（第 %d/%d 次）" % (code, wait, attempt, retries))
            time.sleep(wait)
        except requests.RequestException as e:
            wait = backoff ** attempt
            log("  网络异常 %s → 等 %.1f 秒重试（第 %d/%d 次）"
                % (type(e).__name__, wait, attempt, retries))
            time.sleep(wait)

    return None, None


class ApiError(Exception):
    """业务层错误：HTTP 200 但接口自己报错（code≠0 之类）。"""


def rows_from_json(payload, url):
    """
    从 JSON 响应里取出列表并映射成记录。抛 ApiError 表示业务失败。
    字段缺失不抛异常：该字段留空，由调用方决定怎么记。
    """
    jc = json_cfg()

    if jc.get("ok_path"):
        v = _json_get(payload, jc["ok_path"])
        if v != jc.get("ok_value"):
            raise ApiError("业务错误码 %s=%r（期望 %r）"
                           % (jc["ok_path"], v, jc.get("ok_value")))

    items = _json_get(payload, jc.get("list_path") or "")
    if items is None:
        raise ApiError("响应里找不到列表：list_path=%r" % (jc.get("list_path") or "(根)"))
    if not isinstance(items, list):
        raise ApiError("list_path 指向的不是数组，而是 %s" % type(items).__name__)

    fmap = jc.get("field_map") or {}
    rows = []
    invalid = 0          # 不是 dict 的条目：不能静默丢掉，交给调用方记异常
    for it in items:
        if not isinstance(it, dict):
            invalid += 1
            continue
        if fmap:
            row = {}
            for ours, theirs in fmap.items():
                v = _json_get(it, theirs)
                # 约定：字段名以 _url 结尾的相对地址，自动补成绝对地址
                if isinstance(v, str) and ours.endswith("_url") and v and not v.startswith(("http://", "https://")):
                    v = urljoin(url, v)
                # 取不到就留空字符串：留 None 会让去重键变成字符串 "None"，
                # 多条缺失记录会被误判成同一条（静默丢数据）。
                row[ours] = "" if v is None else v
        else:
            row = dict(it)
        rows.append(row)
    return rows, invalid


def json_total(payload):
    """
    响应里的"总数"。取不到就返回 None（很多接口压根不给）。
    只用于记录与交叉校验：接口说 total=9 但我只抓到 6 条，是重要线索。
    """
    jc = json_cfg()
    if not jc.get("total_path"):
        return None
    v = _json_get(payload, jc["total_path"])
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def next_from_json(payload, url):
    """
    JSON 响应里的"下一页"：
        next_path   → 直接是下一页地址（相对路径会自动补全）
        cursor_path → 用游标拼出下一页地址（游标放在查询参数里）
    返回 None 表示没有下一页。
    """
    jc = json_cfg()

    if jc.get("single_page"):
        # 站点显式声明"只有一页"：抓完这一页就收工，这是正常结束
        return None

    if jc.get("next_path"):
        v = _json_get(payload, jc["next_path"])
        if not v:
            return None
        return urljoin(url, str(v))

    if jc.get("cursor_path"):
        cur = _json_get(payload, jc["cursor_path"])
        endv = jc.get("cursor_end_value")
        if endv is not None:
            # 显式声明了"结束值"：只有它才算结束，0 可以是合法游标
            if cur is None or str(cur) == str(endv):
                return None
        elif cur in (None, "", 0):
            return None
        key = jc.get("cursor_req_key") or "cursor"
        sep = "&" if "?" in url else "?"
        # 保险：把上一次的 cursor 参数去掉再拼新的，避免越拼越长
        base = re.sub(r"([?&])%s=[^&]*" % re.escape(key), r"\1", url).rstrip("?&")
        sep = "&" if "?" in base else "?"
        return "%s%s%s=%s" % (base, sep, key, urlencode({key: cur})[len(key) + 1:])

    return None


def resolve_detail_mode(requested, site_mod):
    """
    决定这一轮走哪条详情路径。

    generic = 引擎通用流程 + 站点的 parse_detail
    off     = 不进详情页

    阶段1 之前还有一条 legacy（站点自己写 detail_hook），已删除：
    真站 40 条 × 13 字段对比零差异之后才删的，旧实现留在 _baseline_v1/code 里。
    """
    has_generic = site_mod is not None and hasattr(site_mod, "parse_detail")
    enabled = bool((CONFIG.get("detail") or {}).get("enabled"))

    if requested == "off":
        return "off"
    if requested == "generic":
        return "generic" if has_generic else "off"
    return "generic" if (enabled and has_generic) else "off"


def crawl_details_generic(rows, sess, log, cfg, anomalies, parse_detail):
    """
    引擎统一负责的详情阶段。站点只提供 parse_detail(html) -> dict。

    引擎负责的事（旧实现里每个站要自己写一遍，容易漏）：
        robots 检查、随机限速、超时、重试、指数退避、
        detail_http_status、detail_fetched_at、detail_fetch 状态、
        失败进 anomalies、失败率熔断、必填字段校验。

    返回 (abort_reason, counters)：
        abort_reason 非 None 表示遇到 abort_on 里的状态码，调用方应整体停止；
        counters 是可直接并入 stat 的计数（含 detail_stop_reason）。

    约定：站点返回的 dict 里如果键是 "title"，会写成 detail_title（不覆盖列表标题），
    其余键原样合并进记录。
    """
    c = detail_cfg()
    total = len(rows)
    counters = {
        "detail_planned": total,
        "detail_attempted": 0,
        "detail_ok": 0,
        "detail_failed": 0,
        "detail_skipped": 0,
        "detail_skipped_limit": 0,
        "detail_robots_blocked": 0,
        "detail_retried": 0,
        "detail_stop_reason": "",
    }

    if total == 0:
        return None, counters

    limit = total
    if int(c.get("max_items_per_page") or 0) > 0:
        limit = min(total, int(c["max_items_per_page"]))
    counters["detail_attempted"] = limit

    abort_on = set(c.get("abort_on") or [])
    required = list(c.get("required") or [])
    ratio = float(c.get("max_fail_ratio") or 0)
    delay_min = float(c["delay_min"])
    delay_max = float(c["delay_max"])
    retries = int(c["retries"])
    timeout = int(c["timeout"])
    backoff = float(c["backoff"])
    check_robots = bool(c.get("respect_robots"))

    abort_reason = None
    stop_reason = ""

    for i, r in enumerate(rows[:limit], 1):
        url = r.get("detail_url") or r.get("url") or ""

        if not url:
            counters["detail_failed"] += 1
            r["detail_fetch"] = "no_detail_url"
            r["detail_http_status"] = 0
            anomalies.append({"page": "detail", "url": "",
                              "reason": "记录里没有 detail_url"})
            log("  [%2d/%d] 没有 detail_url，跳过" % (i, total))
            continue

        # 首次抓取也记一次尝试，字段语义才完整（补抓时会继续累加）
        r["detail_attempts"] = int(r.get("detail_attempts") or 0) + 1

        if check_robots and not url_allowed(url, log, stage="detail"):
            counters["detail_robots_blocked"] += 1
            counters["detail_failed"] += 1
            r["detail_fetch"] = "robots_denied"
            r["detail_http_status"] = 0
            anomalies.append({"page": "detail", "url": url,
                              "reason": "robots 禁止抓详情页"})
            blocked_n = counters["detail_robots_blocked"]
            # 只用绝对条数判断：比例在小样本上会误触发（20 条里 4 条就是 20%）
            if blocked_n >= ROBOTS_DECISION_LIMIT:
                _ROBOTS_STOP["reason"] = "robots_denied_need_decision"
                dec = _ROBOTS_DECISIONS[-1] if _ROBOTS_DECISIONS else {}
                robots_decision_block(
                    log, "详情页", url, dec.get("rule", ""), dec.get("rule_line", 0),
                    "已累计 %d 条详情页被禁，继续跑只会得到空白数据" % blocked_n)
                abort_reason = "robots_denied_need_decision"
                break
            continue

        polite_sleep(delay_min, delay_max)
        code, html = _fetch_core(sess, url, log, retries, timeout, backoff, tag="详情")

        if code is None:
            counters["detail_failed"] += 1
            counters["detail_retried"] += 1
            r["detail_fetch"] = "error"
            r["detail_error"] = "重试耗尽（超时/网络异常）"
            r["detail_http_status"] = 0
            anomalies.append({"page": "detail", "url": url,
                              "reason": "详情重试耗尽（超时/网络异常）"})
            log("  [%2d/%d] 详情重试耗尽 | %s" % (i, total, url[-28:]))

        elif code in abort_on:
            counters["detail_failed"] += 1
            r["detail_fetch"] = "http_%d" % code
            r["detail_http_status"] = code
            anomalies.append({"page": "detail", "url": url,
                              "reason": "详情 HTTP %d（要求停止）" % code})
            log("  [%2d/%d] 详情返回 HTTP %d → 立即停止" % (i, total, code))
            abort_reason = "detail_http_%d" % code
            break

        elif code != 200 or not html:
            counters["detail_failed"] += 1
            r["detail_fetch"] = "http_%d" % code
            r["detail_http_status"] = code
            anomalies.append({"page": "detail", "url": url,
                              "reason": "详情 HTTP %d" % code})
            log("  [%2d/%d] 详情 HTTP %d | %s" % (i, total, code, url[-28:]))

        else:
            r["detail_http_status"] = code
            try:
                d = parse_detail(html)
            except Exception as e:
                counters["detail_failed"] += 1
                r["detail_fetch"] = "parse_error"
                r["detail_error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
                anomalies.append({"page": "detail", "url": url,
                                  "reason": "详情解析异常 %s" % type(e).__name__})
                log("  [%2d/%d] 详情解析失败 %s" % (i, total, type(e).__name__))
                d = None

            if d is not None:
                if not isinstance(d, dict):
                    counters["detail_failed"] += 1
                    r["detail_fetch"] = "parse_error"
                    r["detail_error"] = "parse_detail 返回的不是 dict"
                    anomalies.append({"page": "detail", "url": url,
                                      "reason": "parse_detail 返回类型错误"})
                else:
                    ok, missing = merge_detail_into(r, d, required)
                    if ok:
                        counters["detail_ok"] += 1
                        log("  [%2d/%d] 详情 ok %s" % (i, total, url[-28:]))
                    else:
                        # 旧实现这里只记一条 anomaly 就完了，记录上仍写着
                        # detail_fetch=ok —— 主引擎据此统计，会把残缺数据算成成功。
                        # 现在明确标成 field_missing。
                        counters["detail_failed"] += 1
                        anomalies.append({"page": "detail", "url": url,
                                          "reason": "字段缺失 %s" % ",".join(missing)})
                        log("  [%2d/%d] 字段缺失 %s" % (i, total, ",".join(missing)))

        # ---- 熔断：失败数 / 本轮计划抓取的条数 >= 阈值 ----
        # 分母用 limit 而不是 total：如果 max_items_per_page 限制了只抓 5 条，
        # 那 5 条全挂就是 100%，不该被 20 条的分母稀释成 25%。
        if ratio > 0 and counters["detail_failed"] > 0:
            if counters["detail_failed"] / float(limit) >= ratio:
                stop_reason = "detail_fail_ratio_exceeded"
                log("  !! 详情失败 %d/%d = %.0f%%，已达阈值 %.0f%% → 停止详情阶段"
                    % (counters["detail_failed"], limit,
                       counters["detail_failed"] * 100.0 / limit, ratio * 100))
                break

    # 没处理到的记录显式标出来，避免"看起来没问题其实是没抓"。
    # 两种原因要分开：
    #   skipped_limit   = 被 max_items_per_page 限制，本来就没打算抓
    #   skipped_aborted = 因为熔断/中止，计划里要抓但没轮到
    for i, r in enumerate(rows):
        if i >= limit:
            r["detail_fetch"] = "skipped_limit"
            counters["detail_skipped_limit"] += 1
        elif "detail_fetch" not in r:
            r["detail_fetch"] = "skipped_aborted"
            counters["detail_skipped"] += 1

    counters["detail_stop_reason"] = stop_reason

    log("详情完成：成功 %d / 失败 %d / 熔断未处理 %d / 超出上限未处理 %d / robots禁止 %d / 共 %d%s"
        % (counters["detail_ok"], counters["detail_failed"],
           counters["detail_skipped"], counters["detail_skipped_limit"],
           counters["detail_robots_blocked"], total,
           ("（停止原因：%s）" % stop_reason) if stop_reason else ""))

    return abort_reason, counters


# =====================================================================
# 详情"没抓全"的补抓语义（codex 2026-11-10 指出，这是阶段1 的核心之一）
#
# 问题：pages_done 只表示"列表页抓过了"，不代表"详情抓全了"。
#   一页 20 条里有 3 条详情失败，页面照样被标记完成 → 下次重跑整页跳过
#   → 那 3 条详情永远补不上，而且没人知道。
#
# 现在的做法：**数据文件本身就是详情状态的唯一来源**（看 detail_fetch 字段），
# 不另建断点集合，避免"断点和数据不一致"这种老问题。
#   每次开跑前先扫一遍数据文件，把该重试的那些重新抓一次，原地更新（原子替换）。
#   已经成功的详情不会重抓；列表页也不会重抓。
#
# 哪些不重试：
#   ok            已经好了
#   robots_denied robots 不允许，重试等于硬来
#   no_detail_url 这条记录本来就没有详情页
#   skipped_limit 被 max_items_per_page 主动限制的，不是失败
#   http_404/410  页面没了，重试也不会回来
#   abort_on 里的状态码（401/403/429/451）重试是骚扰站点
# =====================================================================
DETAIL_NEVER_RETRY = {"ok", "robots_denied", "no_detail_url", "skipped_limit"}


def detail_retryable(state, abort_on=None, missing_is_pending=False):
    """
    这个 detail_fetch 状态下次还要不要再试一次？

    missing_is_pending：detail_fetch 字段【完全没有】时怎么算。
        默认 False（没详情功能的站点，不能把"没有这个字段"当成失败）。
        但站点启用了详情时必须是 True —— 否则会出现这种情况：
        某个站原来没开详情 → 老记录里没有 detail_fetch → 后来开了详情，
        这些记录既不会被重抓（列表页已 pages_done），也不会被补抓（状态是 None），
        永远缺详情而且没人知道。
    """
    if state is None or str(state).strip() == "":
        return bool(missing_is_pending)
    s = str(state)
    if s in DETAIL_NEVER_RETRY:
        return False
    if s.startswith("http_"):
        try:
            code = int(s[5:])
        except ValueError:
            return True
        if abort_on and code in abort_on:
            return False
        if code in (404, 410):
            return False
        return True
    return True          # error / parse_error / field_missing / skipped_aborted ...


def load_rows(out_file):
    rows = []
    if not os.path.exists(out_file):
        return rows
    with open(out_file, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    return rows


def rewrite_rows(out_file, rows):
    """原子重写：先写 .tmp 再 os.replace，中途断电不会留下半个文件。"""
    tmp = out_file + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_file)


def repair_pending_details(out_file, sess, log, cfg, anomalies, parse_detail,
                           only_urls=None):
    """
    把上次没抓全的详情补上。返回 counters（直接并入 stat）。

    刻意不做的事：
      * 不重抓列表页（列表数据已经在文件里，重抓只会给站点添压力）
      * 不重抓已经成功的详情
      * 不做失败率熔断（补抓的量本来就小，而且每条都是之前确认要的）
    """
    c = detail_cfg()
    abort_on = set(c.get("abort_on") or [])
    required = list(c.get("required") or [])

    rows = load_rows(out_file)
    if only_urls:
        # 两段式第 2 段：**只认清单**。清单里的 URL 一律处理（哪怕上次已成功，
        # 那是你明确要求重抓的），清单外的一条都不碰。
        want = {u.rstrip("/") for u in only_urls}
        idx = [i for i, r in enumerate(rows)
               if (r.get("detail_url") or "").rstrip("/") in want]
        missing = want - {(r.get("detail_url") or "").rstrip("/") for r in rows}
    else:
        idx = [i for i, r in enumerate(rows)
               if detail_retryable(r.get("detail_fetch"), abort_on,
                                   missing_is_pending=True)]
        missing = set()

    counters = {
        "detail_repair_planned": len(idx),
        "detail_repaired_ok": 0,
        "detail_repaired_fail": 0,
        "detail_repaired_robots": 0,
    }
    if only_urls:
        counters["detail_urls_missing"] = len(missing)
        if missing:
            log("!! 清单里有 %d 个 URL 不在本任务数据里（先跑第 1 段列表）：%s"
                % (len(missing), list(missing)[:3]))

    if not idx:
        log("详情补抓：0 条待补（现有记录的详情都齐了）")
        return counters

    log("详情补抓：%d 条上次没抓全，开始补（不重抓列表页、不重抓已成功的）" % len(idx))
    changed = False
    aborted = None

    for n, i in enumerate(idx, 1):
        r = rows[i]
        url = r.get("detail_url") or ""
        r["detail_attempts"] = int(r.get("detail_attempts") or 0) + 1
        changed = True

        if not url:
            counters["detail_repaired_fail"] += 1
            continue

        if c.get("respect_robots") and not url_allowed(url, log):
            counters["detail_repaired_robots"] += 1
            r["detail_fetch"] = "robots_denied"
            continue

        polite_sleep(float(c["delay_min"]), float(c["delay_max"]))
        code, html = _fetch_core(sess, url, log,
                                 int(c["retries"]), int(c["timeout"]),
                                 float(c["backoff"]), tag="补抓")

        if code is None:
            counters["detail_repaired_fail"] += 1
            r["detail_fetch"] = "error"
            r["detail_error"] = "补抓重试耗尽（超时/网络异常）"
            anomalies.append({"page": "repair", "url": url, "reason": "补抓重试耗尽"})
            log("  [%d/%d] 补抓重试耗尽 | %s" % (n, len(idx), url[-28:]))
            continue

        if code in abort_on:
            counters["detail_repaired_fail"] += 1
            r["detail_fetch"] = "http_%d" % code
            anomalies.append({"page": "repair", "url": url,
                              "reason": "补抓 HTTP %d（要求停止）" % code})
            log("  [%d/%d] 补抓返回 HTTP %d → 停止补抓" % (n, len(idx), code))
            aborted = "detail_repair_http_%d" % code
            break

        if code != 200 or not html:
            counters["detail_repaired_fail"] += 1
            r["detail_fetch"] = "http_%d" % code
            anomalies.append({"page": "repair", "url": url,
                              "reason": "补抓 HTTP %d" % code})
            log("  [%d/%d] 补抓 HTTP %d | %s" % (n, len(idx), code, url[-28:]))
            continue

        r["detail_http_status"] = code
        try:
            d = parse_detail(html)
        except Exception as e:
            counters["detail_repaired_fail"] += 1
            r["detail_fetch"] = "parse_error"
            r["detail_error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
            anomalies.append({"page": "repair", "url": url,
                              "reason": "补抓解析异常 %s" % type(e).__name__})
            continue

        ok, missing = merge_detail_into(r, d, required)
        if ok:
            counters["detail_repaired_ok"] += 1
            log("  [%d/%d] 补抓成功 %s" % (n, len(idx), url[-28:]))
        else:
            counters["detail_repaired_fail"] += 1
            anomalies.append({"page": "repair", "url": url,
                              "reason": "补抓仍缺字段 %s" % ",".join(missing)})
            log("  [%d/%d] 补抓仍缺字段 %s" % (n, len(idx), ",".join(missing)))

    if changed:
        rewrite_rows(out_file, rows)
        log("详情补抓：成功 %d / 仍失败 %d / robots跳过 %d（数据文件已原地更新）"
            % (counters["detail_repaired_ok"], counters["detail_repaired_fail"],
               counters["detail_repaired_robots"]))

    counters["detail_repair_abort"] = aborted
    return counters


def rebuild_seen(out_file, dedup_key):
    """
    从已经落盘的数据文件里把去重键重新读出来。

    为什么不用 state 里的 seen_keys：state 和 data 是两份东西，
    一旦有人 --reset 或者 state 文件损坏，去重就会失效、往数据里灌重复行。
    数据文件才是唯一真相源，所以每次启动都从它重建。
    """
    seen = set()
    if not os.path.exists(out_file):
        return seen
    n = 0
    with open(out_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise BadDataFile(
                    "数据文件第 %d 行不是合法 JSON（%s）——去重索引不完整，"
                    "请先修好这行，或换一个 --job 重跑" % (n + 1, e))
            k = str(rec.get(dedup_key, ""))
            if k:
                seen.add(k)
            n += 1
    return seen


def blank_state(out_file):
    """
    断点文件的初始形状。

    pages_done / urls_done 必须分开：
        pages_done  数字页码模式用（记"第几页抓完了"）
        urls_done   下一页/游标模式用（记"哪些 URL 抓完了"）
    混在一起就会出现"换成分页方式后，旧断点把新页全部跳过"这种静默丢数据。
    """
    return {
        "pages_done": [],      # number 模式
        # A5：页码 -> 抓完那天的日期（'YYYY-MM-DD'）。
        # window 模式跨天作废用它判断；full 模式不看它（续跑语义）。
        "pages_done_at": {},
        "urls_done": [],       # next 模式
        "next_url": None,      # next 模式：下次该从哪个 URL 继续
        "paginate_mode": None, # 上一次用的是哪种分页（换模式会警告）
        "seen_keys": [],
        "out_file": out_file,
        "pages_declared": None,   # 页面声明的总页数（续跑直接复用，不必再解析）
        "filters_fp": "",        # 筛选条件指纹（变更即清 pages_done）
        "page_size": "",         # 每页条数（变更即清 pages_done）
    }


def beyond_declared(page, pages_declared):
    """页码是否超出站点声明的总页数 M（A6：**唯一判定点**）。

    这条判定原来在引擎里散着 4 份，措辞略有差别，改一处容易漏另外三处：
      1. 进循环前剔除断点里的超限页
      2. 循环内发现本轮 M 后剔除超限页
      3. 两处 `pages_done.add(page)` 之前的"超限则不记断点"
    现在统一走这里。改判定只改这一个函数。

    注意语义：M 只决定"记不记断点 / 报不报覆盖率"，**不决定"这一页抓不抓"**。
    抓不抓只看 page_done()（断点里有没有）。
    """
    return bool(pages_declared) and isinstance(page, int) and page > pages_declared


def page_done(page, pages_done):
    """这一页在断点里是否已完成（A6：**唯一判定点**）。

    调用方拿它决定"跳过还是发请求"。注意：这里**不看 M** ——
    所以 noop 续跑时会多发 1 个请求去确认 M（已知代价，见 A6/A5 记录）。
    """
    try:
        return page in pages_done
    except TypeError:
        return False


def normalize_url(url):
    """
    把 URL 归一化成"同一个页面的身份证"，用于判重/防循环。

    归一化的事：
        * 去掉 #fragment
        * scheme / host 转小写
        * query 参数按键排序（?a=1&b=2 与 ?b=2&a=1 视为同一页）
        * 路径里的重复斜杠压成一个
        * 去掉默认端口 :80 / :443
    不归一化的话，站方只要换个参数顺序，visited 就认不出来，会无限翻下去。
    """
    try:
        p = urlsplit(url)
    except Exception:
        return url
    scheme = (p.scheme or "http").lower()
    host = (p.netloc or "").lower()
    if scheme == "http" and host.endswith(":80"):
        host = host[:-3]
    if scheme == "https" and host.endswith(":443"):
        host = host[:-4]
    path = re.sub(r"/{2,}", "/", p.path or "/")
    q = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
    return urlunsplit((scheme, host, path, q, ""))


def load_state(path, out_file):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                st = json.load(f)
            # 数据文件被删了，就重置断点，避免"跳过但没数据"
            if st.get("out_file") != out_file or not os.path.exists(out_file):
                return blank_state(out_file)
            # 老断点文件没有新字段 → 补齐，不能直接 KeyError
            base = blank_state(out_file)
            base.update(st)
            return base
        except Exception:
            pass
    return blank_state(out_file)


def save_state(path, st):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_report(ctx):
    """
    生成单文件采集报告：report-<job>-<stamp>.md + .json

    任何退出路径都要调用它：成功、失败、robots 拒绝、空跑。
    这样报告才能当审计凭据，而不是"只记录成功那几次"。
    """
    job = ctx.get("job") or "unknown"
    run_id = ctx.get("run_id") or ""
    t_start = ctx.get("t_start") or time.time()
    t_end = ctx.get("t_end") or time.time()
    stat = ctx.get("stat") or {}
    anomalies = ctx.get("anomalies") or []
    per_page = ctx.get("per_page") or {}
    field_list = ctx.get("field_list") or []
    status = ctx.get("status", "unknown")
    reason = ctx.get("reason", "")
    mode = ctx.get("mode", "unknown")
    records_before = ctx.get("records_before", 0)
    total_in_file = ctx.get("total_in_file", 0)
    out_file = ctx.get("out_file") or ""
    log_path = ctx.get("log_path") or ""
    state_path = ctx.get("state_path") or ""

    report_dir = CONFIG.get("report_dir") or r"D:\agent-work\out\reports"
    os.makedirs(report_dir, exist_ok=True)

    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S-") + ("%03d" % (datetime.now(TZ).microsecond // 1000))
    base = os.path.join(report_dir, "report-%s-%s" % (job, stamp))
    elapsed = max(0.0, t_end - t_start)
    pages_ok = int(stat.get("pages_ok", 0) or 0)
    avg_page = (elapsed / pages_ok) if pages_ok else 0.0
    counts = list(per_page.values())

    _gate_sum = (gate_mod.current_gate().summary()
                 if gate_mod.current_gate() is not None else {})
    payload = {
        "job": job,
        "run_id": run_id,
        "gate": _gate_sum,
        "status": status,          # success / failed / noop
        "reason": reason,          # ok / robots_denied / empty_page_range / rebuild_index_only ...
        "mode": mode,              # full / incremental
        # 翻页是怎么停的：no_next / pagination_loop / max_pages_reached /
        # pagination_broken_at_page_N / pagination_blocked_by_robots / ""
        "stop_reason": ctx.get("stop_reason") or "",
        "paginate": CONFIG.get("paginate", "number"),
        "started_at": datetime.fromtimestamp(t_start, TZ).isoformat(timespec="seconds"),
        "finished_at": datetime.fromtimestamp(t_end, TZ).isoformat(timespec="seconds"),
        "elapsed_sec": round(elapsed, 1),
        "avg_sec_per_page": round(avg_page, 2),
        "config": {
            "url_template": CONFIG["url_template"],
            "page_start": CONFIG["page_start"],
            "page_end": CONFIG["page_end"],
            "delay_sec": [CONFIG["delay_min"], CONFIG["delay_max"]],
            "timeout_sec": CONFIG["timeout"],
            "retries": CONFIG["retries"],
            "dedup_key": CONFIG["dedup_key"],
            "transport": CONFIG.get("transport", "plain"),
            "hash_exclude": sorted(CONFIG.get("hash_exclude") or []),   # v14.4：报告里能查本任务走的哪条通道
            "respect_robots": CONFIG["respect_robots"],
            "paginate": CONFIG.get("paginate", "number"),
            "max_pages": CONFIG.get("max_pages", 200),
        },
        "stats": dict(stat),
        # 因冷却退出时，报告里要能查到"冷却到几点"（否则只有一个 cooldown_active 词）
        "cooldown": ctx.get("cooldown"),
        # 页数口径（提案1）：声明值来自页面"1/M页"，plan 是配置/CLI 给的计划值
        "pages_declared": ctx.get("pages_declared"),
        "terms_status": ctx.get("terms_status"),
        "robots_override": ctx.get("robots_override", False),
        "override_scope": ctx.get("override_scope", ""),
        "authorized_by": ctx.get("authorized_by", ""),
        "authorized_at": ctx.get("authorized_at", ""),
        "pages_planned": ctx.get("pages_planned"),
        "pages_effective": ctx.get("pages_effective"),
        "coverage": ctx.get("coverage"),
        "truncated": bool(ctx.get("truncated")),
        # 页大小探针（提案3）
        "page_size": CONFIG.get("page_size") or "",
        "page_size_probe": bool(CONFIG.get("page_size_probe")),
        "datafile": {
            "records_before_run": records_before,
            "records_new_this_run": stat.get("records_new", 0),
            "records_dup_this_run": stat.get("records_dup", 0),
            "total_after_run": total_in_file,
        },
        "field_signature": {
            "field_count": len(field_list),
            "fields": list(field_list),
        },
        "per_page": {str(k): v for k, v in sorted(per_page.items())},
        "per_page_summary": {
            "pages_recorded": len(counts),
            "min": min(counts) if counts else 0,
            "max": max(counts) if counts else 0,
            "avg": round(sum(counts) / len(counts), 2) if counts else 0,
        },
        "anomalies": anomalies,
        "robots": {
            "url": _ROBOTS.get("url", ""),
            "status": _ROBOTS.get("status", ""),
            "bytes": _ROBOTS.get("bytes", 0),
            "groups": _ROBOTS.get("groups", 0),
            "crawl_delay_sec": robots_crawl_delay(),
        },
        "robots_decisions": list(_ROBOTS_DECISIONS),
        "overrides": (["ignore_robots"] if _ROBOTS.get("ignore") else []),
        "artifacts": {"data": out_file, "log": log_path, "state": state_path},
    }

    json_path = base + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---- Markdown 版 ----
    L = []
    L.append("# 采集报告：%s" % job)
    L.append("")
    L.append("- 任务 ID：`%s`" % run_id)
    L.append("- **运行状态：%s**（原因：%s）" % (status, reason or "-"))
    L.append("- **运行模式：%s**" % ("增量（运行前已有数据）" if mode == "incremental" else
                                   ("全量（运行前无数据）" if mode == "full" else "未知")))
    L.append("- 开始：%s" % payload["started_at"])
    L.append("- 结束：%s" % payload["finished_at"])
    L.append("- 耗时：%.1f 秒（平均 %.2f 秒/页）" % (elapsed, avg_page))
    L.append("")
    L.append("## 本次运行 vs 数据文件")
    L.append("")
    L.append("| 项 | 数量 |")
    L.append("|---|---|")
    L.append("| 运行前数据文件已有记录 | %d |" % records_before)
    L.append("| **本次新增** | **%d** |" % stat.get("records_new", 0))
    L.append("| 本次因重复丢弃 | %d |" % stat.get("records_dup", 0))
    L.append("| 运行后数据文件总记录 | %d |" % total_in_file)
    L.append("")
    if mode == "incremental" and stat.get("records_dup", 0):
        L.append("> 注意：本次是**增量运行**，不是从空数据一次抓满。")
        L.append("> 本次新增 %d 条、重复丢弃 %d 条；数据文件最终 %d 条唯一记录。"
                 % (stat.get("records_new", 0), stat.get("records_dup", 0), total_in_file))
        L.append("")
    L.append("## 配置")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| URL 模板 | `%s` |" % CONFIG["url_template"])
    L.append("| 页范围 | %d – %d |" % (CONFIG["page_start"], CONFIG["page_end"]))
    L.append("| 请求间隔 | %.1f – %.1f 秒（随机） |" % (CONFIG["delay_min"], CONFIG["delay_max"]))
    L.append("| 超时 / 重试 | %d 秒 / %d 次 |" % (CONFIG["timeout"], CONFIG["retries"]))
    L.append("| 去重键 | `%s` |" % CONFIG["dedup_key"])
    L.append("| 遵从 robots | %s |" % ("是" if CONFIG["respect_robots"] else "否"))
    L.append("")
    L.append("## 结果")
    L.append("")
    L.append("| 指标 | 数量 |")
    L.append("|---|---|")
    L.append("| 页数（总） | %d |" % stat.get("pages_total", 0))
    L.append("| 页数（成功） | %d |" % stat.get("pages_ok", 0))
    L.append("| 页数（跳过·已完成） | %d |" % stat.get("pages_skipped", 0))
    L.append("| 页数（robots 拒绝） | %d |" % stat.get("pages_blocked", 0))
    L.append("| 页数（空页） | %d |" % stat.get("pages_empty", 0))
    L.append("| 页数（失败） | %d |" % stat.get("pages_failed", 0))
    L.append("| **详情失败条数** | **%d** |" % stat.get("detail_failed", 0))
    L.append("| 记录（新增） | %d |" % stat.get("records_new", 0))
    L.append("| 记录（重复丢弃） | %d |" % stat.get("records_dup", 0))
    L.append("")
    L.append("## 字段签名（下次跑完可以拿这一段对比，看结构变没变）")
    L.append("")
    if field_list:
        L.append("- 字段数：**%d**" % len(field_list))
        L.append("- 字段：`%s`" % "`, `".join(field_list))
    else:
        L.append("- 本次没有抓到任何记录，无法生成字段签名。")
    L.append("")
    if counts:
        ps = payload["per_page_summary"]
        L.append("- 每页条数：最少 %d / 最多 %d / 平均 %.2f（共记录 %d 页）"
                 % (ps["min"], ps["max"], ps["avg"], ps["pages_recorded"]))
        L.append("")
        L.append("<details><summary>每页明细</summary>")
        L.append("")
        items = ["%d:%d" % (k, v) for k, v in sorted(per_page.items())]
        for i in range(0, len(items), 10):
            L.append("`" + "  ".join(items[i:i + 10]) + "`")
        L.append("")
        L.append("</details>")
    L.append("")
    L.append("## 异常页")
    L.append("")
    if anomalies:
        L.append("| 页 | 原因 | URL |")
        L.append("|---|---|---|")
        for a in anomalies:
            L.append("| %s | %s | %s |" % (a.get("page"), a.get("reason"), a.get("url")))
    else:
        L.append("（无）")
    L.append("")
    L.append("## 产物")
    L.append("")
    L.append("- 数据：`%s`" % out_file)
    L.append("- 日志：`%s`" % log_path)
    L.append("- 断点：`%s`" % state_path)
    L.append("- 报告：`%s` / `%s`" % (json_path, base + ".md"))
    L.append("")

    md_path = base + ".md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    return md_path, json_path


def cli():
    import argparse
    ap = argparse.ArgumentParser(
        description="通用爬虫模板。默认按 CONFIG 跑全量；下面参数可以临时覆盖。")
    ap.add_argument("--pages", type=int, default=None,
                    help="只跑到第 N 页（覆盖 page_end）")
    ap.add_argument("--page-from", type=int, default=None,
                    help="从第 N 页开始（覆盖 page_start）")
    ap.add_argument("--delay", type=float, nargs=2, default=None,
                    metavar=("MIN", "MAX"), help="覆盖请求间隔，单位秒")
    ap.add_argument("--reset", action="store_true",
                    help="清空断点记录，下次会【重新请求站点每一页】（不删已抓数据）")
    ap.add_argument("--rebuild-index", action="store_true", dest="rebuild_index",
                    help="只从已有数据文件重建去重索引，不请求任何页面")
    ap.add_argument("--allow-empty", action="store_true", dest="allow_empty",
                    help="允许某页解析出 0 条仍算完成（默认不算，防止选择器写错造成静默丢数据）")
    ap.add_argument("--allow-no-dedup", action="store_true", dest="allow_no_dedup",
                    help="允许 dedup_key 字段在解析结果里不存在（默认遇到就中止，防止去重静默失效）")
    ap.add_argument("--site", default=None,
                    help="站点配置模块名（crawlers/sites/<name>.py），不填则用内置 books 配置")
    ap.add_argument("--job", default=None,
                    help="覆盖任务名（决定数据/日志/断点/报告文件名）。"
                         "做 A/B 对比时用它把两次结果写到不同文件")
    ap.add_argument("--transport", default=None,
                    choices=["plain", "cffi"],
                    help="v14 阶段 1：传输层覆盖（plain 默认 / cffi 冒充 TLS）")
    ap.add_argument("--terms-status", default=None,
                    choices=["unknown", "allowed", "blocked"],
                    help="Rule 0：站点条款状态（默认取站点 CONFIG，缺省 unknown=不抓）")
    ap.add_argument("--allow-robots-js", action="store_true", dest="allow_robots_js",
                    help="Rule 0 例外：仅限已获点对点授权的渲染站（为加载 JS/CSS 而越 robots 字面限制）")
    ap.add_argument("--detail-urls", default=None,
                   help="两段式第 2 段：只对这些 URL 抓详情（清单里一行一个）")
    ap.add_argument("--detail-mode", dest="detail_mode", default="auto",
                    choices=["auto", "generic", "off"],
                    help="详情阶段：auto=按站点配置决定，generic=强制走通用流程，"
                         "off=不进详情页")
    ap.add_argument("--ignore-cooldown", action="store_true",
                    help="无视冷却文件强行开跑（会立刻再敲站点，慎用）")
    ap.add_argument("--ignore-robots", dest="ignore_robots", action="store_true",
                    help="本次运行忽略 robots 判定（会在报告里留痕；默认关闭）")
    ap.add_argument("--no-repair-attachments", dest="repair_attachments",
                    action="store_false", default=None,
                    help="不补抓上次没下成的附件（默认会补）")
    ap.add_argument("--no-repair-details", dest="repair_details",
                    action="store_false", default=None,
                    help="关掉「开跑前补抓上次失败的详情」（默认开启）")
    return ap.parse_args()


def main():
    global parse_list

    args = cli()
    _RETRY_META["waits"] = 0
    _RETRY_META["max_sec"] = 0

    # 站点包：--site quotes 会加载 crawlers/sites/quotes.py 里的 CONFIG 和 parse_list
    # 这就是"换站只写一个文件"的落地方式
    site_mod = None
    if args.site:
        import importlib
        try:
            mod = importlib.import_module("sites." + args.site)
        except ImportError as e:
            print("找不到站点模块 sites/%s.py: %s" % (args.site, e))
            print("可用：%s" % ", ".join(sorted(
                p.stem for p in (Path(__file__).parent / "sites").glob("*.py") if p.stem != "__init__")))
            return 1
        CONFIG.update(mod.CONFIG)
        parse_list = mod.parse_list
        site_mod = mod
        print("已加载站点配置 sites/%s.py  job=%s" % (args.site, CONFIG["job"]))

    # v14.5：站点声明"不参与指纹"的字段（如 published="30分钟前"）
    HASH_EXCLUDE.clear()
    HASH_EXCLUDE.update(str(x) for x in (CONFIG.get("hash_exclude") or []))

    if args.pages is not None:
        CONFIG["page_end"] = args.pages
    if args.page_from is not None:
        CONFIG["page_start"] = args.page_from
    if args.delay is not None:
        CONFIG["delay_min"], CONFIG["delay_max"] = args.delay
    if getattr(args, "ignore_robots", False):
        _ROBOTS["ignore"] = True
        CONFIG["ignore_robots"] = True
    if args.job:
        CONFIG["job"] = args.job
    if args.transport:
        CONFIG["transport"] = args.transport
        print("传输层：%s" % args.transport)
    if getattr(args, "repair_attachments", None) is not None:
        CONFIG["repair_attachments"] = args.repair_attachments
    if getattr(args, "repair_details", None) is not None:
        CONFIG["repair_details"] = args.repair_details

    # 目录可用环境变量覆盖（测试隔离用：每个用例一个临时目录，互不干扰）。
    # 顺序放在最后：站点 CONFIG 里的默认值先上，环境变量再压过去。
    for cfg_key, env_key in (("out_dir", "CRAWLER_OUT_DIR"),
                             ("log_dir", "CRAWLER_LOG_DIR"),
                             ("state_dir", "CRAWLER_STATE_DIR"),
                             ("report_dir", "CRAWLER_REPORT_DIR")):
        v = os.environ.get(env_key)
        if v:
            CONFIG[cfg_key] = v

    # ---- Rule 0（最高优先级）：条款三态 → 不通过就在发任何请求之前停 ----
    import rule0
    _terms = rule0.terms_gate(CONFIG, getattr(args, "terms_status", None))
    _ov = rule0.build_override(CONFIG, bool(getattr(args, "allow_robots_js", False)))
    CONFIG["robots_override"] = _ov
    CONFIG["terms_status_effective"] = (
        "allowed" if _terms["ok"] else ("blocked" if _terms["reason"] == "blocked_terms"
                                        else "unknown"))
    if not _terms["ok"]:
        from urllib.parse import urlsplit as _us
        _host = _us(str(CONFIG.get("url_template") or CONFIG.get("first_url") or "")).netloc
        try:
            if CONFIG.get("log_dir"):
                os.makedirs(CONFIG["log_dir"], exist_ok=True)
            _lg = Logger(os.path.join(CONFIG.get("log_dir") or ".", "crawler-%s.log" % CONFIG["job"]))
        except Exception:
            _lg = print
        block = rule0.decision_block(
            _host, _terms["signal"], _terms["evidence"],
            "本次未发出任何请求（在 robots/首页之前就停了）")
        for line in block.splitlines():
            _lg(line)
        print(block)
        # 也要留一份报告（审计要求：任何退出路径都有报告）
        try:
            ctx = {"job": CONFIG["job"], "run_id": "%s-%s" % (
                       CONFIG["job"], datetime.now(TZ).strftime("%Y%m%d-%H%M%S")),
                   "t_start": time.time(), "t_end": time.time(), "stat": {},
                   "status": _terms["status"], "reason": _terms["reason"],
                   "mode": "rule0", "out_file": "", "field_list": [], "per_page": {},
                   "records_before": 0, "total_in_file": 0,
                   "terms_status": CONFIG["terms_status_effective"],
                   "rule0_block": block}
            ctx.update(rule0.override_report_fields(_ov))
            write_report(ctx)
        except Exception as e:
            print("（Rule 0 报告写入失败：%s）" % e)
        return 2

    if _ov.get("enabled"):
        print("Rule 0 例外生效：robots_override=true scope=%s by=%s at=%s max_pages=%s"
              % (_ov["scope"], _ov["authorized_by"], _ov["authorized_at"], _ov["max_pages"]))
    elif getattr(args, "allow_robots_js", False):
        print("Rule 0 例外未生效：%s" % _ov.get("why", ""))

    job = CONFIG["job"]
    run_id = "%s-%s" % (job, datetime.now(TZ).strftime("%Y%m%d-%H%M%S"))

    os.makedirs(CONFIG["out_dir"], exist_ok=True)
    os.makedirs(CONFIG["log_dir"], exist_ok=True)
    os.makedirs(CONFIG["state_dir"], exist_ok=True)

    log_path = os.path.join(CONFIG["log_dir"], "crawler-%s.log" % job)
    log = Logger(log_path)
    out_file = os.path.join(CONFIG["out_dir"], "%s.jsonl" % job)
    state_path = os.path.join(CONFIG["state_dir"], "state_%s.json" % job)

    # 报告素材容器：所有退出路径共用，保证失败/拒抓也有报告可查
    ctx = {
        "job": job, "run_id": run_id, "t_start": time.time(), "t_end": None,
        "stat": {}, "anomalies": [], "per_page": {}, "field_list": [],
        "out_file": out_file, "log_path": log_path, "state_path": state_path,
        "records_before": 0, "total_in_file": 0,
        "mode": "unknown", "status": "unknown", "reason": "",
        # Rule 0 留痕（v14）：条款状态 + 例外面（未启用时为空/false）
        "terms_status": CONFIG.get("terms_status_effective"),
        **rule0.override_report_fields(CONFIG.get("robots_override")),
    }

    def finalize(status, reason, rc):
        """统一退出收尾：写报告 → 关日志 → 返回退出码。任何路径都必须走这里。"""
        ctx["t_end"] = time.time()
        ctx["status"] = status
        ctx["reason"] = reason
        # Retry-After 统计是模块级的（_fetch_core 里没有 stat 引用），
        # 这里并入报告；早退路径（冷却/参数错）也照样写，值是 0。
        try:
            st_ = ctx.get("stat")
            if st_ is None:
                st_ = {}
                ctx["stat"] = st_
            st_["retry_after_waits"] = _RETRY_META["waits"]
            st_["retry_after_max_sec"] = _RETRY_META["max_sec"]
        except Exception:
            pass
        try:
            md_path, json_path = write_report(ctx)
            log("报告  %s" % md_path)
            log("      %s" % json_path)
        except Exception as e:
            log("!! 报告生成失败（不影响已抓的数据）: %s: %s" % (type(e).__name__, e))
        log("状态  %s / %s" % (status, reason))
        log("=" * 62)
        log.close()
        return rc

    log("=" * 62)
    log("任务 %s | run_id=%s" % (job, run_id))
    log("输出 %s" % out_file)
    _g = gate_mod.set_gate(gate_mod.build_from_config(CONFIG, log))
    log("间隔 %.1f~%.1f 秒/请求，重试上限 %d 次"
        % (CONFIG["delay_min"], CONFIG["delay_max"], CONFIG["retries"]))
    if _g is not None:
        log("闸门 %d 次/分（窗口 %.0fs，抖动 %.1f~%.1f 秒）+ 单任务 %d 请求 / %.0f 分钟"
            % (_g.max_rpm, _g.window_sec, _g.jitter[0], _g.jitter[1],
               _g.max_requests, _g.max_seconds / 60.0))

    # 只重建索引就到此为止，不碰网络
    if args.rebuild_index:
        try:
            seen_only = rebuild_seen(out_file, CONFIG["dedup_key"])
        except BadDataFile as e:
            log("!! %s" % e)
            return finalize("failed", "data_file_corrupt", 2)
        st0 = load_state(state_path, out_file)
        st0["seen_keys"] = list(seen_only)
        st0["out_file"] = out_file
        st0["updated_at"] = now_iso()
        save_state(state_path, st0)
        log("--rebuild-index：从数据文件重建出去重键 %d 条，未请求任何页面" % len(seen_only))
        ctx["records_before"] = len(seen_only)
        ctx["total_in_file"] = len(seen_only)
        ctx["mode"] = "noop"
        return finalize("noop", "rebuild_index_only", 0)

    # 页范围校验：--pages 3 --page-from 20 这种组合会得到空区间，必须明确报错而不是静默 0 页
    # 注意顺序：--rebuild-index 在上面已经返回 —— 它是纯本地操作，
    # 不该被页范围、冷却、json/soft_block 兼容性这些"联网前检查"挡住。
    if CONFIG["page_start"] > CONFIG["page_end"]:
        log("!! 页范围为空：page_start=%d > page_end=%d，什么都不会抓。"
            % (CONFIG["page_start"], CONFIG["page_end"]))
        log("   检查 --pages / --page-from 是否写反，或 CONFIG 里的 page_start/page_end。")
        return finalize("failed", "empty_page_range", 1)

    sess = session_factory()
    first_url = CONFIG["url_template"].format(page=CONFIG["page_start"])
    site_host = urlsplit(first_url).netloc.lower()
    cd_key = cooldown_group(site_host)   # 冷却按"组"锁，默认等于 host

    # ---- 软封判定需要 HTML 解析；json 模式下 parse_list 解不了 dict ----
    # 不拒绝的话，canary 会一直"无法判定"，等于配了开关却永远不触发（假安全）。
    sb0 = soft_block_cfg()
    if sb0.get("enabled") and response_mode() == "json":
        log("!! soft_block.enabled=true 但 response=json：")
        log("!! json 模式下 canary 无法用 parse_list 解析，软封判定会永远不触发。")
        log("!! 要么关掉 soft_block，要么给该站改成 html 模式。本次直接退出（零请求）。")
        return finalize("failed", "soft_block_incompatible", 1)


    # ---- 冷却检查：必须排在 robots 之前（但排在 rebuild-index 之后，纯本地操作不该被挡）----
    # 被判软封后整站都在返回假页面，这时候连 robots 都不该再敲。
    cd = load_cooldown(cd_key, log)
    cd_until = cooldown_until(cd)
    if cd and cd_until is not None and datetime.now(TZ) < cd_until:
        if getattr(args, "ignore_cooldown", False):
            log("!" * 62)
            log("!! 冷却期未结束（到 %s），但指定了 --ignore-cooldown" % cd["until"])
            log("!! 这一跑会继续敲站点，风险自负")
            log("!" * 62)
        else:
            log("!! 冷却中：%s 到 %s 之前不再请求（原因 %s，第 %d 次）"
                % (cd_key, cd.get("until"), cd.get("reason"), cd.get("strikes", 0)))
            log("!! 要强行跑请加 --ignore-cooldown；本次未发出任何网络请求")
            ctx["cooldown"] = cd
            return finalize("failed", "cooldown_active", 6)


    if not load_robots(sess, first_url, log):
        log("robots.txt 判定不允许抓取 → 退出（不硬来）")
        return finalize("failed", "robots_denied", 2)

    st = load_state(state_path, out_file)

    # ---- 筛选条件指纹检测（先于 page_size）----
    # 同一 job 换筛选 → 页码与内容的对应关系整体作废，旧断点必须清。
    fp_now = query_fingerprint(first_url)
    fp_old = st.get("filters_fp") or ""
    if fp_now and fp_old and fp_now != fp_old:
        log("!! 筛选条件变了（指纹 %s → %s）→ 旧断点作废" % (fp_old, fp_now))
        log("!!   清空 pages_done（%d 页）与 pages_declared（%s），保留去重键 %d 条"
            % (len(st.get("pages_done") or []), st.get("pages_declared"),
               len(st.get("seen_keys") or [])))
        st["pages_done"] = []
        # next / cursor 模式的断点也在 st 里，同样必须清：
        # 不清的话会从"旧筛选条件抓到的下一页"接着抓，等于把旧条件的数据当成新条件的。
        st["urls_done"] = []
        st["next_url"] = None
        st["pages_declared"] = None
        ctx.setdefault("anomalies", []).append(
            {"page": "state", "url": first_url,
             "reason": "筛选条件变更 %s→%s，已清 pages_done/urls_done/next_url/pages_declared"
                       % (fp_old, fp_now)})
    st["filters_fp"] = fp_now

    # ---- page_size 变更检测 ----
    # 站点用 page_size 改变每页条数时，页码与内容的对应关系就变了：
    # 旧断点里的 pages_done 全部作废（否则会跳过没抓过的内容）。
    # 去重键 seen_keys 必须保留（它跟页码无关，是真正的"抓过没有"）。
    ps_now = CONFIG.get("page_size") or ""
    ps_old = st.get("page_size") or ""
    if ps_now != ps_old and st.get("pages_done"):
        log("注意：page_size 从 %r 变成 %r → 旧断点（%d 页）作废，去重键保留 %d 条"
            % (ps_old, ps_now, len(st.get("pages_done") or []), len(st.get("seen_keys") or [])))
        st["pages_done"] = []
        st["page_size"] = ps_now
        st["out_file"] = out_file
        st["updated_at"] = now_iso()
        save_state(state_path, st)
        ctx.setdefault("anomalies", []).append(
            {"page": "state", "url": "", "reason": "page_size 变更 %r→%r，已清 pages_done"
                                                    % (ps_old, ps_now)})
    elif ps_now:
        st["page_size"] = ps_now
    if args.reset:
        # 只清"已完成页"，去重键永远从数据文件重建，不受 --reset 影响
        log("!! --reset：断点已清空。下次会【重新请求目标站点的每一页】，")
        log("!!          不是只重建本地索引。只想重建索引请用 --rebuild-index，")
        log("!!          只想重抓部分页请用 --page-from。")
        # 复合状态（st）里两种分页的断点都清掉
        st = blank_state(out_file)
        save_state(state_path, st)
        log("断点已按 --reset 清空（已抓数据保留，重复内容仍会被去重）")

    try:
        seen = rebuild_seen(out_file, CONFIG["dedup_key"])
    except BadDataFile as e:
        # 注意：此时 anomalies 还没创建（它在下面才定义），这里只记日志 + 收尾
        log("!! %s" % e)
        return finalize("failed", "data_file_corrupt", 2)
    log("去重键：从已有数据文件重建 %d 条" % len(seen))
    pages_done = set(st["pages_done"])

    # ---- A5：window 模式 —— 每一轮都重抓，断点不跨运行 ----
    # 根因（A5）：滚动时间窗（settr=3）+ 页码断点 = 第 1 页永远"已完成"
    #   → 新岗位永远在第 1 页顶部，而第 1 页永远被跳过 → 一个请求都不发。
    # 修法：window 模式**每次开跑就清空 pages_done**（不是"跨天才作废"）——
    #   因为同一天跑第二次时，第 1 页也在这一轮之前刚被抓过，按日期戳它还"有效"，
    #   于是第二次又变成"跳过 → 一个请求都不发"。只有"每轮重抓"才真的解决。
    # 代价说清楚：window 一轮只抓前 refresh_pages 页（默认 3），重抓成本很低；
    #   真正的去重靠 seen_keys（它跟页码无关，不清）。
    # full 模式完全不动（full 是"抓完整站"语义，续跑必须保留断点）。
    if coverage_mode() == "window":
        _prev_n = len(pages_done)
        if _prev_n:
            log("window 模式：每轮重抓前 %d 页 → 清空上一轮的 %d 页断点（%s）"
                % (int(CONFIG.get("refresh_pages") or 3), _prev_n,
                   ",".join(str(x) for x in sorted(pages_done)[:10])))
        pages_done = set()
        st["pages_done"] = []
        st["pages_done_at"] = {}
        ctx["window_expired_pages"] = _prev_n
    log("断点：已完成 %d 页，已知去重键 %d 条" % (len(pages_done), len(seen)))

    # 记录"运行前已有多少条"，报告里要区分增量运行和全量运行
    ctx["records_before"] = len(seen)
    # 同一时刻同步"文件当前行数"：任何早退路径（清单空、参数错、robots 拒…）
    # 都不会再出现 60+0≠0 的账目不自洽。
    ctx["total_in_file"] = len(seen)
    ctx["mode"] = "incremental" if len(seen) > 0 else "full"

    t_start = time.time()
    ctx["t_start"] = t_start
    stat = {"pages_total": 0, "pages_ok": 0, "pages_skipped": 0, "pages_empty": 0,
            "pages_blocked": 0, "pages_failed": 0, "records_new": 0, "records_dup": 0,
            "detail_failed": 0,
            # 阶段A 新增（先置 0，报告里一定能读到）
            "retry_after_waits": 0, "retry_after_max_sec": 0,
            "soft_block_detected": 0, "canary_requests": 0, "pages_soft_blocked": 0,
            "resp_bytes_min": 0, "resp_bytes_total": 0, "cards_total": 0}
    ctx["stat"] = stat
    consecutive_empty = 0
    dedup_checked = False
    prev_url = ""          # 上一页的 URL，用来给下一页当 Referer
    soft_blocked = False   # 判定软封后不再继续

    # 采集报告用的素材（与 ctx 共享引用，后续 append 会自动同步）
    anomalies = []      # [{page, url, reason}]
    per_page = {}       # {page: 条数}  只记本次真正抓到的页
    field_list = []     # 字段签名（会先从数据文件恢复，再与本页字段取并集）
    field_list.extend(rebuild_field_signature(out_file))
    if field_list:
        log("字段签名：从已有数据文件恢复 %d 个字段" % len(field_list))
    ctx["anomalies"] = anomalies
    ctx["per_page"] = per_page
    ctx["field_list"] = field_list

    # ---- 开跑前先补抓上次没抓全的详情 ----
    # 这是 codex 指出的阶段1 核心：页面被标记完成 ≠ 详情抓全了。
    # 不补的话，一次偶发超时就让那几条数据永久缺失，而且下次重跑直接跳过整页。
    d_cfg = detail_cfg()
    # --detail-urls（两段式第 2 段）时不跑例行补抓：那会把"只抓清单"变成"全补一遍"
    if (not getattr(args, "detail_urls", None)
            and resolve_detail_mode(args.detail_mode, site_mod) != "off"
            and CONFIG.get("repair_details") and d_cfg.get("enabled")
            and site_mod is not None and hasattr(site_mod, "parse_detail")):
        try:
            rcp = repair_pending_details(out_file, sess, log, CONFIG,
                                         anomalies, site_mod.parse_detail)
        except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
            # 闸门停止：补抓半途收工。文件里没补完的记录保持原状态 → 下次可续跑。
            why = ("request_budget_exceeded" if isinstance(ge, RequestBudgetExceeded)
                   else "time_budget_exceeded")
            log("!! 闸门在【详情补抓】阶段停止：%s → 本轮收工，状态已保留可续跑" % ge)
            anomalies.append({"page": "repair", "url": "", "reason": "闸门停止：%s" % why})
            ctx["gate_stage"] = "repair_details"
            return finalize("partial", why, 3)
        except Exception as e:
            log("!! 详情补抓异常 %s: %s" % (type(e).__name__, e))
            anomalies.append({"page": "repair", "url": "",
                              "reason": "补抓流程异常 %s" % type(e).__name__})
            rcp = {}

        for k, v in rcp.items():
            if k == "detail_repair_abort":
                if v:
                    # 补抓时被 403/429 拒了，说明对方不想我们再动，立即收工
                    return finalize("failed", v, 4)
                continue
            stat[k] = stat.get(k, 0) + v

    # ---- 开跑前补抓上次没下成的附件 ----
    # 与详情补抓同理：页面标记完成 ≠ 附件下全了。只重试可重试的状态。
    if (not getattr(args, "detail_urls", None)
            and attach_cfg().get("enabled") and CONFIG.get("repair_attachments", True)):
        try:
            repair_pending_attachments(out_file, sess, log, anomalies, stat)
        except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
            why = ("request_budget_exceeded" if isinstance(ge, RequestBudgetExceeded)
                   else "time_budget_exceeded")
            log("!! 闸门在【附件补抓】阶段停止：%s → 本轮收工，状态已保留可续跑" % ge)
            anomalies.append({"page": "repair", "url": "", "reason": "闸门停止：%s" % why})
            ctx["gate_stage"] = "repair_attachments"
            return finalize("partial", why, 3)
        except BadDataFile as e:
            log("!! %s" % e)
            anomalies.append({"page": "repair", "url": "", "reason": str(e)})
            return finalize("failed", "data_file_corrupt", 2)
        except Exception as e:
            log("!! 附件补抓异常 %s: %s" % (type(e).__name__, e))
            anomalies.append({"page": "repair", "url": "",
                              "reason": "附件补抓流程异常 %s" % type(e).__name__})

    # ---- 两段式第 2 段：只对清单里的详情 URL 抓，列表页一个请求都不发 ----
    if getattr(args, "detail_urls", None):
        src = Path(args.detail_urls)
        if not src.exists():
            log("!! --detail-urls 指向的文件不存在：%s" % src)
            return finalize("failed", "detail_urls_not_found", 1)
        urls = []
        for ln in src.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                urls.append(ln)
        if not urls:
            log("!! --detail-urls 清单是空的")
            return finalize("failed", "detail_urls_empty", 1)
        if site_mod is None or not hasattr(site_mod, "parse_detail"):
            return finalize("failed", "detail_urls_no_parser", 1)
        log("两段式第 2 段：清单 %d 个 URL，只抓这些详情（不请求列表页）" % len(urls))
        # 账目口径：第 2 段不改行数，只补字段 → before = total，new = 0
        try:
            _rows0 = load_rows(out_file)
        except BadDataFile as e:
            log("!! %s" % e)
            return finalize("failed", "data_file_corrupt", 2)
        ctx["records_before"] = len(_rows0)
        ctx["total_in_file"] = len(_rows0)
        try:
            cp = repair_pending_details(out_file, sess, log, CONFIG, anomalies,
                                        site_mod.parse_detail, only_urls=urls)
        except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
            why = ("request_budget_exceeded" if isinstance(ge, RequestBudgetExceeded)
                   else "time_budget_exceeded")
            log("!! 闸门在【清单补详情】阶段停止：%s → 已完成的已落盘，可续跑" % ge)
            ctx["gate_stage"] = "repair_details"
            return finalize("partial", why, 3)
        for k, v in cp.items():
            if k == "detail_repair_abort":
                if v:
                    return finalize("failed", v, 4)
                continue
            stat[k] = stat.get(k, 0) + v

        # ---- 第 2 段顺带把「选中记录」的附件下掉 ----
        # 为什么不另开第 3 段：附件和详情是同一批记录的两个属性，
        # 分开跑会让"哪条记录齐了"变得难以判定。
        if attach_cfg().get("enabled"):
            try:
                _rows = load_rows(out_file)
            except BadDataFile as e:
                log("!! %s" % e)
                return finalize("failed", "data_file_corrupt", 2)
            _want = {u.rstrip("/") for u in urls}
            _sel = [r for r in _rows
                    if (r.get("detail_url") or "").rstrip("/") in _want]
            if _sel:
                log("两段式第 2 段：对选中的 %d 条记录下附件" % len(_sel))
                try:
                    download_attachments(_sel, sess, log, CONFIG, anomalies, stat,
                                         CONFIG.get("job"))
                except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
                    why = ("request_budget_exceeded"
                           if isinstance(ge, RequestBudgetExceeded) else "time_budget_exceeded")
                    log("!! 闸门在【第 2 段附件】阶段停止：%s → 已下好的状态照常回写" % ge)
                    rewrite_rows(out_file, _rows)
                    ctx["total_in_file"] = len(_rows)
                    ctx["gate_stage"] = "attachment"
                    return finalize("partial", why, 3)
                rewrite_rows(out_file, _rows)      # 原子回写附件结果
                ctx["total_in_file"] = len(_rows)
                # 附件有没下成的 → 这一轮不算“补好了”，要报 partial/attachment_partial。
                # 口径与主流程末尾那段一致（同一组计数键），避免两处判定不同步。
                _bad_keys = ("attach_too_many", "attach_too_large", "attach_quota",
                             "attach_dns_failed", "attach_robots_denied",
                             "attach_robots_check_failed", "attach_type_rejected",
                             "attach_private_host", "attach_bad_scheme",
                             "attach_denied_ext", "attach_download_failed",
                             "attach_stage_failed")
                _att_bad = sum(stat.get(k, 0) for k in _bad_keys)
                if _att_bad > 0:
                    log("注意：第 2 段有 %d 个附件没下成 → 判为 partial/attachment_partial"
                        % _att_bad)
                    return finalize("partial", "attachment_partial", 3)
            else:
                log("两段式第 2 段：清单里的记录没有附件字段，跳过附件阶段")
        else:
            log("两段式第 2 段：附件功能对本站未启用，本段只补详情")
        ok_n = cp.get("detail_repaired_ok", 0)
        fail_n = cp.get("detail_repaired_fail", 0)
        log("清单补详情：成功 %d / 失败 %d / robots 跳过 %d / 清单外或缺失 %d"
            % (ok_n, fail_n, cp.get("detail_repaired_robots", 0),
               cp.get("detail_urls_missing", 0)))
        if fail_n:
            return finalize("partial", "detail_pending_remains", 3)
        if ok_n:
            return finalize("success", "details_repaired", 0)
        return finalize("noop", "nothing_done", 0)

    fh = open(out_file, "a", encoding="utf-8", newline="\n")

    # ---- 待抓序列：两种分页共用同一段处理逻辑 ----
    paginate = (CONFIG.get("paginate") or "number").lower()
    if paginate not in ("number", "next"):
        log("!! CONFIG['paginate'] 只能是 number 或 next，现在是 %r" % paginate)
        fh.close()
        return finalize("failed", "bad_paginate_mode", 1)

    if response_mode() not in ("html", "json"):
        log("!! CONFIG['response'] 只能是 html 或 json，现在是 %r → 不猜、直接失败"
            % CONFIG.get("response"))
        fh.close()
        return finalize("failed", "bad_response_mode", 1)

    if (json_cfg().get("total_scope") or "global").lower() not in ("global", "page"):
        log("!! json.total_scope 只能是 global 或 page，现在是 %r"
            % json_cfg().get("total_scope"))
        fh.close()
        return finalize("failed", "bad_total_scope", 1)

    # JSON + next 但没有配"下一页怎么找" → 配置错误，必须明确失败。
    # 否则只抓第一页、stop_reason=no_next、status=success —— 看起来一切正常，
    # 实际后面的页一条没抓，属于最恶劣的静默截断。
    if response_mode() == "json" and paginate == "next":
        jc0 = json_cfg()
        if not jc0.get("next_path") and not jc0.get("cursor_path") and not jc0.get("single_page"):
            log("!! 配置错误：response=json + paginate=next，但 json.next_path 和 "
                "json.cursor_path 都没配。")
            log("!! 如果这个接口确实只有一页，请显式写 json.single_page = True。")
            fh.close()
            return finalize("failed", "json_pagination_not_configured", 1)

    urls_done = set(st.get("urls_done") or [])
    visited = set(urls_done)          # 已抓过的 URL（含本次），防循环
    max_pages = int(CONFIG.get("max_pages") or 200)
    stop_reason = ""

    if st.get("paginate_mode") and st["paginate_mode"] != paginate:
        log("注意：这个 job 上次用的是 %s 分页，这次是 %s。"
            % (st["paginate_mode"], paginate))
        log("      两种模式的断点是分开存的（pages_done / urls_done），不会互相跳过。")

    if paginate == "number":
        _pe = CONFIG["page_end"]
        if coverage_mode() == "window":
            # A5：滚动时间窗下"抓完整站"没意义，只维护最近窗口。
            # 默认前 3 页；站点可用 refresh_pages 覆盖。
            _cap = int(CONFIG.get("refresh_pages") or 3)
            _pe = min(_pe, CONFIG["page_start"] + _cap - 1)
            log("window 模式：本轮只看前 %d 页（第 %d–%d 页）"
                % (_cap, CONFIG["page_start"], _pe))
            # 报告里的 pages_planned 必须跟着变小，否则"计划 20 页、实际 3 页"是假账
            ctx["pages_planned"] = _pe
            ctx["pages_effective"] = _pe
        work = [(p, CONFIG["url_template"].format(page=p))
                for p in range(CONFIG["page_start"], _pe + 1)]
    else:
        if site_mod is None or (response_mode() != "json" and not hasattr(site_mod, "parse_next")):
            log("!! paginate=next 需要站点模块提供 parse_next(html, page_url)"
                "（JSON 模式下由引擎从 json.next_path / json.cursor_path 取，不需要这个函数）")
            fh.close()
            return finalize("failed", "missing_parse_next", 1)
        # 续跑：上次记下的"下一页"就是这次起点；没有就从头开始
        start_url = st.get("next_url") or first_url
        if normalize_url(start_url) in urls_done:
            # 断点里说下一页已抓过 —— 说明上次刚好抓完最后一页，没有下一页了
            log("断点显示没有下一页可抓（next_url 已完成），本次不再请求")
            work = []
            stop_reason = "no_next"
        else:
            log("分页方式：下一页链接（起始 %s；已完成 %d 个 URL）"
                % (start_url, len(urls_done)))
            work = [(1, start_url)]

    # 页数口径（提案1）：plan 是"计划抓多少页"，declared 是页面自己声明的总页数
    if coverage_mode() != "window":      # window 模式下上面已按 refresh_pages 设过
        ctx["pages_planned"] = CONFIG["page_end"]
        ctx["pages_effective"] = CONFIG["page_end"]
    # 续跑时上一次已经知道 M，就不必再从页面读（那一页可能全被跳过）
    ctx["pages_declared"] = st.get("pages_declared") or None
    ctx["truncated"] = False
    _m_tried = False

    # ---- 进循环前：用断点里的 M 清洗 pages_done 的超限页 ----
    # 断点里的 pages_declared 是上一轮读到的总页数。pages_done 里若有超出它的页，
    # 说明上一轮 M 更大、或旧版本误抓过"最后一页的重复内容"。
    # 必须在这里剔除，原因很硬：那些页会先被 `page in pages_done` 跳过，
    # 一个请求都不发 → 循环内的"发现 M 并剔除"逻辑根本没机会执行。
    # 只剔 pages_done，**不动 work、不动 page_end**：
    # 本轮实际抓几页由本次请求重新读到的 M 决定（M 每天会变）。
    _M0 = ctx.get("pages_declared")
    if paginate == "number" and _M0:
        _over = sorted(p for p in list(pages_done) if beyond_declared(p, _M0))
        if _over:
            if hasattr(pages_done, "discard"):
                for _p in _over:
                    pages_done.discard(_p)
            else:
                pages_done[:] = [p for p in pages_done
                                 if not (beyond_declared(p, _M0))]
            log("断点里有 %d 页超出上一轮读到的总页数 %d → 已剔除（%s%s）"
                % (len(_over), _M0, ",".join(str(x) for x in _over[:10]),
                   " ..." if len(_over) > 10 else ""))

    idx = 0
    # A5：window 模式的"连续见过"计数器（跨页累计；full 模式不用）
    window_consec_dup = 0
    try:
        while work:
            page, url = work.pop(0)
            idx += 1
            stat["pages_total"] += 1

            if paginate == "number" and page_done(page, pages_done):
                stat["pages_skipped"] += 1
                continue

            if paginate == "next":
                if idx > max_pages:
                    stop_reason = "max_pages_reached"
                    stat["pages_total"] -= 1
                    log("已达 max_pages=%d 上限 → 停止翻页" % max_pages)
                    break
                nu = normalize_url(url)
                if nu in visited:
                    stop_reason = "pagination_loop"
                    stat["pages_total"] -= 1
                    log("下一页指回了已抓过的 URL → 判定为翻页循环，停止")
                    log("    %s" % url)
                    break

            # 逐页检查 robots（同一份规则，不重复下载 robots.txt）
            if not url_allowed(url, log, stage="page"):
                stat["pages_blocked"] += 1
                anomalies.append({"page": page, "url": url, "reason": "robots 禁止"})
                # 列表页被禁 = 这一站根本没法抓，立刻停整轮并出决策块，
                # 而不是"跳过这页继续下一页"（那会把 900 页跑成空数据）
                _ROBOTS_STOP["reason"] = "robots_denied_need_decision"
                stop_reason = ("all_pages_blocked_by_robots"
                               if stat["pages_ok"] == 0 else "blocked_by_robots")
                dec = _ROBOTS_DECISIONS[-1] if _ROBOTS_DECISIONS else {}
                robots_decision_block(log, "列表页", url,
                                      dec.get("rule", ""), dec.get("rule_line", 0),
                                      "第 %s 页被禁，本站一个字节都没抓" % page)
                break

            mode_resp = response_mode()
            if paginate == "number":
                log("第 %d/%d 页 → %s" % (page, CONFIG["page_end"], url))
            else:
                log("第 %d 页 → %s" % (idx, url))

            # Referer 按页传：第 1 页给站点根，之后给上一页的 URL。
            # 不做"全局静态 Referer"——那在跨页时反而是明显的不自然特征。
            if idx == 1:
                ref = "%s://%s/" % (urlsplit(url).scheme, urlsplit(url).netloc)
            else:
                ref = prev_url or ("%s://%s/" % (urlsplit(url).scheme, urlsplit(url).netloc))
            try:
                if mode_resp == "json":
                    code, payload = fetch_page(sess, url, log, page=page, referer=ref)
                else:
                    code, payload = fetch_page(sess, url, log, referer=ref)
            except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
                stop_reason = ("request_budget_exceeded"
                               if isinstance(ge, RequestBudgetExceeded)
                               else "time_budget_exceeded")
                log("!! 闸门停止：%s" % ge)
                anomalies.append({"page": page, "url": url,
                                  "reason": "闸门停止：%s" % stop_reason})
                ctx["gate_stage"] = "page"
                break
            prev_url = url
            # 立刻快照"这一页"的响应元信息：后面打 canary 会把 _LAST_META 覆盖掉，
            # 到那时再读就成了 canary 的字节数/响应头，证据会张冠李戴。
            page_meta = dict(_LAST_META)

            if code is None:
                stat["pages_failed"] += 1
                anomalies.append({"page": page, "url": url, "reason": "重试耗尽（超时/网络异常）"})
                if paginate == "next":
                    # 拿不到这一页的 HTML，就没有"下一页"链接可读 —— 只能停，
                    # 而且必须明确说清"从第几页开始没抓到"，不能假装抓完了
                    stop_reason = "pagination_broken_at_page_%d" % idx
                    log("  这一页拿不到，下一页地址也就无从得知 → 停止翻页")
                    break
                log("  放弃这一页（重试已用完），继续下一页")
                polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
                continue

            if code != 200 or payload is None:
                stat["pages_failed"] += 1
                reason = ("HTTP %s" % code) if code != 200 else "响应无法解析（非 JSON / 空）"
                anomalies.append({"page": page, "url": url, "reason": reason})
                if paginate == "next":
                    stop_reason = "pagination_broken_at_page_%d" % idx
                    log("  跳过（%s）→ 读不到下一页，停止翻页" % reason)
                    break
                log("  跳过（%s）" % reason)
                polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
                continue

            try:
                if mode_resp == "json":
                    rows, invalid_items = rows_from_json(payload, url)
                else:
                    rows, invalid_items = parse_list(payload, url), 0
            except ApiError as e:
                # 业务层报错（HTTP 200 但 code≠0）。这不是"这页空"，是站方明确说不行，
                # 所以按失败记，并且不再往下翻（继续翻只会一直报同样的错）。
                stat["pages_failed"] += 1
                anomalies.append({"page": page, "url": url, "reason": "接口业务错误：%s" % e})
                log("  接口业务错误：%s" % e)
                stop_reason = "api_business_error_at_page_%d" % idx
                break
            except Exception as e:
                stat["pages_failed"] += 1
                anomalies.append({"page": page, "url": url,
                                  "reason": "解析异常 %s: %s" % (type(e).__name__, e)})
                if paginate == "next":
                    stop_reason = "pagination_broken_at_page_%d" % idx
                    log("  解析失败 %s → 停止翻页" % type(e).__name__)
                    break
                log("  解析失败 %s: %s" % (type(e).__name__, e))
                polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
                continue

            # ---- 总页数发现（提案1）----
            # 从**本轮第一个真正抓到的页面**解析：续跑时第 1 页可能被跳过，
            # 所以不能写死"只读第 1 页"，否则续跑永远拿不到 M。
            # 语义（2026-11-11 修正）：
            #   M ≤ 计划 → 夹紧到 M，这是"抓全了"，truncated=False
            #   M > 计划 → 本次只覆盖一个窗口，truncated=True（报不报 partial 看状态块）
            # 站点没配 pattern / parse_total_pages → 静默跳过，不记 anomaly
            #
            # ⚠ 2026-11-11 修复：原来这里还要求 ctx["pages_declared"] is None，
            #   于是"续跑时断点里已有 M"就完全跳过发现+夹紧逻辑 →
            #   第 6..20 页全部当正常页去抓（实测多 15 个请求 + 75 条重复丢弃）。
            #   现在改成只看"本轮是否已经试过"（_m_tried）：
            #   每轮都用**本次读到的 M** 覆盖断点里的旧值（M 每天会变），
            #   这样 M 变小能及时刹车，M 变大也能正确继续。
            if (paginate == "number" and mode_resp == "html"
                    and not _m_tried
                    and total_pages_supported(site_mod)):
                _m_tried = True
                _prev_M = ctx.get("pages_declared")
                M = declared_total_pages(payload, url, site_mod)
                if M:
                    planned = CONFIG["page_end"]
                    if _prev_M and _prev_M != M:
                        log("总页数有变化：断点里是 %s 页，本次读到 %d 页 → 以本次为准"
                            % (_prev_M, M))
                    ctx["pages_declared"] = M
                    # 断点里若有超出本轮 M 的页，必须剔除。
                    # 成因：上一轮 M 更大、或旧版本误抓过超限页（那些页其实是"最后一页"的重复内容）。
                    # 不剔除的话，M 一旦变大，这些页会被误判"已完成"→ 漏抓真实数据。
                    _over = sorted(p for p in list(pages_done) if beyond_declared(p, M))
                    if _over:
                        if hasattr(pages_done, "discard"):
                            for _p in _over:
                                pages_done.discard(_p)
                        else:
                            pages_done[:] = [p for p in pages_done if not (beyond_declared(p, M))]
                        log("断点里有 %d 页超出站点声明的 %d 页 → 已剔除（%s%s）"
                            % (len(_over), M, ",".join(str(x) for x in _over[:10]),
                               " ..." if len(_over) > 10 else ""))
                    if M <= planned:
                        CONFIG["page_end"] = M
                        work = [(p, u) for (p, u) in work if p <= M]
                        ctx["pages_effective"] = M
                        ctx["truncated"] = False
                        log("页面声明共 %d 页 ≤ 计划 %d 页 → 夹紧到 %d 页（视为抓全）"
                            % (M, planned, M))
                    else:
                        ctx["pages_effective"] = planned
                        ctx["truncated"] = True
                        log("页面声明共 %d 页 > 计划 %d 页 → 本次只覆盖前 %d 页"
                            % (M, planned, planned))
                else:
                    anomalies.append({"page": page, "url": url,
                                      "reason": "页面上读不到总页数（按配置页数继续）"})
                    log("  读不到总页数 → 按配置页数 %d 继续（只记 anomaly，不拦）"
                        % CONFIG["page_end"])

            # 响应体积与卡片数：报告里要能看出"这页是不是被替换成了假页面"
            _rb = int(page_meta.get("bytes") or 0)
            if _rb:
                stat["resp_bytes_total"] += _rb
                stat["resp_bytes_min"] = _rb if not stat["resp_bytes_min"] else min(stat["resp_bytes_min"], _rb)

            # 接口里的名单里混进了非对象条目（字符串/数字/null）：
# 这些条目的数据拿不到，但绝不能静默跳过——否则"抓了 10 条"其实只有 8 条可用。
            if invalid_items:
                stat["invalid_items"] = stat.get("invalid_items", 0) + invalid_items
                log("!! 本页有 %d 个条目不是对象，已跳过（计入报告）" % invalid_items)
                anomalies.append({"page": page, "url": url,
                                  "reason": "接口条目不是对象 %d 个" % invalid_items})

            # 接口自报的总数：只记录 + 做一次交叉提醒，不作为成功判据
            if mode_resp == "json":
                tot = json_total(payload)
                if tot is not None:
                    stat["json_total_reported"] = tot
                    if not stat.get("json_total_first_page"):
                        stat["json_total_first_page"] = tot

            stat["cards_total"] = stat.get("cards_total", 0) + len(rows)

            # ---- 去重前置 ----
            # 已经抓过的记录，不必再请求详情、更不必下载附件：
            # 原来顺序是"详情 → 附件 → 写入时才发现重复"，白白打了 N 倍请求。
            dup_now = 0
            # A5：跨页累计"连续见过"的条数（遇到新记录就清零）。
            # 用累计而不是按页，是因为一页可能只有 5 条，单页永远到不了阈值。
            if rows:
                fresh = []
                batch_seen = set()
                for r0 in rows:
                    k0 = str(r0.get(CONFIG["dedup_key"]) or "")
                    # "已抓过" 和 "本页内重复" 都要在这里拦下：
                    # 只查 seen 的话，同一页里两条相同记录会各抓一次详情、
                    # 各下一份附件（第二份被改名成 xxx_1.pdf），既费流量又多出文件。
                    if k0 and (k0 in seen or k0 in batch_seen):
                        dup_now += 1
                        window_consec_dup += 1
                        continue
                    window_consec_dup = 0   # A5：遇到新记录，连续计数清零
                    if k0:
                        batch_seen.add(k0)
                    fresh.append(r0)
                rows = fresh
                if dup_now:
                    stat["records_dup"] += dup_now
                    log("  本页 %d 条已抓过，跳过详情/附件" % dup_now)

            # 去重键校验（只查第一页一次）
            # 字段名写错的话，key 全是空字符串 → 去重静默失效 → 重复数据一路写进去
            if rows and not dedup_checked:
                dedup_checked = True
                if CONFIG["dedup_key"] not in rows[0]:
                    log("!! parse_list 返回的记录里没有去重键字段 '%s'" % CONFIG["dedup_key"])
                    log("!! 现有字段：%s" % ", ".join(sorted(rows[0].keys())))
                    log("!! 这样去重会完全失效，重复记录会被当成新数据写进去。")
                    if args.allow_no_dedup:
                        log("!! --allow-no-dedup 已指定，继续（去重可能失效）")
                    else:
                        log("!! 中止。确认要这么干才加 --allow-no-dedup。")
                        stat["pages_failed"] += 1
                        break

            # 去重键"有字段但值是空"：字段映射配错、或接口这一批没给主键。
            # 这会让去重完全失效（空 key 一律不参与判重），必须显式计入报告。
            n_empty_key = sum(1 for r in rows if not str(r.get(CONFIG["dedup_key"]) or "").strip())
            if n_empty_key:
                stat["dedup_key_empty"] = stat.get("dedup_key_empty", 0) + n_empty_key
                log("!! 本页有 %d 条记录的去重键 '%s' 是空的 —— 这些行不会参与去重"
                    % (n_empty_key, CONFIG["dedup_key"]))
                anomalies.append({"page": page, "url": url,
                                  "reason": "去重键为空 %d 条（字段映射缺失？）" % n_empty_key})


            if not rows and dup_now:
                stat["pages_ok"] += 1
                if paginate == "number":
                    _over_M2 = (ctx.get("pages_declared")
                                and beyond_declared(page, ctx.get("pages_declared")))
                    if not _over_M2:
                        pages_done.add(page)
                        st["pages_done"] = sorted(pages_done)
                        if coverage_mode() == "window":
                            st.setdefault("pages_done_at", {})[str(page)] = date.today().isoformat()
                    if ctx.get("pages_declared"):
                        st["pages_declared"] = ctx["pages_declared"]
                else:
                    nu0 = normalize_url(url)
                    visited.add(nu0)
                    try:
                        nxt0 = (next_from_json(payload, url) if mode_resp == "json"
                                else site_mod.parse_next(payload, url))
                    except Exception:
                        nxt0 = None
                        stop_reason = "pagination_parse_error"
                    if nxt0:
                        urls_done.add(nu0)
                        st["urls_done"] = sorted(urls_done)
                        st["next_url"] = nxt0
                        work.append((idx + 1, nxt0))
                    else:
                        st["next_url"] = url
                st["paginate_mode"] = paginate
                st["seen_keys"] = list(seen)
                st["out_file"] = out_file
                st["updated_at"] = now_iso()
                save_state(state_path, st)
                # A5：window 模式 —— 连续见过太多就提前停。
                # 位置很关键：必须放在 pages_ok += 1 和 save_state 之后，
                # 这样"这一页算处理完"already 成立，计数不会因为提前停而少一页。
                if coverage_mode() == "window":
                    _thr = int(CONFIG.get("refresh_stop_after_dups") or 15)
                    if window_consec_dup >= _thr:
                        stop_reason = "refresh_no_new"
                        log("  连续 %d 条都是已抓过的（阈值 %d）→ 提前停，不再翻页"
                            % (window_consec_dup, _thr))
                        break
                polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
                continue
            # ---- 详情阶段 ----
            # 现在只有一条路径：引擎通用流程 + 站点的 parse_detail。
            # 旧的"站点自己写 detail_hook"已在阶段1 删除（真站 40 条 × 13 字段零差异后
            # 才删的）。旧实现完整保存在 crawlers/_baseline_v1/code/，需要复现旧行为时
            # 直接跑那份快照里的 crawler.py 即可，不污染现在的代码。
            stop_after_page = False
            d_mode = resolve_detail_mode(args.detail_mode, site_mod) if rows else "off"

            if rows and d_mode == "generic":
                log("  进入详情页补字段（引擎通用流程，%d 条）..." % len(rows))
                try:
                    abort_reason, dcount = crawl_details_generic(
                        rows, sess, log, CONFIG, anomalies, site_mod.parse_detail)
                except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
                    # 闸门停止：**本页列表数据一个字都不丢**，没抓的详情标 skipped_budget
                    why = ("request_budget_exceeded" if isinstance(ge, RequestBudgetExceeded)
                           else "time_budget_exceeded")
                    pend = 0
                    for r0 in rows:
                        if not r0.get("detail_fetch"):
                            r0["detail_fetch"] = "skipped_budget"
                            r0["detail_error"] = "闸门停止（%s），下次补抓" % why
                            pend += 1
                    stat["detail_skipped_budget"] = stat.get("detail_skipped_budget", 0) + pend
                    log("!! 闸门在【详情】阶段停止：%s → 本页 %d 条详情标 skipped_budget，"
                        "列表数据照常写入" % (ge, pend))
                    anomalies.append({"page": page, "url": url,
                                      "reason": "闸门停止：%s（详情 %d 条挂起）" % (why, pend)})
                    # 先把本页已经解析好的列表数据落盘（一个字段都不丢），再收工。
                    # 断点**不**标记这一页完成 —— 下次续跑会重抓并由去重键过滤重复行，
                    # 详情则靠 detail_fetch=skipped_budget 被补抓流程接住。
                    _fa = now_iso()
                    for _r in rows:
                        _k = str(_r.get(CONFIG["dedup_key"], ""))
                        if _k and _k in seen:
                            stat["records_dup"] += 1
                            continue
                        _rec = dict(_r)
                        _rec.update({"source_url": url, "fetched_at": _fa,
                                     "http_status": code,
                                     "content_hash": content_hash_of(_r),
                                     "run_id": run_id})
                        fh.write(json.dumps(_rec, ensure_ascii=False) + "\n")
                        if _k:
                            seen.add(_k)
                        stat["records_new"] += 1
                    fh.flush()
                    os.fsync(fh.fileno())
                    log("   已保存本页 %d 条列表数据（不标断点，下次续跑会去重）" % len(rows))
                    ctx["gate_stage"] = "detail"
                    stop_reason = why
                    break
                except Exception as e:
                    log("!! 详情流程异常 %s: %s" % (type(e).__name__, e))
                    anomalies.append({"page": page, "url": url,
                                      "reason": "通用详情流程异常 %s" % type(e).__name__})
                    stat["pages_failed"] += 1
                    break

                # 计数并入 stat（报告里直接可见）
                for k, v in dcount.items():
                    if k == "detail_stop_reason":
                        stat["detail_stop_reason"] = v
                    elif k in ("detail_planned", "detail_attempted"):
                        # 这两个是"本页多少条"，多页累加没有意义
                        stat[k] = max(stat.get(k, 0), v)
                    else:
                        stat[k] = stat.get(k, 0) + v

                if abort_reason:
                    log("!! 详情阶段要求停止：%s" % abort_reason)
                    anomalies.append({"page": page, "url": url,
                                      "reason": "详情中止：%s" % abort_reason})
                    stat["pages_failed"] += 1
                    ctx["abort_reason"] = abort_reason
                    break

                if dcount.get("detail_stop_reason") == "detail_fail_ratio_exceeded":
                    # 熔断：本页数据仍然写下去（已抓的列表字段是有效信息，
                    # 缺详情的记录会明确标着 skipped_aborted），但之后不再继续。
                    ctx["detail_ratio_stopped"] = True
                    stop_after_page = True

            # ---- 附件阶段（阶段4）----
            # 放在写文件之前：附件结果直接写进记录，一次落盘。
            if rows and attach_cfg().get("enabled"):
                log("  处理附件（%d 条记录）..." % len(rows))
                try:
                    download_attachments(rows, sess, log, CONFIG, anomalies, stat,
                                         CONFIG.get("job"))
                except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
                    why = ("request_budget_exceeded" if isinstance(ge, RequestBudgetExceeded)
                           else "time_budget_exceeded")
                    pend = 0
                    for r0 in rows:
                        _al = r0.get("attachments") or []
                        _new = []
                        for a0 in _al:
                            if isinstance(a0, str):
                                # 还没开始下载时条目只是 URL 字符串 → 规范化成 dict 并标挂起
                                _new.append({"url": a0, "status": "skipped_budget",
                                             "bytes": 0, "sha256": "", "path": ""})
                                pend += 1
                            elif isinstance(a0, dict):
                                if a0.get("status") in (None, "", "pending"):
                                    a0["status"] = "skipped_budget"
                                    pend += 1
                                _new.append(a0)
                        if _al:
                            r0["attachments"] = _new
                    stat["attach_skipped_budget"] = stat.get("attach_skipped_budget", 0) + pend
                    log("!! 闸门在【附件】阶段停止：%s → %d 个附件标 skipped_budget，"
                        "记录与已下好的附件照常写入" % (ge, pend))
                    anomalies.append({"page": page, "url": url,
                                      "reason": "闸门停止：%s（附件 %d 个挂起）" % (why, pend)})
                    # 先把本页已经解析好的列表数据落盘（一个字段都不丢），再收工。
                    # 断点**不**标记这一页完成 —— 下次续跑会重抓并由去重键过滤重复行，
                    # 详情则靠 detail_fetch=skipped_budget 被补抓流程接住。
                    _fa = now_iso()
                    for _r in rows:
                        _k = str(_r.get(CONFIG["dedup_key"], ""))
                        if _k and _k in seen:
                            stat["records_dup"] += 1
                            continue
                        _rec = dict(_r)
                        _rec.update({"source_url": url, "fetched_at": _fa,
                                     "http_status": code,
                                     "content_hash": content_hash_of(_r),
                                     "run_id": run_id})
                        fh.write(json.dumps(_rec, ensure_ascii=False) + "\n")
                        if _k:
                            seen.add(_k)
                        stat["records_new"] += 1
                    fh.flush()
                    os.fsync(fh.fileno())
                    log("   已保存本页 %d 条列表数据（不标断点，下次续跑会去重）" % len(rows))
                    ctx["gate_stage"] = "attachment"
                    stop_reason = why
                    break
                except Exception as e:
                    log("!! 附件阶段异常 %s: %s" % (type(e).__name__, e))
                    stats_attach_error = stat.get("attach_stage_failed", 0) + 1
                    stat["attach_stage_failed"] = stats_attach_error
                    anomalies.append({"page": "attachment", "url": "",
                                      "reason": "附件阶段异常 %s: %s"
                                                % (type(e).__name__, str(e)[:80])})

            if not rows:
                # 空页先别当"真空"：有可能是整站被替换成了假页面（软封）。
                # 判据不是字节数阈值，而是"再打一次已知有结果的页面还空不空"。
                sb = soft_block_cfg()
                if sb.get("enabled") and sb.get("canary_url"):
                    if ctx.get("canary_cards") is None:
                        stat["canary_requests"] += 1
                        log("  空页 → 打一次 canary 对照：%s" % sb["canary_url"])
                        polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
                        try:
                            c_cards, c_bytes, c_skip = probe_canary(sess, log, sb, parse_list)
                        except (RequestBudgetExceeded, TimeBudgetExceeded) as ge:
                            # canary 只是判软封的旁证；闸门停了就"无法判定"，绝不让它冒泡成 traceback
                            log("!! 闸门在【canary】阶段停止：%s → 按无法判定处理" % ge)
                            anomalies.append({"page": page, "url": sb.get("canary_url", ""),
                                              "reason": "闸门停止：canary 未能执行"})
                            c_cards, c_bytes, c_skip = None, 0, "gate_stopped"
                            ctx["gate_stage"] = "canary"
                            stop_reason = ("request_budget_exceeded"
                                           if isinstance(ge, RequestBudgetExceeded)
                                           else "time_budget_exceeded")
                        ctx["canary_cards"] = -1 if c_cards is None else c_cards
                        ctx["canary_bytes"] = c_bytes
                        if c_skip:
                            ctx["canary_skip"] = c_skip
                            log("  canary 无法判定（%s）→ 按普通空页处理" % c_skip)
                        else:
                            log("  canary 结果：%s 张卡片（%s 字节）" % (c_cards, c_bytes))

                    if ctx.get("canary_cards") == 0:
                        # 本页空 + canary 也空 → 判定软封，立刻停手
                        stat["soft_block_detected"] = 1
                        # 这一页既不算成功也不算普通空页，单独计一项，
                        # 否则 pages_total=1 而 ok/empty/failed 全 0，报告自相矛盾。
                        stat["pages_soft_blocked"] = 1
                        page_bytes = int(page_meta.get("bytes") or 0)
                        hit_markers = []
                        try:
                            if payload and any(m in str(payload) for m in sb.get("markers") or []):
                                hit_markers = [m for m in sb.get("markers") or [] if m in str(payload)]
                        except Exception:
                            pass
                        ev = {"page_url": url, "resp_bytes": page_bytes, "cards": 0,
                              "canary_url": sb["canary_url"],
                              "canary_bytes": ctx.get("canary_bytes", 0),
                              "canary_cards": ctx.get("canary_cards"),
                              "server": page_meta.get("server", ""),
                              "cf_ray": page_meta.get("cf_ray", ""),
                              "markers": hit_markers}
                        anomalies.append({"page": page, "url": url,
                                          "reason": "判定软封（软封页与 canary 都是 0 卡片）",
                                          "evidence": ev})
                        log("!! 空页 + canary 也空 → 判定为软封，立即停止（不再发任何页面请求）")
                        try:
                            old = load_cooldown(cd_key, log) or {}
                            strikes = int(old.get("strikes") or 0) + 1
                            cd_data, sec = save_cooldown(cd_key, "soft_block_suspected",
                                                         strikes, ev)
                            log("!! 已写冷却文件：%s（%d 秒，第 %d 次）"
                                % (cooldown_path(cd_key), sec, strikes))
                        except Exception as e:
                            log("!! 冷却文件写入失败 %s: %s" % (type(e).__name__, e))
                        # 局部变量也要写：后面 `ctx["stop_reason"] = stop_reason`
                        # 会用局部值覆盖 ctx，只写 ctx 的话报告里就变回空字符串。
                        stop_reason = "soft_block_suspected"
                        ctx["stop_reason"] = stop_reason
                        soft_blocked = True
                        break

                stat["pages_empty"] += 1
                consecutive_empty += 1
                anomalies.append({"page": page, "url": url,
                                  "reason": "解析出 0 条（空页或选择器不匹配）"})

                if paginate == "next":
                    # 空页 ≠ 翻页结束。下一页链接还在这份 HTML 里，必须读出来：
                    # 直接 continue 会在"后续还有好几页"的时候静默收工。
                    nu = normalize_url(url)
                    try:
                        # JSON 模式由引擎从响应里取下一页（next_path / cursor_path）
                        nxt = (next_from_json(payload, url) if mode_resp == "json"
                               else site_mod.parse_next(payload, url))
                    except Exception as e:
                        log("!! parse_next 异常 %s: %s" % (type(e).__name__, e))
                        anomalies.append({"page": page, "url": url,
                                          "reason": "parse_next 异常 %s: %s"
                                                    % (type(e).__name__, str(e)[:80])})
                        stop_reason = "pagination_parse_error"
                        # 不标记完成；next_url 指回这一页 → 下次重试
                        st["next_url"] = url
                        st["paginate_mode"] = paginate
                        st["out_file"] = out_file
                        st["updated_at"] = now_iso()
                        save_state(state_path, st)
                        log("  这一页的翻页信息没拿到 → 下次从这里重试（不标记完成）")
                        break

                    visited.add(nu)
                    st["paginate_mode"] = paginate
                    st["seen_keys"] = list(seen)
                    st["out_file"] = out_file
                    st["updated_at"] = now_iso()

                    if nxt:
                        # 有下一页：这一页的翻页信息是完整的，可以记完成
                        urls_done.add(nu)
                        st["urls_done"] = sorted(urls_done)
                        log("  这一页 0 条，但有下一页 → 继续翻（异常已记入报告）")
                        st["next_url"] = nxt
                        save_state(state_path, st)
                        work.append((idx + 1, nxt))
                        polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
                        continue

                    # 空页 + 没有下一页：这次判失败，但【不能标记完成】，
                    # 否则下次运行会从 first_url 起步、发现它在 urls_done 里 → 直接 noop，
                    # 把"这一页是空的"这个异常永久固化成"抓完了"。
                    log("  这一页 0 条，也没有下一页 → 本次判异常；下次仍会重试这一页")
                    st["next_url"] = url
                    save_state(state_path, st)
                    stop_reason = "pagination_empty_at_page_%d" % idx
                    break

                if args.allow_empty:
                    log("  解析出 0 条（--allow-empty 已指定，按完成处理）")
                else:
                    log("  解析出 0 条 → 【不标记为完成】。选择器可能写错了；"
                        "确认这一页本来就是空的才能用 --allow-empty。")
                    if consecutive_empty >= 3:
                        log("连续 %d 页解析出 0 条 → 选择器大概率写错，中止。"
                            "（避免把整站标记成已完成、造成静默丢数据）" % consecutive_empty)
                        stat["pages_failed"] += 1
                        break
                    polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
                    continue
            else:
                consecutive_empty = 0

            # 记录字段签名与每页条数（供采集报告使用）
            # 必须用 extend，不能 `field_list = sorted(...)`：
            # 重新赋值会让局部变量指向新列表，而 ctx 里存的还是最初那个空列表，
            # 报告就永远是 field_count=0。
            # 字段签名 = 已有（含从数据文件恢复的）+ 本页所有行的字段，取并集。
            # 这样：可选字段不漏、二跑/全跳过也不会变成空。
            keys_union = set(field_list)
            for r0 in rows:
                keys_union.update(r0.keys())
            if keys_union != set(field_list):
                field_list[:] = sorted(keys_union)
            per_page[page] = len(rows)

            fetched_at = now_iso()
            new_this_page = 0
            for row in rows:
                key = str(row.get(CONFIG["dedup_key"], ""))
                if key and key in seen:
                    stat["records_dup"] += 1
                    continue

                content_hash = content_hash_of(row)

                rec = dict(row)
                rec.update({
                    "source_url": url,
                    "fetched_at": fetched_at,
                    "http_status": code,
                    "content_hash": content_hash,
                    "run_id": run_id,
                })
                rec = reanchor_and_guard(rec, anomalies, _GUARD_SEEN)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if key:
                    seen.add(key)
                new_this_page += 1
                stat["records_new"] += 1

            fh.flush()
            os.fsync(fh.fileno())

            stat["pages_ok"] += 1

            if paginate == "number":
                # 超出站点声明总页数的页不记断点。
                # 那些页返回的是"最后一页"的重复内容；一旦 M 变大（站点新增数据），
                # 同一页码会变成**新内容**，若断点里记着"已完成"就会漏抓。
                # 代价：下一次续跑会重发 1 个请求来确认 M —— 这个代价换"不漏数据"值得。
                _over_M = (ctx.get("pages_declared")
                           and beyond_declared(page, ctx.get("pages_declared")))
                if _over_M:
                    log("第 %d 页超出站点声明的 %d 页 → 不记断点（下次会重试确认）"
                        % (page, ctx["pages_declared"]))
                else:
                    pages_done.add(page)
                    st["pages_done"] = sorted(pages_done)
                    if coverage_mode() == "window":
                        st.setdefault("pages_done_at", {})[str(page)] = date.today().isoformat()
                if ctx.get("pages_declared"):
                    st["pages_declared"] = ctx["pages_declared"]
            else:
                nu = normalize_url(url)
                visited.add(nu)
                # 关键：先不要把这页记成"已完成"。要等 parse_next 成功，
                # 才算"这一页的翻页信息拿到了"。否则解析器一出错，
                # urls_done 就把这页盖成已完成、next_url 又被清空 →
                # 下次运行从头开始、发现起始页已在 urls_done 里 → 直接 noop，
                # 等于把"中断"永久固化成"抓完了"。
                marked_done = True
                try:
                    nxt = (next_from_json(payload, url) if mode_resp == "json"
                           else site_mod.parse_next(payload, url))
                except Exception as e:
                    # 解析器坏了 ≠ 没有下一页。当成 no_next 会把"抓取中断"报成"正常抓完"，
                    # 这正是最该避免的静默失败，所以单独给一个 stop_reason 并算 partial。
                    log("!! parse_next 异常 %s: %s" % (type(e).__name__, e))
                    anomalies.append({"page": page, "url": url,
                                      "reason": "parse_next 异常 %s: %s"
                                                % (type(e).__name__, str(e)[:80])})
                    nxt = None
                    stop_reason = "pagination_parse_error"
                    # 回滚：这一页不进 urls_done，并把 next_url 指回自己 →
                    # 下次运行会重新抓这一页、重新尝试解析下一页
                    marked_done = False
                    st["next_url"] = url
                    log("  这一页的翻页信息没拿到 → 下次从这里重试（不标记完成）")

                if marked_done:
                    urls_done.add(nu)
                    if nxt:
                        st["next_url"] = nxt
                        work.append((idx + 1, nxt))
                    else:
                        st["next_url"] = None
                        stop_reason = stop_reason or "no_next"
                st["urls_done"] = sorted(urls_done)

            st["paginate_mode"] = paginate
            st["seen_keys"] = list(seen)
            st["out_file"] = out_file
            st["updated_at"] = now_iso()
            save_state(state_path, st)

            log("  本页 %d 条，新增 %d 条，累计新增 %d 条"
                % (len(rows), new_this_page, stat["records_new"]))
            if paginate == "next":
                log("  下一页：%s" % (st.get("next_url") or "（没有）"))

            if stop_after_page:
                log("熔断：详情失败率超过阈值 → 本次运行到此停止（本页数据已写入）")
                break

            polite_sleep(CONFIG["delay_min"], CONFIG["delay_max"])
    finally:
        fh.close()

    ctx["stop_reason"] = stop_reason
    if stop_reason:
        log("翻页停止原因：%s" % stop_reason)

    # ---- 这一轮有没有把"整个结果集"抓完？ ----
    # 只有抓完了，json.total_scope="global" 的自报总数才有资格拿来比对：
    #   * next/cursor：只有 stop_reason == "no_next" 才算真的到底
    #   * 数字分页  ：除非站点显式声明总页数（CONFIG["total_pages"]），否则一律不认，
    #                 因为 --pages 1 只抓一页时"配置范围"抓完了，不代表站点抓完了
    complete_set = False
    if paginate == "next":
        complete_set = (stop_reason == "no_next")
    else:
        declared = CONFIG.get("total_pages")
        if declared:
            want = set(range(1, int(declared) + 1))
            covered = set(pages_done) | set(per_page.keys())
            complete_set = (want <= covered
                            and stat.get("pages_failed", 0) == 0
                            and stat.get("pages_blocked", 0) == 0
                            and stat.get("pages_empty", 0) == 0)
    ctx["complete_set"] = complete_set
    if response_mode() == "json":
        log("结果集是否抓完：%s（total_scope=%s）"
            % ("是" if complete_set else "否",
               (json_cfg().get("total_scope") or "global")))

    elapsed = time.time() - t_start
    log("-" * 62)
    log("页数  总 %d / 成功 %d / 跳过(已完成) %d / robots拒绝 %d / 空页 %d / 失败 %d"
        % (stat["pages_total"], stat["pages_ok"], stat["pages_skipped"],
           stat["pages_blocked"], stat["pages_empty"], stat["pages_failed"]))
    log("记录  新增 %d / 重复丢弃 %d" % (stat["records_new"], stat["records_dup"]))
    log("耗时  %.1f 秒（平均 %.2f 秒/页）"
        % (elapsed, elapsed / max(1, stat["pages_ok"])))
    log("输出  %s（%.1f KB）"
        % (out_file, os.path.getsize(out_file) / 1024 if os.path.exists(out_file) else 0))

    # 数据文件最终条数（报告里要区分"本次新增"和"总计"）
    # 顺带统计"还有多少条详情没抓全"——这是下次能不能补上的依据，
    # 也是报告里必须出现的数字（不能只说 partial 就完事）。
    abort_on = set(detail_cfg().get("abort_on") or [])
    detail_on = bool(detail_cfg().get("enabled"))
    pending_after = 0
    ctx["total_in_file"] = 0
    try:
        with open(out_file, "r", encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                ctx["total_in_file"] += 1
                rec = json.loads(ln)
                # 站点启用了详情时，"没有 detail_fetch 字段"也算待补抓
                if detail_retryable(rec.get("detail_fetch"), abort_on,
                                    missing_is_pending=detail_on):
                    pending_after += 1
    except Exception:
        ctx["total_in_file"] = 0
    stat["detail_pending_after_run"] = pending_after
    if pending_after:
        log("详情  还有 %d 条没抓全（下次运行会自动补抓，只补这些，不重抓列表页）"
            % pending_after)
    log("数据  运行前 %d 条 → 现在 %d 条（本次新增 %d，重复丢弃 %d）"
        % (ctx["records_before"], ctx["total_in_file"],
           stat["records_new"], stat["records_dup"]))

    if ctx.get("abort_reason"):
        return finalize("failed", ctx["abort_reason"], 4)

    # 详情失败率熔断：页面是抓到了，但详情大面积失败，数据不完整。
    # 这就是 codex 指出的那个口径 —— 不能因为"页面成功了"就报 success。
    if ctx.get("detail_ratio_stopped"):
        return finalize("partial", "detail_fail_ratio_exceeded", 3)

    # 闸门停止优先级最高：它是**根因**，pending 只是后果。
    # 不这么排的话，报告会写成 detail_pending_remains，看不出是被预算截断的。
    if ctx.get("gate_stage") in ("page", "detail", "attachment", "canary",
                                 "repair_details", "repair_attachments"):
        _why = ("time_budget_exceeded"
                if (gate_mod.current_gate() and
                    gate_mod.current_gate().stopped_by == "time_budget")
                else "request_budget_exceeded")
        # 有没有**拿到数据**才决定 partial/failed：闸门在详情阶段停时，
        # pages_ok 可能还是 0（这一页没标完成），但列表数据已经落盘了 → 算 partial。
        _has_data = (int(stat.get("records_new", 0) or 0) > 0
                     or int(ctx.get("total_in_file", 0) or 0) > 0)
        return finalize("partial" if _has_data else "failed", _why, 3 if _has_data else 4)

    # 详情没抓全 → 这一轮不能算完成。
    # 放在 success 之前：不能因为"列表页都成功了"就把残缺数据报成功。
    # 下次运行会自动补抓（只补这些，不重抓列表页）。
    if pending_after > 0:
        return finalize("partial", "detail_pending_remains", 3)

    # ---- 退出状态判定 ----
    # 不能只看 abort_reason：页面全失败但没触发 abort（比如一直 500、一直超时）
    # 时，报告也不能写 success。
    pages_total = stat.get("pages_total", 0)
    pages_ok = stat.get("pages_ok", 0)
    pages_failed = stat.get("pages_failed", 0)
    pages_blocked = stat.get("pages_blocked", 0)
    pages_skipped = stat.get("pages_skipped", 0)
    detail_failed = stat.get("detail_failed", 0)

    # 翻页异常（循环 / 到达上限 / 断链）：说明"后面的页没抓到"，不能报 success
    # 软封单独走后面的分支（rc=6），不要被这个通用的"翻页异常 rc=4"抢先吃掉。
    # refresh_no_new 是 window 模式的正常收工（这轮没新数据），不是翻页异常。
    # 放进白名单，让它走后面的"正常收尾"分支（success）。
    if stop_reason and stop_reason not in ("no_next", "", "soft_block_suspected",
                                           "refresh_no_new"):
        if pages_ok > 0:
            log("翻页异常（%s）→ 判为 partial" % stop_reason)
            return finalize("partial", stop_reason, 3)
        log("翻页异常（%s）且 0 页成功 → 判为 failed" % stop_reason)
        return finalize("failed", stop_reason, 4)

    # 空页：出现过空页（且没加 --allow-empty）就不能报 success。
    # 空页通常意味着选择器失效或页面结构变了，数据很可能是残缺的。
    if stat.get("pages_empty", 0) > 0 and not getattr(args, "allow_empty", False):
        log("注意：本次出现 %d 个空页 → 判为 partial（空页不等于抓完了）"
            % stat["pages_empty"])
        return finalize("partial", "empty_page_seen", 3)

    # 接口条目里有非对象：有数据被跳过，不能报 success。
    # 这条放在"总数对不上"之前：条目无效更能解释"为什么少了几条"，报得更具体。
    if stat.get("invalid_items", 0) > 0:
        log("注意：接口里有 %d 个条目不是对象、已被跳过 → 判为 partial"
            % stat["invalid_items"])
        return finalize("partial", "invalid_items_skipped", 3)

    # 接口自报总数对不上：只在本轮"确实把整个结果集抓完"时才判定。
    # 否则用户只抓 1~3 页、增量续跑、被 max_pages 截断时，total 本来就该比文件里的多，
    # 拿它比就会天天误报 partial。
    scope = (json_cfg().get("total_scope") or "global").lower()
    stat["json_total_scope"] = scope
    rep_total = stat.get("json_total_first_page")
    complete_set = ctx.get("complete_set", False)
    stat["json_total_complete_set"] = complete_set
    if scope == "global" and complete_set and rep_total is not None \
            and ctx.get("total_in_file", 0) < rep_total:
        log("注意：接口自报总数 %d 条，但数据文件里只有 %d 条 → 可能少抓了"
            % (rep_total, ctx.get("total_in_file", 0)))
        return finalize("partial", "json_total_mismatch", 3)

    # 去重键为空：数据写进去了，但去重形同失效，必须显式提示，不能报 success
    if stat.get("dedup_key_empty", 0) > 0:
        log("注意：有 %d 条记录的去重键为空 → 判为 partial（去重可能失效）"
            % stat["dedup_key_empty"])
        return finalize("partial", "dedup_key_empty", 3)

    if soft_blocked or stat.get("soft_block_detected"):
        log("!! 本次判定为软封 → failed / soft_block_suspected")
        return finalize("failed", "soft_block_suspected", 6)

    # 覆盖率：已抓到数据的页数 / 页面声明的总页数
    _M = ctx.get("pages_declared")
    if _M:
        # 口径：已完成的页数 / 站点声明总页数（不是"有数据的页数"）。
        # 续跑第二跑 pages_ok=0（全被跳过），但那不代表没覆盖。
        _done = len(pages_done) if paginate == "number" else len(urls_done)
        ctx["coverage"] = round(min(1.0, float(_done) / float(_M)), 3)
    else:
        ctx["coverage"] = None

    # 被"页面声明的总页数"夹紧 → 说明这次没抓完整个结果集。
    # 显式给了 --pages 时这是用户自己要的（按 success 报，但报告里 coverage 会说话）；
    # 没给 --pages 就是配置页数拍大了，必须报 partial，不能假装抓完。
    if ctx.get("truncated"):
        if getattr(args, "pages", None) is not None:
            log("注意：本次只覆盖 %s（声明 %s 页，--pages 限定了 %s 页）"
                % (ctx.get("coverage"), _M, getattr(args, "pages", None)))
        elif coverage_mode() == "window":
            log("注意：window 模式（只维护最近窗口）→ 覆盖 %s / 声明 %s 页，按正常收工"
                % (ctx.get("coverage"), _M))
        else:
            log("注意：计划页数 %s 小于站点声明的 %s 页 → 判为 partial（没抓完整个结果集）"
                % (ctx.get("pages_planned"), _M))
            return finalize("partial", "page_range_truncated", 3)

    # 附件有失败：数据拿到了，但文件没下全，不能报 success
    att_bad_keys = ("attach_too_many", "attach_too_large", "attach_quota",
                    "attach_dns_failed",
                    "attach_robots_denied", "attach_robots_check_failed",
                    "attach_type_rejected", "attach_private_host",
                    "attach_bad_scheme", "attach_denied_ext", "attach_download_failed",
                    "attach_stage_failed")
    att_bad = sum(stat.get(k, 0) for k in att_bad_keys)
    if att_bad > 0:
        log("注意：附件有 %d 个没下成（详情见报告 anomalies）→ 判为 partial" % att_bad)
        return finalize("partial", "attachment_partial", 3)

    if pages_ok > 0 and pages_failed == 0 and detail_failed == 0:
        # 正常收工。只有 window 的"这轮没新数据"需要把 reason 带出来，
        # 其他情况保持 "ok" 不变（避免影响既有断言）。
        return finalize("success", "refresh_no_new" if stop_reason == "refresh_no_new" else "ok", 0)

    if pages_ok > 0 and (pages_failed > 0 or detail_failed > 0):
        log("注意：页面 %d 成功 / %d 失败，详情失败 %d 条 → 判为 partial"
            % (pages_ok, pages_failed, detail_failed))
        return finalize("partial", "some_items_failed", 3)

    if pages_failed > 0 and pages_ok == 0:
        log("注意：0 页成功 / %d 页失败 → 判为 failed" % pages_failed)
        return finalize("failed", "all_pages_failed", 4)

    if pages_blocked > 0:
        return finalize("failed", "all_pages_blocked_by_robots", 4)

    if pages_skipped > 0:
        # 页面都抓过了，但这一轮补上了之前失败的详情 → 这是"修好了"，不是"什么都没做"
        if stat.get("detail_repaired_ok", 0) > 0:
            log("所有页面之前已完成；本轮补抓成功 %d 条详情 → 判为 success"
                % stat["detail_repaired_ok"])
            return finalize("success", "details_repaired", 0)
        return finalize("noop", "all_pages_already_done", 0)

    return finalize("noop", "nothing_done", 0)


if __name__ == "__main__":
    sys.exit(main())