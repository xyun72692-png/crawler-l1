#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v13.4 候选编排：给一个目标（地区 + 行业），出候选清单。

来源顺序（2026-11-14 改版，**检索优先**；旧的「成本递增、顺序不能反」已作废）：
  第 -1 步 平台先验      0 请求    读 tools/geo/known_platforms.json（命中即给结论，过期只提示重验）
  第 0 步  官方名录      0 请求    读 tools/geo/gov_platforms.json（省级公共就业平台等）
  第 1 步  检索          1 次搜索  读 search_queries.json 出模板；结果放进 --search-result
  第 2 步  页脚 / 友链   0 请求    读 data/raw 已存首页 + out/friendlink_domains.json
  第 3 步  域名语法+DNS  0 HTTP    {city}+后缀 等模板批量解析
  第 4 步  枚举表抽样    -         读 jrzp_domain_enum_v2 的 csv：A 档全收 + B 档抽 --b-sample 个
  第 5 步  人工 --seed   -

本文件不含任何具体域名：后缀模板在 tools/geo/patterns.json，
城市表在 tools/geo/cities.json，官方平台名录在 tools/geo/gov_platforms.json，
检索模板在 tools/geo/search_queries.json。

用法：
    # 只打印该地区/行业该跑哪几条检索（0 网络，agent 照着搜）
    python tools/discover.py --region 浙江 --industry 食品 --print-queries

    # 判型 A/D（数据只有一个机构在产生）：只查官方名录 + 给定 URL（URL 由调用方传入）
    python tools/discover.py --region 浙江 --mode single --seed SEED_URL

    # 判型 C（数据在平台内、要账号）：零请求，直接告诉你要账号
    python tools/discover.py --mode account

    # 判型 B（默认 wide）：六步全跑，行为与 v13.4 完全一致
    python tools/discover.py --region 浙江 --industry 食品 --out out/candidates.csv

    # 检索结果交给它并入候选（检索由 agent 执行，本脚本只解析）
    python tools/discover.py --region 浙江 --industry 食品 --search-result out/search_zj.json --out out/candidates.csv

    # 纯离线：官方名录 + 页脚 + 友链 + 域名语法
    python tools/discover.py --region 浙江 --skip-syntax

    # 把旧枚举表的 B 档也捞 15 个回来验证
    python tools/discover.py --region 浙江 --from-enum out/v13_enum_v2.csv --b-sample 15
"""

import argparse
import csv
import json
import random
import socket
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "tools" / "geo"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "out"

CSV_COLS = ["城市", "域名", "通道", "形态", "状态", "置信度", "预估量", "证据摘要",
            "下一步", "来源", "歧义", "覆盖度", "备注", "平台判定"]

SRC_GOV = "0 官方名录"
SRC_SEARCH = "1 检索"
SRC_FOOTER = "2 页脚/友链（已存首页）"
SRC_FRIEND = "2 友链统计（已存产物）"
SRC_SYNTAX = "3 域名语法 + DNS"
SRC_ENUM = "4 枚举表抽样"
SRC_SEED = "5 人工 seed"

# ---- 判型（2026-11-15）：判型只写在文档里等于没有，代码必须有强制入口 ----
# A 单点权威（数据只有一个机构在产生）→ single：只跑第 0 步官方名录 + 给定 URL
# B 多源长尾（无数主体各自发布）      → wide  ：六步全跑（默认，行为与之前完全一致）
# C 账号在环（数据在平台内，用户有号）→ account：先要账号，零请求
# D 开放 API（已有现成接口）          → single + --seed 直接给接口地址
MODE_SINGLE = "single"
MODE_WIDE = "wide"
MODE_ACCOUNT = "account"

# 来源权重：数字小的排前面，保证 --limit 截断时先砍最不可靠的来源
SRC_ORDER = {SRC_GOV: 0, SRC_SEARCH: 1, SRC_FOOTER: 2, SRC_FRIEND: 2,
             SRC_SYNTAX: 3, SRC_ENUM: 4, SRC_SEED: 5}


def safe(s):
    """控制台打印用：GBK 窗口遇到生僻字符不许崩。"""
    return str(s).encode("gbk", "replace").decode("gbk", "replace")


def clean_text(t):
    """去掉锚文本里的控制符/重新元音符号等脏字符（页脚里确实出现过 \\u05b0）。"""
    import re
    t = re.sub(r"[\u0000-\u001f\u007f-\u009f\u0590-\u05ff\ufffd\u200b-\u200f]", "", t)
    return re.sub(r"\s+", "", t).strip()


def load_json(p, default):
    p = Path(p)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


KNOWN = GEO / "known_platforms.json"


def load_known_platforms():
    """平台先验清单（0 请求）。"""
    return load_json(KNOWN, {}) or {}


def match_known_platform(host, known=None):
    """按域名后缀匹配平台先验。返回 (entry, state)；state = fresh / stale / ""。"""
    known = known if known is not None else load_known_platforms()
    h = (host or "").lower().strip()
    if h.startswith("www."):
        h = h[4:]
    if not h:
        return None, ""
    today = date.today()
    default_ttl = int((known.get("_meta") or {}).get("default_ttl_days") or 180)
    for e in known.get("platforms") or []:
        for d in ((e.get("match") or {}).get("domains") or []):
            d = (d or "").lower().strip()
            if d and (h == d or h.endswith("." + d)):
                ttl = int(e.get("ttl_days") or default_ttl)
                try:
                    checked = date.fromisoformat(e.get("verified_at") or "")
                except ValueError:
                    return e, "stale"
                return e, ("fresh" if (today - checked).days <= ttl else "stale")
    return None, ""


def dns_ok(host, timeout=2.0):
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 第 0 步：官方名录
def from_gov_roster(region, all_regions=False, goal=""):
    """读 gov_platforms.json：官方/政府类平台直接并入候选（0 请求）。

    verified 非空 = 已实测（置信度「已验证」）；空 = 待验（置信度「待验」）。
    条目里的 coverage 透传到输出，供判断「这个省是不是有统一平台」。

    goal 非空时按条目 kind 过滤（招聘/法规/价格/天气）—— 天气任务不该看到招聘站，
    那属于把判型的活又推回给人。
    """
    data = load_json(GEO / "gov_platforms.json", {})
    want_kind = GOAL_MAP.get(goal) if goal else ""
    rows = []
    for prov, items in data.items():
        if prov.startswith("_"):
            continue
        if not all_regions and not region_matches(prov, region):
            continue
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict) or not it.get("domain"):
                continue
            if want_kind and (it.get("kind") or "") != want_kind:
                continue
            verified = (it.get("verified") or "").strip()
            rows.append({
                "城市": prov,
                "域名": it["domain"],
                "来源": SRC_GOV,
                "证据": "%s｜%s" % (it.get("name", ""), it.get("evidence", "")),
                "置信度": "已验证" if verified else "待验",
                "coverage": it.get("coverage", "unknown"),
                "note": it.get("note", ""),
                "next": it.get("url") or ("https://%s" % it["domain"]),
            })
    return rows


def region_matches(prov, region):
    """「浙江」≈「浙江省」≈「浙江省级」，宽松匹配。"""
    if not region:
        return False
    a, b = prov.strip(), region.strip()
    return a == b or a in b or b in a


# ---------------------------------------------------------------- 第 1 步：检索
GOAL_MAP = {"jobs": "招聘", "regulation": "法规", "price": "价格", "weather": "天气"}

# 这几个 goal 属于 A/D 型（单点权威：一个机构在产生数据）——
# 用 wide 跑六步就是"大炮打蚊子"，所以要拦；真要多源发现必须显式 --force-wide。
AD_GOALS = ("weather", "regulation")


def print_queries(region, city, industry, goal):
    """只打印 goal 对应类别的模板。goal 空或非法 → 报错。

    **不许把 search_queries.json 里 14 条全吐出来** —— 天气任务看到"招聘 6 条"是噪音，
    人还得自己筛，等于把判型的活又推回给人。
    """
    if not goal:
        print("!! --print-queries 必须给 --goal，否则不知道该出哪一类模板。")
        print("   可选：%s" % " / ".join("%s(%s)" % (k, v) for k, v in GOAL_MAP.items()))
        return 2
    kind = GOAL_MAP.get(goal)
    if not kind:
        print("!! 未知 --goal=%r。可选：%s"
              % (goal, " / ".join("%s(%s)" % (k, v) for k, v in GOAL_MAP.items())))
        return 2

    tpl = load_json(GEO / "search_queries.json", {})
    queries = tpl.get(kind) or []
    if not queries:
        print("!! search_queries.json 里没有「%s」这一类" % kind)
        return 2

    fields = {"省": region or "", "市": city or region or "",
              "行业": industry or "", "部委": industry or "", "品类": industry or ""}
    seen, lines = set(), []
    for q in queries:
        try:
            q2 = q.format(**fields)
        except (KeyError, IndexError):
            continue
        q2 = q2.strip()
        # 去重：没给 --city 时，{省} 与 {市} 会退化成同一个词，模板会撞车
        if not q2 or "{" in q2 or q2 in seen:
            continue
        seen.add(q2)
        lines.append(q2)

    if not lines:
        print("!! 该类模板全部因缺占位符而渲染不出来（检查 --region / --industry）")
        return 2
    print("[%s] %s" % (goal, kind))
    for q2 in lines:
        print("  " + q2)
    print("\n共 %d 条（只含「%s」这一类）。检索完把 URL 存成 JSON 再 --search-result 并入："
          % (len(lines), kind))
    print('  {"query": "...", "urls": ["https://<域名>/"]}')
    return 0


def _iter_urls(node, query="", depth=0):
    """从任意嵌套结构里递归收集 (url, query)。

    字符串先判、不受深度限制 —— 之前把 `depth > 6` 放在最前面，
    第 7 层的字符串直接被截断，结果"深一层就静默丢 URL"（实测丢掉 deep.items[].href）。
    """
    if isinstance(node, str):
        if node.startswith("http"):
            yield node, query
        return
    if depth > 8:
        return
    if isinstance(node, list):
        for x in node:
            for u, q in _iter_urls(x, query, depth + 1):
                yield u, q
        return
    if isinstance(node, dict):
        q2 = node.get("query") or node.get("q") or query
        # 常见键先走一遍（顺序稳定），其余键也扫，避免"换个字段名就静默丢"
        for k in ("url", "link", "href", "urls", "results", "items", "data",
                  "records", "list", "docs", "hits", "value"):
            if k in node:
                for u, q in _iter_urls(node[k], q2, depth + 1):
                    yield u, q
        for k, v in node.items():
            if k in ("url", "link", "href", "urls", "results", "items", "data",
                     "records", "list", "docs", "hits", "value"):
                continue
            for u, q in _iter_urls(v, q2, depth + 1):
                yield u, q
        return


def from_search(path):
    """解析检索结果（由 agent 执行检索后落盘）。

    返回 (rows, err)：
      err 非空 = 这份检索结果不可用（读不了 / 结构认不出 / 解析出 0 条域名）。
      **解析 0 条必须报错**，不许打印"成功"——那会让人以为检索做过、其实什么也没进来。
    """
    if not path:
        return [], ""
    data = load_json(path, None)
    if data is None:
        return [], "检索结果文件读不了或不是合法 JSON：%s" % path

    rows, seen = [], set()
    for url, q in _iter_urls(data):
        host = urlsplit(url).netloc
        if not host or host in seen:
            continue
        seen.add(host)
        rows.append({"城市": "", "域名": host, "来源": SRC_SEARCH,
                     "证据": "检索「%s」" % q if q else "检索结果",
                     "置信度": "候选", "next": url})

    if not rows:
        return [], ("检索结果里解析出 0 条域名：%s（顶层类型 %s）"
                    % (path, type(data).__name__))
    return rows, ""


# ---------------------------------------------------------------- 第 2 步：页脚 / 友链
def from_footer(region):
    """① 已存首页页脚里的城市站（0 请求）：按锚文本找外链。

    F-14：类目/地区识别看**锚文本**，不看域名拼音。
    旧实现用 `"rc." in url or "rcw." in url or "job" in url` 过滤，
    会把「域名里恰好不含这几个串」的综合平台静默丢掉 —— 违反 F-14。
    """
    rows = []
    for p in sorted(RAW.glob("*_home.html"))[:40]:
        try:
            html = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        import re
        own_host = ""
        m0 = (re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\'](https?://[^"\']+)', html, re.I)
              or re.search(r'<meta[^>]+property=["\']og:url["\'][^>]*content=["\'](https?://[^"\']+)', html, re.I))
        if m0:
            own_host = urlsplit(m0.group(1)).netloc.lower()
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.S):
            url = m.group(1)
            host = urlsplit(url).netloc.lower()
            text = clean_text(re.sub(r"<[^>]+>", "", m.group(2)))
            if own_host and host == own_host:
                continue                      # 站内链接不算友链
            if 2 <= len(text) <= 12:
                rows.append({"城市": text, "域名": host,
                             "来源": SRC_FOOTER, "证据": "来自 %s" % p.name,
                             "置信度": "候选"})
    return rows



def from_friendlink():
    """③ 友链域名（0 请求，读已有产物）。"""
    data = load_json(OUT / "friendlink_domains.json", {})
    rows = []
    items = data.items() if isinstance(data, dict) else []
    for host, cnt in items:
        rows.append({"城市": "", "域名": host, "来源": SRC_FRIEND,
                     "证据": "在已存首页出现 %s 次" % cnt, "置信度": "候选"})
    return rows


# ---------------------------------------------------------------- 第 3 步：域名语法
def build_abbr_index(region):
    """abbr → [城市...]：用于识别「zj = 浙江 还是 镇江」这类歧义。"""
    cities = load_json(GEO / "cities.json", {})
    idx = {}

    def add(name, val):
        v = (val or "").strip().lower()
        if v:
            idx.setdefault(v, set()).add(name)

    for prov, lst in cities.items():
        if prov == "_provinces" and isinstance(lst, list):
            for c in lst:                     # 省级条目也进索引：
                add(c.get("city", ""), c.get("abbr"))   # 这样 zj 才能同时对上
                add(c.get("city", ""), c.get("pinyin")) # 「浙江」和「镇江」
            continue
        if prov.startswith("_") or not isinstance(lst, list):
            continue
        for c in lst:
            add(c.get("city", ""), c.get("abbr"))
            add(c.get("city", ""), c.get("pinyin"))
    return {k: sorted(v) for k, v in idx.items()}


def _gen_level(units, suffixes, templates, cap, abbr_idx, level, join="concat"):
    """按「单位表 × 后缀 × 前缀模板」生成候选并逐个 DNS 解析。

    join="concat"（默认）：{pinyin} + 后缀 -> 拼成一个词（真实站就是这种，中间没有点）
    join="dot"           ：{pinyin} + "." + 后缀 -> 拆成子域（本项目的真站不是这种写法）
    v13 的 discover.py 一直用 dot，所以永远生成不出真站域名；这里改成 concat。
    """
    rows = []
    for c in units:
        made = 0
        for suf in suffixes:
            if made >= cap:
                break
            for tpl in templates:
                if made >= cap:
                    break
                host = tpl.format(**c) + (suf if join == "concat" else ("." + suf))
                if not dns_ok(host):
                    continue
                # 歧义检测：模板里用到的缩写，全国范围（含省级）是否对应多个地名
                owners = []
                for key in ("abbr", "pinyin"):
                    v = (c.get(key) or "").strip().lower()
                    if v and tpl.find("{%s}" % key) >= 0:
                        owners = abbr_idx.get(v, [])
                        break
                amb = len(owners) > 1
                rows.append({
                    "城市": c["city"], "域名": host, "来源": SRC_SYNTAX,
                    "证据": "%s DNS 可解析（0 HTTP）" % level
                            + ("；缩写歧义：" + "/".join(owners) if amb else ""),
                    "置信度": "候选",
                    "ambiguous": amb,
                    "owners": owners,
                })
                made += 1
    return rows


def from_syntax(region):
    """④ 域名语法 + DNS（0 HTTP）。市级 + 省级两套模板；歧义缩写不单选。"""
    data = load_json(GEO / "cities.json", {})
    pats = load_json(GEO / "patterns.json", {})
    abbr_idx = build_abbr_index(region)
    rows = []
    # 市级：{city}+后缀 一类（后缀表在 geo/patterns.json）
    rows += _gen_level(
        data.get(region, []),
        pats.get("suffixes", []),
        pats.get("prefix_templates", ["{pinyin}"]),
        int(pats.get("max_candidates_per_city", 6)),
        abbr_idx, "市级")
    # 省级：{省}+hr 一类（v13 完全没有这一档，浙江那个省级平台因此永远生成不出来）
    provs = [p for p in data.get("_provinces", []) if region_matches(p.get("city", ""), region)]
    if provs:
        rows += _gen_level(
            provs,
            pats.get("province_suffixes", []),
            pats.get("province_prefix_templates", ["{pinyin}", "{abbr}"]),
            int(pats.get("max_candidates_per_province", 4)),
            abbr_idx, "省级")
    return rows


# ---------------------------------------------------------------- 第 4 步：枚举表抽样
def from_enum(csv_path, b_sample=15):
    """读旧枚举表：A 档全收；B 档抽 b_sample 个（固定种子，可复现）。

    为什么这么做：v13 的 244 个候选里 B 档 98 个全被丢掉，
    浙江人力资源大市场那个域名就躺在 B 档里 —— 「B 级」只等于「没验证」。
    """
    p = Path(csv_path)
    if not p.exists():
        print("!! 枚举表不存在：%s" % csv_path)
        return []
    rows, b_rows = [], []
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            conf = (r.get("confidence") or "").strip()
            row = {"城市": r.get("owner", ""), "域名": r.get("domain", ""),
                   "来源": SRC_ENUM, "证据": (r.get("pattern", "") + "｜" + conf).strip("｜"),
                   "置信度": conf.split(" ")[0] if conf else "?"}
            if conf.startswith("A"):
                rows.append(row)
            elif conf.startswith("B"):
                b_rows.append(row)
    if b_sample > 0 and b_rows:
        rnd = random.Random(0)
        picked = rnd.sample(b_rows, min(b_sample, len(b_rows)))
        for r in picked:
            r["证据"] += "｜B 档抽样验证额度"
            r["verify_quota"] = "b_sample"
        rows += picked
    print("   枚举表：A 档 %d 个全收；B 档共 %d 个，抽 %d 个进验证额度"
          % (len(rows) - len([r for r in rows if r.get("verify_quota")]), len(b_rows),
             len([r for r in rows if r.get("verify_quota")])))
    return rows


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="v13.4 候选编排（检索优先）")
    ap.add_argument("--region", default="浙江")
    ap.add_argument("--city", default="")
    ap.add_argument("--industry", default="")
    ap.add_argument("--seed", action="append", default=[])
    ap.add_argument("--search-result", default="", help="检索结果 JSON（agent 搜完落盘）")
    ap.add_argument("--from-enum", default="", help="旧枚举 csv（A 全收 + B 抽样）")
    ap.add_argument("--b-sample", type=int, default=15, help="B 档抽样额度，0=不要")
    ap.add_argument("--all-gov", action="store_true", help="全国官方名录都并入")
    ap.add_argument("--print-queries", action="store_true", help="只打印检索模板，0 网络")
    ap.add_argument("--skip-syntax", action="store_true", help="不跑域名语法（省 DNS）")
    ap.add_argument("--goal", default="",
                    help="数据类别，决定检索哪一类模板：%s" % " / ".join(GOAL_MAP))
    ap.add_argument("--mode", choices=[MODE_SINGLE, MODE_WIDE, MODE_ACCOUNT], default=None,
                    help="判型，**必填**：single=只跑官方名录+给定URL（A/D 型）；"
                         "wide=六步全跑（B 型）；account=先要账号、零请求（C 型）。"
                         "不给就 0 请求、先把判型三问打出来问你")
    ap.add_argument("--force-wide", action="store_true",
                    help="允许用 --mode wide 跑 A/D 型 goal（weather/regulation）。"
                         "不加就 rc=2 拒绝；加了会在输出里留痕。")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", default=str(OUT / "candidates.csv"))
    args = ap.parse_args()

    # ---- --goal 必填（所有执行模式 + --print-queries 都要）----
    if not args.goal:
        print("!! --goal 必填。可选：%s"
              % " / ".join("%s(%s)" % (k, v) for k, v in GOAL_MAP.items()))
        print("   它决定两件事：① 检索出哪一类模板 ② 官方名录按哪一类 kind 过滤。")
        print("   不写的话，天气任务会被塞进招聘站和招聘模板 —— 等于把判型的活推回给人。")
        return 2
    if args.goal not in GOAL_MAP:
        print("!! 未知 --goal=%r。可选：%s"
              % (args.goal, " / ".join("%s(%s)" % (k, v) for k, v in GOAL_MAP.items())))
        return 2

    if args.print_queries:
        return print_queries(args.region, args.city, args.industry, args.goal)

    # ---- 判型闸门：不判型 = 不许开跑（0 请求）----
    if not args.mode:
        print("== 先判型，再谈发现（本次 0 请求）==")
        print("   这条数据需要几个源？回答三个问题（30 秒）：")
        print("     ① 谁产生这条数据？   一个机构 -> A/D ；无数主体 -> B")
        print("     ② 手上有账号吗？     有，且数据在平台里 -> C")
        print("     ③ 有现成接口吗？     有 -> D（连抓都不用抓）")
        print()
        print("   A 单点权威   1~2 个源，找到就停，**不进页脚/域名/枚举**   天气、国家法规、汇率")
        print("   B 多源长尾   10~50+ 个源，跑满六步，按覆盖度停           招聘、租房、招投标")
        print("   C 账号在环   1 个源（你的账号），**先问账号**              拼多多价格、知乎、微博")
        print("   D 开放 API   1 个源，直接调接口，不抓页面                 天气 API、开放数据")
        print()
        print("   选定后重跑：--mode %s" % " | ".join(GOAL_MAP and
                                             [MODE_SINGLE, MODE_WIDE, MODE_ACCOUNT]))
        return 2

    # ---- wide 不许跑 A/D 型 goal（weather / regulation）----
    # 这三个判断的顺序有意义：先拦"没判型"，再拦"判错了型"。
    if args.mode == MODE_WIDE and args.goal in AD_GOALS and not args.force_wide:
        print("!! --goal %s 属于 A/D 型（单点权威），不该用 --mode wide 跑六步。" % args.goal)
        print("   天气：中央气象台 / 一个天气 API 就够；法规：一手公报（国务院/司法部/地方公报）1~3 个源。")
        print("   跑六步去搜聚合站 / 枚举域名 = 纯浪费。")
        print("   确实要强制多源发现，请加 --force-wide（会写进输出留痕）。")
        return 2
    if args.mode == MODE_WIDE and args.goal in AD_GOALS:
        print("   !! 已用 --force-wide 强制 wide 跑 %s（A/D 型）—— 这是显式覆盖，不是默认放行"
              % args.goal)

    # ---- 判型行为 ----
    if args.mode == MODE_ACCOUNT:
        print("== 判型 C（账号在环）：先要账号，不做发现 ==")
        print("   这类数据在平台内，没账号就没有入口；跑六步去搜聚合站是浪费。")
        print("   需要你先给三件事：① 哪个平台 ② 有没有账号/能不能登录 ③ 只要哪些字段")
        print("   （本模式 0 请求，未生成候选文件）")
        return 0
    if args.mode == MODE_SINGLE and (args.search_result or args.from_enum):
        bad = [n for n, v in (("--search-result", args.search_result),
                              ("--from-enum", args.from_enum)) if v]
        print("!! --mode single 不接受 %s。" % "、".join(bad))
        print("   single 是 A/D 型（数据只有一个机构在产生）：只跑第 0 步官方名录 + --seed 给定 URL。")
        print("   确实要多源发现，请改用 --mode wide。")
        return 2

    rows = []
    # 第 0 步：官方名录（0 请求，永远先做；single / wide 都跑）
    gov_rows = from_gov_roster(args.region, all_regions=args.all_gov, goal=args.goal)
    if gov_rows:
        print("   第 0 步 官方名录：%d 个（其中已验证 %d 个）"
              % (len(gov_rows), len([r for r in gov_rows if r["置信度"] == "已验证"])))
    else:
        print("   第 0 步 官方名录：0 个（名录里没有这个地区）")
    rows += gov_rows

    if args.mode == MODE_SINGLE:
        for u in args.seed:
            rows.append({"城市": "", "域名": urlsplit(u).netloc, "来源": SRC_SEED,
                         "证据": "人工给定", "置信度": "候选", "next": u})
        print("   给定 URL（--seed）：%d 个" % len(args.seed))
        if not gov_rows and not args.seed:
            # A/D 型但不知道一手源 —— 这是唯一该检索的 A/D 场景
            print("   判型 single（A/D 型）：名录没命中，也没给 --seed，**不知道一手源**。")
            print("   -> 这种情况才该检索一次：python tools/discover.py --goal %s --print-queries"
                  % (args.goal or "<jobs|regulation|price|weather>"))
            print("   （本次仍是 0 请求；拿到一手源后用 --seed 重跑）")
        else:
            print("   判型 single（A/D 型）：已有可信源（名录/seed），**不检索**、不跑页脚/域名/枚举")
    else:
        # 第 1 步：检索结果（B 型必跑；A/D 型在上面已被截住，C 型更早返回）
        search_rows, search_err = from_search(args.search_result)
        if search_err:
            print("!! 第 1 步 检索结果不可用：%s" % search_err)
            print("   解析出 0 条 = 这次检索等于没做，**不能当成功**（rc=2）。")
            return 2
        if search_rows:
            print("   第 1 步 检索结果：%d 个域名" % len(search_rows))
        else:
            print("   第 1 步 检索：未提供 --search-result（先跑 --goal %s --print-queries）"
                  % (args.goal or "<jobs|regulation|price|weather>"))
            print("   F-22：本次检索条数 = 0 —— 属于**漏项**（需要找站却没检索）。")
            print("        要么补检索（模板见 --print-queries），要么在结论里写明为什么不需要。")
        rows += search_rows

        # 第 2 步：页脚 / 友链
        foot = from_footer(args.region)
        friend = from_friendlink()
        print("   第 2 步 页脚/友链：%d + %d 个" % (len(foot), len(friend)))
        rows += foot
        rows += friend

        # 第 3 步：域名语法 + DNS
        if args.skip_syntax:
            print("   第 3 步 域名语法：已用 --skip-syntax 跳过（0 DNS）")
        else:
            syn = from_syntax(args.region)
            print("   第 3 步 域名语法+DNS：%d 个（其中标歧义 %d 个）"
                  % (len(syn), len([r for r in syn if r.get("ambiguous")])))
            rows += syn

        # 第 5 步：人工 seed（保持在枚举之前 —— 去重时"先出现者优先"，
        # 换顺序会让同一个域名的来源标记从 seed 变成 enum，属于行为变化）
        for u in args.seed:
            rows.append({"城市": "", "域名": urlsplit(u).netloc, "来源": SRC_SEED,
                         "证据": "人工给定", "置信度": "候选", "next": u})
        if args.seed:
            print("   第 5 步 人工 seed：%d 个" % len(args.seed))

        # 第 4 步：枚举表抽样（A 全收 + B 抽样）—— 序号在前但执行在后，与 v13.4 一致
        if args.from_enum:
            rows += from_enum(args.from_enum, args.b_sample)
        else:
            print("   第 4 步 枚举表抽样：未提供 --from-enum，跳过")

    # 去重（同域名只留第一条，保留最先出现的来源 —— 官方名录 > 检索 > 其余）
    seen, uniq = set(), []
    for r in rows:
        host = (r.get("域名") or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if not host or host in seen:
            continue
        seen.add(host)
        r["_host"] = host
        uniq.append(r)

    # 排序按「来源权重」优先（官方名录 > 检索 > 页脚 > 语法 > 枚举），
    # 不能按城市名 —— 否则中文码点顺序会把官方名录挤出 --limit。
    uniq.sort(key=lambda r: (SRC_ORDER.get(r.get("来源", ""), 9),
                             r.get("城市") == "", r.get("城市", ""), r["域名"]))
    uniq = uniq[: args.limit]

    # ---- 平台先验（0 请求）：命中即给结论；过期只提示重验 ----
    known = load_known_platforms()
    hits = []
    for r in uniq:
        entry, state = match_known_platform(r.get("_host") or r.get("域名"), known)
        if not entry:
            continue
        label = "%s / %s" % (entry.get("platform") or entry.get("id"),
                             entry.get("verdict") or "?")
        if state == "stale":
            label += "（已过期，建议重验）"
        elif entry.get("confidence") == "recorded":
            label += "（记录级，未复验）"
        r["平台判定"] = label
        hits.append((r, entry, state))
    if hits:
        stale_n = sum(1 for _, _, st in hits if st == "stale")
        print("   平台先验：命中 %d 个（过期 %d）" % (len(hits), stale_n))
        for r, e, st in hits[:8]:
            extra = "  ← 已过期，建议重验" if st == "stale" else ""
            print("     %-28s %-12s %s%s" % (safe(r["域名"]), safe(e.get("platform") or e.get("id")),
                                             safe(e.get("verdict") or "?"), extra))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in uniq:
            w.writerow({
                "城市": r.get("城市") or "-",
                "域名": r["域名"],
                "通道": "-", "形态": "-", "状态": "pending",
                "置信度": r.get("置信度", "-"),
                "预估量": "-",
                "证据摘要": "%s；%s" % (r.get("来源", ""), r.get("证据", "")),
                "下一步": "python tools/identify.py %s" % (r.get("next") or ("https://" + r["域名"])),
                "来源": r.get("来源", ""),
                "歧义": "yes" if r.get("ambiguous") else "",
                "覆盖度": r.get("coverage", ""),
                "备注": r.get("note", ""),
                "平台判定": r.get("平台判定", ""),
            })

    print("候选 %d 个 → %s" % (len(uniq), out))
    by_src = {}
    for r in uniq:
        by_src[r.get("来源", "?")] = by_src.get(r.get("来源", "?"), 0) + 1
    for k, v in sorted(by_src.items()):
        print("  %-24s %d" % (k, v))
    amb = [r for r in uniq if r.get("ambiguous")]
    if amb:
        print("  !! 歧义候选 %d 个（缩写同时对应多个城市，未单选）：" % len(amb))
        for r in amb[:5]:
            print("     %-24s %s" % (r["域名"], "/".join(r.get("owners") or [])))
    for r in uniq[:12]:
        print("   %-8s %-30s %s" % (safe(r.get("城市") or "-"), safe(r["域名"]),
                                    safe(r.get("来源", ""))))
    return 0


if __name__ == "__main__":
    sys.exit(main())