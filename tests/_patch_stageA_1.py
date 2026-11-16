# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""阶段A 施工：Retry-After / canary 软封 / 全局冷却 / Referer + 响应指标。

一次性 patch，每处替换都带断言，宁可中途炸掉也不留下半截代码。
"""
import sys
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")
orig = s

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处的：" + why
    s = s.replace(old, new, 1)

# ---------------------------------------------------------------- 1) 新基础设施
INFRA = '''

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
        text = resp.text or ""
        _LAST_META["bytes"] = len(text.encode("utf-8", errors="ignore"))
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


def cooldown_path(host):
    """
    冷却文件路径。**必须**从 state_dir 派生：
    测试用 CRAWLER_STATE_DIR 隔离，写死全局目录会污染真实运行目录。
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", host or "unknown")
    return os.path.join(CONFIG["state_dir"], "_cooldown_%s.json" % safe)


def load_cooldown(host):
    p = cooldown_path(host)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


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
'''

anchor = "\n\ndef detail_cfg():"
sub(anchor, INFRA + anchor, "插入基础设施块")

# ---------------------------------------------------------------- 2) _fetch_core
sub('''def _fetch_core(sess, url, log, retries, timeout, backoff, tag=""):''',
    '''def _fetch_core(sess, url, log, retries, timeout, backoff, tag="", referer=None):''',
    "_fetch_core 签名加 referer")

sub('''    pre = ("[%s] " % tag) if tag else ""
    for attempt in range(1, retries + 1):
        try:
            r = sess.get(url, timeout=timeout)
            code = r.status_code

            if code == 200:''',
    '''    pre = ("[%s] " % tag) if tag else ""
    hdr = {"Referer": referer} if referer else None
    for attempt in range(1, retries + 1):
        try:
            r = sess.get(url, timeout=timeout, headers=hdr, allow_redirects=True)
            code = r.status_code
            _note_resp(r, referer)

            if code == 200:''',
    "_fetch_core 加 Referer 与响应记录")

sub('''            if code in (429, 503):
                wait = backoff ** attempt * 3
                log("  %sHTTP %s 被限速判定 → 等 %.1f 秒（第 %d/%d 次）"
                    % (pre, code, wait, attempt, retries))
                time.sleep(wait)
                continue''',
    '''            if code in (429, 503):
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
                continue''',
    "_fetch_core 读 Retry-After")

# ---------------------------------------------------------------- 3) fetch / fetch_page
sub('''def fetch(sess, url, log):
    """列表页用的 GET：沿用 CONFIG 里的重试/超时/退避。"""
    return _fetch_core(sess, url, log,
                       CONFIG["retries"], CONFIG["timeout"], CONFIG["backoff"])''',
    '''def fetch(sess, url, log, referer=None):
    """列表页用的 GET：沿用 CONFIG 里的重试/超时/退避。referer 按页传。"""
    return _fetch_core(sess, url, log,
                       CONFIG["retries"], CONFIG["timeout"], CONFIG["backoff"],
                       referer=referer)''',
    "fetch 透传 referer")

sub('''def fetch_page(sess, url, log, page=None):''',
    '''def fetch_page(sess, url, log, page=None, referer=None):''',
    "fetch_page 签名加 referer")

sub('''    if response_mode() != "json":
        return fetch(sess, url, log)''',
    '''    if response_mode() != "json":
        return fetch(sess, url, log, referer=referer)''',
    "html 分支透传 referer")

sub('''    headers = dict(jc.get("headers") or {})''',
    '''    headers = dict(jc.get("headers") or {})
    if referer:
        headers.setdefault("Referer", referer)''',
    "json 分支加 Referer")

sub('''            code = r.status_code

            if code == 200:
                try:
                    return code, r.json()''',
    '''            code = r.status_code
            _note_resp(r, referer)

            if code == 200:
                try:
                    return code, r.json()''',
    "json 分支记录响应")

P.write_text(s, encoding="utf-8", newline="\n")
print("第一批完成，行数 %d → %d" % (len(orig.splitlines()), len(s.splitlines())))