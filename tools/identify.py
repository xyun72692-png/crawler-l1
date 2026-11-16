#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v13.2 通道判定器：给一个 URL（或已存 HTML），输出判定卡片。

设计原则（对照《指令-v13.2》）：
  · 判据全部放在 tools/channels/*.json —— 本文件里**没有任何域名、没有任何站点名**
  · 只负责"匹配规则"，不负责"抓数据"
  · 短路 + 预算：能离线就离线；单站最多 2 个请求（robots + 首页）

用法：
    python tools/identify.py https://example.tld/path --html data\\raw\\fixtures\\x.html
    python tools/identify.py --batch tests\\data\\acceptance_15.json --out out\\identify_cards.json
    python tools/identify.py <url> --no-network          # 只判已有证据，不发请求
"""

import argparse
import json
import re
import sys
from pathlib import Path

CHANNEL_DIR = Path(__file__).resolve().parent / "channels"
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）
DEFAULT_UA = UA  # 由 identity 决定，勿在此写版本号
MAX_REQUESTS_PER_SITE = 2


# --------------------------------------------------------------------------- #
# 证据容器
# --------------------------------------------------------------------------- #
class Probe:
    """一个站点在判定时刻已知的全部证据。"""

    def __init__(self, url, html=None, robots_text=None, home_html=None,
                 allow_network=True, timeout=15, max_requests=MAX_REQUESTS_PER_SITE):
        self.url = url
        self.allow_network = allow_network
        self.timeout = timeout
        self.requests_made = 0
        self.max_requests = int(max_requests)
        self._session = None

        self.html, self.encoding = (html, "given") if html is not None else (None, None)
        self.robots_text = robots_text
        self.home_html = home_html if home_html is not None else (
            html if html is not None else None)
        self.title = None
        self._refresh_title()

    # -- 派生量 ---------------------------------------------------------- #
    def _refresh_title(self):
        if self.html:
            m = re.search(r"<title[^>]*>(.*?)</title>", self.html, re.S | re.I)
            self.title = m.group(1).strip() if m else ""

    @property
    def size(self):
        return len(self.html.encode("utf-8", errors="ignore")) if self.html else 0

    @property
    def visible_text_len(self):
        if not self.html:
            return 0
        t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", self.html)
        t = re.sub(r"(?s)<[^>]+>", " ", t)
        t = re.sub(r"&[a-z#0-9]+;", " ", t)
        return len(re.sub(r"\s+", "", t))

    # -- 取数（受预算约束） ----------------------------------------------- #
    def _sess(self):
        if self._session is None:
            import requests
            s = requests.Session()
            s.headers.update({"User-Agent": DEFAULT_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
            self._session = s
        return self._session

    def _decode(self, raw):
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                return raw.decode(enc), enc
            except Exception:
                continue
        return raw.decode("utf-8", errors="replace"), "utf-8?"

    def fetch(self, what):
        """what = 'robots' | 'home'；超预算/不允许联网时返回 False。"""
        if not self.allow_network or self.requests_made >= self.max_requests:
            return False
        base = self.url.split("?")[0]
        if what == "robots":
            from urllib.parse import urlsplit
            u = urlsplit(base)
            target = "%s://%s/robots.txt" % (u.scheme or "https", u.netloc)
        else:
            parts = base.split("/")
            target = "/".join(parts[:3]) + "/"
        try:
            r = self._sess().get(target, timeout=self.timeout, allow_redirects=True)
            self.requests_made += 1
            text, enc = self._decode(r.content)
        except Exception:
            self.requests_made += 1
            return False
        if what == "robots":
            self.robots_text = text
        else:
            self.html = text
            self.encoding = enc
            if self.home_html is None:
                self.home_html = text
            self._refresh_title()
        return True


# --------------------------------------------------------------------------- #
# 规则匹配原语（只认 JSON 里出现的键，不认识任何站点）
# --------------------------------------------------------------------------- #
def _ev(token, probe):
    """把一个检测项变成 (是否命中, 可读证据)；支持嵌套 all/any。"""
    if "all" in token or "any" in token:
        return rule_hits(token, probe)
    if "html_contains" in token:
        sub = token["html_contains"]
        hit = bool(probe.html) and sub.lower() in probe.html.lower()
        return hit, "html 含 %r" % sub
    if "html_regex" in token:
        rx = token["html_regex"]
        n = len(re.findall(rx, probe.html or "", re.I))
        return n > 0, "html 命中 /%s/ ×%d" % (rx, n)
    if "title_contains" in token:
        sub = token["title_contains"]
        hit = bool(probe.title) and sub in probe.title
        return hit, "title 含 %r（实际 %r）" % (sub, (probe.title or "")[:40])
    if "url_regex" in token:
        rx = token["url_regex"]
        hit = bool(re.search(rx, probe.url, re.I))
        return hit, "url 匹配 /%s/" % rx
    if "size_lt" in token:
        v = token["size_lt"]
        if probe.html is None:                   # 没取到页面 ≠ 空壳
            return False, "未取到页面（不判尺寸）"
        return probe.size < v, "页面 %d B < %d" % (probe.size, v)
    if "size_gt" in token:
        v = token["size_gt"]
        return probe.size > v, "页面 %d B > %d" % (probe.size, v)
    if "visible_text_lt" in token:
        v = token["visible_text_lt"]
        if probe.html is None:
            return False, "未取到页面（不判正文长度）"
        return probe.visible_text_len < v, "可见正文 %d 字 < %d" % (probe.visible_text_len, v)
    if "count_regex_min" in token:
        spec = token["count_regex_min"]
        n = len(re.findall(spec["regex"], probe.html or ""))
        return n >= spec["min"], "%s 命中 %d 次（≥%d）" % (spec["regex"], n, spec["min"])
    if "robots_contains" in token:
        sub = token["robots_contains"]
        hit = bool(probe.robots_text) and sub.lower() in probe.robots_text.lower()
        return hit, "robots.txt 含 %r" % sub
    if "home_robots_same_bytes" in token:
        want = token["home_robots_same_bytes"]
        same = (probe.home_html is not None and probe.robots_text is not None
                and probe.home_html.encode("utf-8", "ignore") ==
                probe.robots_text.encode("utf-8", "ignore"))
        import hashlib
        digest = hashlib.md5(
            (probe.home_html or "").encode("utf-8", "ignore")).hexdigest()[:8]
        return (same == want), ("home 与 robots.txt 字节完全相同（md5 %s）" % digest
                                if same else "home 与 robots.txt 不同")
    raise ValueError("规则里有未实现的检测项：%r" % list(token))


def rule_hits(rule, probe):
    # rule 可以是一条完整规则（带 detect），也可以是一个裸的 all/any 组
    det = rule.get("detect") or rule
    ev, hit = [], False
    if "all" in det:
        results = [_ev(t, probe) for t in det["all"]]
        hit = all(r[0] for r in results)
        if hit:
            ev = []
            for r in results:
                ev.extend(list(r[1]) if isinstance(r[1], (list, tuple)) else [r[1]])
    if not hit and "any" in det:
        for t in det["any"]:
            ok, why = _ev(t, probe)
            if ok:
                hit = True
                ev = list(why) if isinstance(why, (list, tuple)) else [why]
                break
    return hit, ev


def load_rules(rules_dir):
    rules = []
    meta = {"schema_version": "1.0", "rules_version": "unknown"}
    for p in sorted(Path(rules_dir).glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        if p.name.startswith("_"):
            meta.update(obj)
            continue
        obj["_file"] = p.name
        obj.setdefault("priority", 50)
        rules.append(obj)
    rules.sort(key=lambda r: (r["priority"], r["_file"]))
    return rules, meta


# --------------------------------------------------------------------------- #
# 判定主流程（短路）
# --------------------------------------------------------------------------- #
def identify(url, html=None, robots_text=None, home_html=None,
             allow_network=True, rules_dir=CHANNEL_DIR, timeout=15,
             max_requests=MAX_REQUESTS_PER_SITE):
    rules, meta = load_rules(rules_dir)
    probe = Probe(url, html=html, robots_text=robots_text, home_html=home_html,
                  allow_network=allow_network, timeout=timeout,
                  max_requests=max_requests)

    # ① 先判已有证据（0 请求）
    card = _judge(url, probe, rules, meta)

    # ② Rule0 需要"home vs robots"对比时，补 1 个 robots 请求
    if card["matched_rule"] == "" and probe.robots_text is None and probe.home_html is not None:
        if probe.fetch("robots"):
            card = _judge(url, probe, rules, meta)

    # ③ 仍然判不出来 → 取首页（再 1 请求，总计 ≤2）
    if card["status"] == "unknown" and probe.html is None:
        if probe.fetch("home"):
            card = _judge(url, probe, rules, meta)

    card["requests_made"] = probe.requests_made
    card["encoding"] = probe.encoding or ""
    card["bytes"] = probe.size
    return card


def _judge(url, probe, rules, meta):
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc or url
    card = {
        "schema_version": meta.get("schema_version", "1.0"),
        "rules_version": meta.get("rules_version", "unknown"),
        "url": url,
        "host": host,
        "status": "unknown",
        "form": "",
        "channel": "unknown",
        "transport": "none",
        "capability": "needs_v14",
        "confidence": "C",
        "evidence": [],
        "est_volume": "",
        "rule0_hit": "",
        "next_step": "",
        "matched_rule": "",
    }
    for rule in rules:
        hit, ev = rule_hits(rule, probe)
        if not hit:
            continue
        is_rule0 = rule.get("kind") == "rule0"
        card.update({
            "status": "blocked" if is_rule0 else rule.get("status", "ok"),
            "form": rule.get("form", ""),
            "channel": rule.get("channel", "unknown"),
            "transport": rule.get("transport", "none"),
            "capability": rule.get("capability", "needs_v14"),
            "est_volume": rule.get("est_volume", ""),
            "next_step": rule.get("next_step", ""),
            "matched_rule": rule["_file"],
            "evidence": ev,
            # 通道/规则命中给 A；通用兜底（只看尺寸/正文长度）给 B
            "confidence": "B" if rule.get("kind") == "generic" else "A",
        })
        if is_rule0:
            card["rule0_hit"] = rule.get("name", rule["id"])
        return card
    if probe.html is None:
        card["status"] = "unknown"
        card["capability"] = "unknown"
        card["evidence"] = ["取不到首页（网络失败/超时/需 http）"]
        card["next_step"] = "换 http:// 重试，或人工确认站点是否存活（这不是判不出，是没拿到）"
        return card
    card["evidence"] = ["未命中任何规则（%d 条）" % len(rules)]
    card["next_step"] = "补一份首页 HTML 或换列表页再判；也可能是新形态，需要新增一条规则 JSON"
    return card


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _read(path):
    p = Path(path)
    raw = p.read_bytes()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="v13.2 通道判定器")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--html", help="已存 HTML 文件（离线判定，0 请求）")
    ap.add_argument("--robots", help="已存 robots.txt")
    ap.add_argument("--home", help="已存首页 HTML（与 --html 分开时用）")
    ap.add_argument("--batch", help="批量清单 JSON：[{key,url,html,robots,expect:{...}}]")
    ap.add_argument("--out", help="批量结果写入这个 JSON")
    ap.add_argument("--rules-dir", default=str(CHANNEL_DIR))
    ap.add_argument("--no-network", action="store_true", help="只判已有证据，不发任何请求")
    ap.add_argument("--max-requests", type=int, default=MAX_REQUESTS_PER_SITE,
                    help="单站请求上限（默认 2 = robots + 首页；批量省预算用 1）")
    args = ap.parse_args()

    if args.batch:
        items = json.loads(Path(args.batch).read_text(encoding="utf-8"))
        cards, ok = [], 0
        for it in items:
            html = _read(it["html"]) if it.get("html") else None
            robots = _read(it["robots"]) if it.get("robots") else None
            home = _read(it["home"]) if it.get("home") else None
            card = identify(it["url"], html=html, robots_text=robots, home_html=home,
                            allow_network=not args.no_network,
                            rules_dir=Path(args.rules_dir))
            card["key"] = it.get("key", "")
            exp = it.get("expect") or {}
            card["expect"] = exp
            card["pass"] = all(
                (card.get(k) == v) if k != "status_note" else True
                for k, v in exp.items())
            ok += 1 if card["pass"] else 0
            cards.append(card)
        if args.out:
            Path(args.out).write_text(json.dumps(cards, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        print("批量判定 %d 站，命中期望 %d 个" % (len(cards), ok))
        for c in cards:
            print("  [%s] %-28s %-9s %-13s %-6s req=%d %s"
                  % ("PASS" if c["pass"] else "FAIL", c["host"], c["status"], c["form"],
                     c["channel"], c["requests_made"],
                     "" if c["pass"] else ("期望 " + json.dumps(c["expect"], ensure_ascii=False))))
        return 0 if ok == len(cards) else 1

    if not args.url:
        ap.print_help()
        return 2
    html = _read(args.html) if args.html else None
    robots = _read(args.robots) if args.robots else None
    home = _read(args.home) if args.home else None
    card = identify(args.url, html=html, robots_text=robots, home_html=home,
                    allow_network=not args.no_network, rules_dir=Path(args.rules_dir))
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())