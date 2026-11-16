#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""robots.txt 判定（RFC 9309）。

修掉标准库 urllib.robotparser 的两个缺陷：
    1. 不认 `*` 和 `$` 通配符（`Disallow: /job/*` 会被当成字面前缀，永不命中）
    2. 按书写顺序取第一条命中，而不是"最长匹配优先"

对外只用 decide()：
    decide(text, ua, url) -> (allowed: bool, rule: str, line_no: int)

    allowed  True/False
    rule     命中的规则原文（如 'Disallow: /job/*'），没有命中时为空串
    line_no  规则在 robots.txt 里的行号（1 起），用于回溯
"""
import math
import re
from urllib.parse import urlsplit

__all__ = ["parse_groups", "pick_rules", "match_path", "decide", "classify_robots"]


def _strip(line):
    """去掉行内注释并 strip。"""
    return line.split("#", 1)[0].strip()


def parse_groups(text):
    """解析成 [(ua_tokens, rules, crawl_delay)]。

    rules = [(allow:bool, pattern:str, lineno:int)]
    crawl_delay = float 或 None（该组的 Crawl-delay）

    连续多个 User-agent 行共享后续规则；遇到第一条非 User-agent 指令后，
    再出现 User-agent 就说明是新的一组。
    """
    groups = []
    cur_uas, cur_rules, in_rules = [], [], False
    cur_delay = None
    for idx, raw in enumerate((text or "").splitlines(), 1):
        line = _strip(raw)
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "user-agent":
            if in_rules:
                if cur_uas:
                    groups.append((cur_uas, cur_rules, cur_delay))
                cur_uas, cur_rules, cur_delay, in_rules = [], [], None, False
            if val:
                cur_uas.append(val.lower())
        elif key in ("allow", "disallow"):
            if not cur_uas:
                continue            # 规则出现在任何 User-agent 之前 → 忽略
            in_rules = True
            cur_rules.append((key == "allow", val, idx))
        elif key == "crawl-delay":
            if cur_uas:
                in_rules = True
                try:
                    v = float(val)
                    # inf / nan / 负数都不接受：inf 会让 time.sleep 抛异常或永久挂起
                    if math.isfinite(v) and v >= 0:
                        cur_delay = v
                except ValueError:
                    pass
        # 其他指令（sitemap 等）忽略
    if cur_uas:
        groups.append((cur_uas, cur_rules, cur_delay))
    return groups


def pick_rules(groups, ua):
    """选出适用于本 UA 的规则：`*` 组 + token 命中组，取最具体（token 最长）的那层。

    同长度时合并（RFC 允许多组共享规则）。
    返回 (rules, crawl_delay)
    """
    ua_l = (ua or "").lower()
    cand = []
    for tokens, rules, delay in groups:
        score = -1
        for t in tokens:
            if t == "*":
                score = max(score, 0)
            elif t and t in ua_l:
                score = max(score, len(t))
        if score >= 0:
            cand.append((score, rules, delay))
    if not cand:
        return [], None
    top = max(s for s, _, _ in cand)
    out, delays = [], []
    for s, rules, delay in cand:
        if s == top:
            out.extend(rules)
            if delay is not None:
                delays.append(delay)
    return out, (max(delays) if delays else None)


def _compile(pattern):
    """把 robots 规则编译成正则。`*` = 任意长度，末尾 `$` = 锚定结尾。"""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    parts = []
    for ch in body:
        parts.append(".*" if ch == "*" else re.escape(ch))
    return re.compile("^" + "".join(parts) + ("$" if anchored else ""))


def match_path(rules, path):
    """在规则里找最长匹配。返回 (allowed, rule_str, lineno)。

    RFC 9309：
      - 多条命中取**最长**的规则
      - 长度相同 → **Allow 优先**
      - 没有任何规则命中 → 允许
    """
    best_len, best_allow, best_rule, best_line = -1, None, "", 0
    for allow, pattern, lineno in rules:
        if pattern == "":
            continue                      # `Disallow:` 空值 = 不限制
        try:
            if not _compile(pattern).match(path):
                continue
        except re.error:
            continue
        length = len(pattern)
        if length > best_len or (length == best_len and allow and not best_allow):
            best_len, best_allow = length, allow
            best_rule = ("Allow: " if allow else "Disallow: ") + pattern
            best_line = lineno
    if best_allow is None:
        return True, "", 0
    return best_allow, best_rule, best_line


def decide(text, ua, url):
    """对外唯一入口。url 只看 path + query（不含 scheme/host）。"""
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    rules, _delay = pick_rules(parse_groups(text), ua)
    return match_path(rules, path)


def crawl_delay(text, ua):
    """适用于本 UA 的 Crawl-delay（秒）；没有规则时返回 None。"""
    _rules, delay = pick_rules(parse_groups(text), ua)
    return delay

# ---------------------------------------------------------------- 响应形态判定
# 2026-11-15：修「把 WAF/HTML 页面当成零规则 robots」的 fail-open。
# 判据只看长相，不看体积 —— 项目语料里存在 552 字节的 HTML robots，
# 用「>10KB 才算异常」的阈值会漏掉它们。
_HTML_STARTS = ("<!doctype", "<html", "<head", "<body", "<meta", "<script", "<?xml")


def classify_robots(status_code, content_type, text, probe_bytes=2048):
    """一次 /robots.txt 响应是什么性质（四态）。

      absent      404 —— 没有文件 = 未设限（放行）
      denied      401/403/5xx/其它非 200 —— 拒绝
      unparsable  200 但内容是 HTML/挑战页 —— 无法确认限制（fail-closed）
      ok          200 且内容像 robots（含空文件 / 纯注释）

    probe_bytes 只是取前缀的长度，不是"体积阈值"。
    """
    if status_code == 404:
        return "absent"
    if status_code != 200:
        return "denied"
    ct = (content_type or "").lower()
    body = (text or "").lstrip("\ufeff \r\n\t")
    head = body[:probe_bytes].lower()
    if head.startswith(_HTML_STARTS):
        return "unparsable"
    # 有些服务器把 robots.txt 也标成 text/html（实测有），只要正文像 robots 就认。
    if "text/html" in ct and not _looks_like_robots(body):
        return "unparsable"
    return "ok"


def _looks_like_robots(text):
    """正文里有没有一行是 robots 指令（不看 Content-Type）。"""
    for line in (text or "").splitlines():
        s = line.split("#", 1)[0].strip().lower()
        if s.startswith(("user-agent:", "disallow:", "allow:", "sitemap:", "crawl-delay:")):
            return True
    return False
