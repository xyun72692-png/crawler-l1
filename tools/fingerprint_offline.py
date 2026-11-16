# -*- coding: utf-8 -*-
"""
离线指纹（v13 第一件，**0 请求**）：只读本地已存的 HTML，不连任何站点。

输出四样（都是能跨站比对的信号）：
  1. outbound_hosts   页面里 <a href> 指到的域名（含友链/"分站"）—— 发现新站的主力
  2. resource_hosts   <img>/<script>/<link> 的第三方域名 —— 识别平台（如 img.jrzp.com）
  3. static_paths     静态资源路径集合（js/css/png/ico/svg）—— 同模板站会高度重合
  4. favicon          页面声明的 icon 地址（只有 URL，**离线拿不到 ico 字节**，
                      要算 favicon hash 必须在线抓 1 次，见 tools/_murmur3.py）

用法：
  python tools\\fingerprint_offline.py <html> [--json out.json]
  python tools\\fingerprint_offline.py --compare A.html B.html

说明：
  · 一个 HTTP 请求都不发（脚本里没有 requests/urllib 的网络调用）
  · 这是 v13 验收的"尺子"：能否从已存页面复现已知答案
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

RE_STATIC = re.compile(r"\.(js|css|png|jpg|jpeg|gif|ico|svg|webp)(?:\?|$)", re.I)
RE_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
FAVICON_KEYS = ("icon", "shortcut icon", "apple-touch-icon", "mask-icon")


def _host(url, base_host=""):
    u = (url or "").strip()
    if not u or u.startswith(("#", "javascript:", "data:", "mailto:", "tel:")):
        return ""
    if u.startswith("//"):
        u = "http:" + u
    sp = urlsplit(u)
    h = (sp.netloc or "").lower().split(":")[0]
    if not h and base_host and u.startswith("/"):
        return base_host          # 站内相对路径
    # 只认"像域名"的 host：`message`、`undefined` 这种是页面里的 JS 变量，不是域名
    return h if RE_DOMAIN.match(h) else ""


def analyze(path, base_host=""):
    p = Path(path)
    html = p.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    title = soup.title.get_text(strip=True) if soup.title else ""
    out_hosts, res_hosts, static_paths = Counter(), Counter(), set()
    favicons, anchors = [], 0

    # ① 出站链接（友链/分站）：只统计 a[href]
    for a in soup.find_all("a", href=True):
        anchors += 1
        h = _host(a["href"], base_host)
        if h and h != base_host:
            out_hosts[h] += 1

    # ② 资源域名 + ③ 静态路径
    for tag, attr in (("img", "src"), ("script", "src"), ("link", "href"), ("source", "src")):
        for el in soup.find_all(tag):
            v = el.get(attr)
            if not v:
                continue
            h = _host(v, base_host)
            if h and h != base_host:
                res_hosts[h] += 1
            sp = urlsplit(v if "://" in v or v.startswith("//") else "/" + v.lstrip("/"))
            if RE_STATIC.search(sp.path or ""):
                static_paths.add((sp.path or "").split("?")[0])

    # ④ favicon 声明
    for el in soup.find_all("link"):
        rel = " ".join(el.get("rel") or []).lower()
        if any(k in rel for k in FAVICON_KEYS) and el.get("href"):
            favicons.append(el["href"])

    # 平台线索（只看出现的字符串，不联网）
    markers = {}
    for kw in ("jrzp", "74cms", "no_page_group", "qike", "discuz", "phpcms", "dedecms",
               "zhaopin", "job.shtml", "index.php?m="):
        if kw.lower() in html.lower():
            markers[kw] = html.lower().count(kw.lower())

    # 本站的子域（从首页出站链接里收，0 额外请求）：dhx.xxx.com 这类分站/频道站
    subs = []
    if base_host:
        for h in out_hosts:
            if h != base_host and h.endswith("." + base_host):
                subs.append(h)

    return {
        "file": str(p),
        "subdomains_of_self": sorted(subs),
        "bytes": len(html.encode("utf-8", errors="replace")),
        "title": title,
        "base_host_guess": base_host,
        "anchors": anchors,
        # 判据要用全量：展示层截断曾把 img.jrzp.com / jrzp.com 截掉，导致 3b 误判为否
        "outbound_all": sorted(out_hosts.items(), key=lambda kv: -kv[1]),
        "outbound_hosts": out_hosts.most_common(40),   # 仅用于展示
        "resource_hosts": res_hosts.most_common(20),
        "resource_all": res_hosts.most_common(),
        "static_paths_count": len(static_paths),
        "static_paths": sorted(static_paths)[:200],
        "favicons": favicons,
        "platform_markers": markers,
    }


CITY_PAT = re.compile(r"([\u4e00-\u9fa5]{2,4})(人才网|招聘网|人才市场|人力资源网)")

PROVINCE_CITIES = {
    "浙江": ["杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州",
             "舟山", "台州", "丽水"],
    "江苏": ["南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安",
             "盐城", "扬州", "镇江", "泰州", "宿迁"],
}
# 招聘无关的锚文本特征（培训/学校/政府入口等）
NOISE_ANCHOR = ("培训", "学校", "学院", "大学", "教育", "公共服务", "政务", "政府",
                "app", "APP", "下载", "公众号")


def resolve_city(path, province=None, base_host=""):
    """按**锚文本**识别城市站（域名拼音只作辅助，不作判据）。

    规则（指令 §二）：
      1  取 <a> 锚文本，用 CITY_PAT 抽"城市名 + 人才网/招聘网"
      2  城市名必须在目标省行政区划表里（给了 province 才校验）
      3  域名拼音只辅助，不判
      4  无锚文本的外链 → 丢弃
      5  锚文本与招聘无关（培训/学校/政务…）→ 丢弃

    返回 (命中列表, 丢弃列表)；每条含 domain / anchor / city / reason。
    """
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    keep, drop = [], []
    seen = set()
    for a in soup.find_all("a", href=True):
        u = (a.get("href") or "").strip()
        if not u or u.startswith(("#", "javascript:", "data:", "mailto:", "tel:")):
            continue
        if u.startswith("//"):
            u = "http:" + u
        if u.startswith("/"):
            continue                      # 站内链接不是"城市站"
        host = urlsplit(u).netloc.lower().split(":")[0]
        if not host or not RE_DOMAIN.match(host) or host == base_host:
            continue
        if host in seen:
            continue
        seen.add(host)

        anchor = a.get_text(" ", strip=True) or (a.get("title") or "")
        m = CITY_PAT.search(anchor or "")
        if not m:
            drop.append({"domain": host, "anchor": anchor[:20],
                         "city": "", "reason": "无锚文本/锚文本无城市形态"})
            continue
        city = m.group(1)
        if any(k in anchor for k in NOISE_ANCHOR):
            drop.append({"domain": host, "anchor": anchor[:20], "city": city,
                         "reason": "锚文本与招聘无关"})
            continue
        if province:
            if city not in PROVINCE_CITIES.get(province, []):
                drop.append({"domain": host, "anchor": anchor[:20], "city": city,
                             "reason": "不在 %s 行政区划表" % province})
                continue
        keep.append({"domain": host, "anchor": anchor[:20], "city": city,
                     "reason": "锚文本命中"})
    return keep, drop


def guess_base(path):
    """从 HTML 里猜本站域名（canonical/og:url/绝对链接），猜不到就空。"""
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    for pat in (r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
                r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat, html, re.I)
        if m:
            h = urlsplit(m.group(1)).netloc.lower().split(":")[0]
            if h:
                return h
    # 不再"取页面里第一个 URL"当本站：那会把第三方 CDN 误当本站（实测把苍南判成 www.jrzp.com）
    return ""


def compare(a, b):
    ra, rb = analyze(a, guess_base(a)), analyze(b, guess_base(b))
    ha = {h for h, _ in ra["outbound_hosts"]}
    hb = {h for h, _ in rb["outbound_hosts"]}
    pa, pb = set(ra["static_paths"]), set(rb["static_paths"])
    rha = {h for h, _ in ra["resource_hosts"]}
    rhb = {h for h, _ in rb["resource_hosts"]}
    print("A:", Path(a).name, "| base:", ra["base_host_guess"], "| 出站域名", len(ha),
          "| 资源域名", len(rha), "| 静态路径", len(pa))
    print("B:", Path(b).name, "| base:", rb["base_host_guess"], "| 出站域名", len(hb),
          "| 资源域名", len(rhb), "| 静态路径", len(pb))
    print()
    print("出站域名交集: %d  %s" % (len(ha & hb), sorted(ha & hb)[:6]))
    print("资源域名交集: %d  %s" % (len(rha & rhb), sorted(rha & rhb)[:6]))
    print("静态路径交集: %d  %s" % (len(pa & pb), sorted(pa & pb)[:6]))
    if pa:
        print("静态路径重合度(A 视角): %.1f%%" % (100.0 * len(pa & pb) / len(pa)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html", nargs="?")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--expect", metavar="FILE",
                    help="已知答案清单（一行一个域名）→ 报命中/漏掉，v13 验收用")
    ap.add_argument("--base", default="", help="本站域名（用于排除自身链接）")
    ap.add_argument("--json", default=None)
    ap.add_argument("--cities", metavar="PROVINCE",
                    help="按锚文本抽城市站（浙江/江苏），输出命中与丢弃")
    ap.add_argument("--base-host", default="")
    args = ap.parse_args()

    if args.compare:
        return compare(*args.compare)
    if not args.html:
        print(__doc__)
        return 2

    if args.cities:
        keep, drop = resolve_city(args.html, args.cities, args.base_host)
        print("按锚文本识别 %s 城市站：命中 %d / 丢弃 %d" % (args.cities, len(keep), len(drop)))
        for x in keep:
            print("  ✅ %-26s %-20s %s" % (x["domain"], x["anchor"], x["city"]))
        print("  丢弃：")
        for x in drop[:12]:
            print("     ❌ %-26s %-20s %s" % (x["domain"], x["anchor"], x["reason"]))
        if args.json:
            Path(args.json).write_text(json.dumps({"keep": keep, "drop": drop},
                                                ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    r = analyze(args.html, args.base or guess_base(args.html))
    print("文件 %s（%d 字节）" % (Path(r["file"]).name, r["bytes"]))
    print("标题 %s" % r["title"][:60])
    print("本站猜测 %s | a 标签 %d" % (r["base_host_guess"] or "(未知)", r["anchors"]))
    print()
    print("出站域名 top10:", r["outbound_hosts"][:10])
    print("资源域名 top8 :", r["resource_hosts"][:8])
    print("静态路径     : %d 个" % r["static_paths_count"])
    print("favicon 声明 :", r["favicons"] or "无")
    print("平台线索     :", r["platform_markers"] or "无")

    if args.expect:
        want = [x.strip().lower() for x in Path(args.expect).read_text(encoding="utf-8").splitlines()
                if x.strip() and not x.startswith("#")]
        hosts = [h for h, _ in r["outbound_hosts"]]
        base = (r.get("base_host_guess") or "").lower()
        self_hit = [w for w in want if base and (w in base or base.endswith(w))]
        rest = [w for w in want if w not in self_hit]
        hit = [w for w in rest if any(w in h for h in hosts)]
        miss = [w for w in rest if w not in hit]
        print()
        print("回测：已知答案 %d 条 → 出站命中 %d / 自身 %d（按设计排除）/ 漏掉 %d"
              % (len(want), len(hit), len(self_hit), len(miss)))
        if self_hit:
            print("  自身（不算漏）:", self_hit)
        if miss:
            print("  漏掉:", miss)
        extra = [h for h in hosts if not any(w in h for w in want)]
        print("  额外发现（不在答案里）:", extra)

    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print("JSON →", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())