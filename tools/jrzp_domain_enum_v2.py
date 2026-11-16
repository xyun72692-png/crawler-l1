# -*- coding: utf-8 -*-
"""
jrzp 域名语法枚举 v2（**0 个 HTTP 请求**，只用 DNS）。

v2 修的四条（v1 的方法错误，会导致 R6 清单被污染）：
  1. **解析顺序：www.域名 优先，取不到才回落 apex** —— apex 大量是停放页；
  2. **禁止用 apex 做 IP 聚类**（同一 apex IP 上连已知真站 pingyangrc 都在停放）；
  3. **共享 IP 排除**：某个 IP 上挂了 >10 个候选域名 → 判为停放/CDN，**不参与聚类**；
  4. **锚点改成"与已知站 www 的 IP 簇重合"**（温州已知：183.201.233.x / 36.147.23.x）。

另外补了「城市首字母」语法族（`hzrc.com` / `ntrc.com` 这类真实存在），
并修掉 v1 的两个非法名（`taizhou_js` 下划线、`ruian2` 占位）。

已知答案唯一来源：`tools\\golden\\jrzp_wenzhou_known.txt`（不再有两份）。

用法：
    python tools\\jrzp_domain_enum_v2.py --recall
    python tools\\jrzp_domain_enum_v2.py --province 两地 --out out\\v13_enum_v2.csv
"""

import argparse
import csv
import socket
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
GOLDEN = TOOLS / "golden" / "jrzp_wenzhou_known.txt"

SHARED_IP_THRESHOLD = 10      # 一个 IP 上超过这么多候选域名 → 判停放/CDN


# ---------------------------------------------------------------- 已知答案（唯一来源）
def known_domains():
    return [x.strip().lower() for x in GOLDEN.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.startswith("#")]


# ---------------------------------------------------------------- 地名表
WENZHOU = {   # 12 个县级行政区
    "鹿城": ("lucheng", "lc"), "龙湾": ("longwan", "lw"), "瓯海": ("ouhai", "oh"),
    "洞头": ("dongtou", "dt"), "永嘉": ("yongjia", "yj"), "平阳": ("pingyang", "py"),
    "苍南": ("cangnan", "cn"), "文成": ("wencheng", "wc"), "泰顺": ("taishun", "ts"),
    "瑞安": ("ruian", "ra"), "乐清": ("yueqing", "yq"), "龙港": ("longgang", "lg"),
}
ZHEJIANG = {
    "杭州": ("hangzhou", "hz"), "宁波": ("ningbo", "nb"), "温州": ("wenzhou", "wz"),
    "嘉兴": ("jiaxing", "jx"), "湖州": ("huzhou", "hu"), "绍兴": ("shaoxing", "sx"),
    "金华": ("jinhua", "jh"), "衢州": ("quzhou", "qz"), "舟山": ("zhoushan", "zs"),
    "台州": ("taizhou", "tz"), "丽水": ("lishui", "ls"),
}
JIANGSU = {
    "南京": ("nanjing", "nj"), "无锡": ("wuxi", "wx"), "徐州": ("xuzhou", "xz"),
    "常州": ("changzhou", "cz"), "苏州": ("suzhou", "sz"), "南通": ("nantong", "nt"),
    "连云港": ("lianyungang", "lyg"), "淮安": ("huaian", "ha"), "盐城": ("yancheng", "yc"),
    "扬州": ("yangzhou", "yz"), "镇江": ("zhenjiang", "zj"), "泰州": ("taizhou", "tzjs"),
    "宿迁": ("suqian", "sq"),
}
# 主要区县（够试点；名字冲突的就别硬塞缩写）
DISTRICTS = {
    "鄞州": ("yinzhou", "yz2"), "余杭": ("yuhang", "yh"), "萧山": ("xiaoshan", "xs"),
    "慈溪": ("cixi", "cx"), "义乌": ("yiwu", "yw"), "诸暨": ("zhuji", "zj2"),
    "温岭": ("wenling", "wl"), "江阴": ("jiangyin", "jy"), "昆山": ("kunshan", "ks"),
    "张家港": ("zhangjiagang", "zjg"), "常熟": ("changshu", "cs"), "武进": ("wujin", "wj"),
    "吴江": ("wujiang", "wj2"), "宜兴": ("yixing", "yx"), "丹阳": ("danyang", "dy"),
}


def gen(cities, patterns=("full_rc", "abbr_rc", "full_job", "wz_abbr_rc", "wz_abbr_job")):
    """生成候选：{full}rc / {abbr}rc / {full}job / wz{abbr}rc / wz{abbr}job。

    abbr 里带数字的（如 tzjs / yz2 / wj2 / zj2）是**内部区分用的占位**，
    不是真域名，生成时跳过 —— 宁可少造，不造非法域名。
    """
    out = {}
    for name, (full, abbr) in cities.items():
        clean_abbr = "" if any(ch.isdigit() for ch in abbr) else abbr
        cands = {}
        if "full_rc" in patterns:
            cands["%src.com" % full] = "full_rc"
        if "abbr_rc" in patterns and clean_abbr:
            cands["%src.com" % clean_abbr] = "abbr_rc"
        if "full_job" in patterns:
            cands["%sjob.com" % full] = "full_job"
        if "wz_abbr_rc" in patterns and clean_abbr:
            cands["wz%src.com" % clean_abbr] = "wz_abbr_rc"
        if "wz_abbr_job" in patterns and clean_abbr:
            cands["wz%sjob.com" % clean_abbr] = "wz_abbr_job"
        for d, pat in cands.items():
            out.setdefault(d, (name, pat))
    return out


# ---------------------------------------------------------------- DNS
def _ips(host, retries=1, timeout=3.0):
    last = ""
    for _ in range(retries + 1):
        try:
            socket.setdefaulttimeout(timeout)
            return sorted({i[4][0] for i in socket.getaddrinfo(host, None)})
        except socket.gaierror as e:
            last = "nxdomain" if e.errno in (-2, 11001) else "gaierror"
        except Exception:
            last = "error"
    return [] if last == "nxdomain" else ["ERR:%s" % last]


def resolve_best(domain):
    """www 优先，取不到才回落 apex。返回 (which, ips)。"""
    w = _ips("www." + domain)
    if w and not w[0].startswith("ERR:"):
        return "www", w
    a = _ips(domain)
    if a and not a[0].startswith("ERR:"):
        return "apex", a
    return "none", []


def known_clusters(doms):
    """已知站的 www IP 簇（/24 前缀），用于锚定 A 档。"""
    prefixes = set()
    detail = {}
    for d in doms:
        which, ips = resolve_best(d)
        if which == "www":
            for ip in ips:
                detail.setdefault(d, []).append(ip)
                prefixes.add(".".join(ip.split(".")[:3]))
    return prefixes, detail


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recall", action="store_true")
    ap.add_argument("--province", choices=["浙江", "江苏", "两地"], default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    known = known_domains()
    prefixes, kdetail = known_clusters(known)
    print("已知站 %d 个；www IP 簇（/24）: %s" % (len(known), sorted(prefixes)))
    if not prefixes:
        print("!! 已知站 www 全部解析失败，聚类无锚点 → 停止")
        return 1

    if args.recall:
        cands = gen(WENZHOU)
        miss = [d for d in known if d not in cands]
        print("召回：候选 %d 个 → 命中 %d / 漏 %d %s"
              % (len(cands), len(known) - len(miss), len(miss), miss))
        print("龙港候选:", [d for d in cands if cands[d][0] == "龙港"])
        return 0 if not miss else 1

    cities = {}
    if args.province in ("浙江", "两地"):
        cities.update(ZHEJIANG)
    if args.province in ("江苏", "两地"):
        cities.update(JIANGSU)
    cities.update(WENZHOU)
    cities.update(DISTRICTS)
    cands = gen(cities)

    rows = []
    for d, (owner, pat) in sorted(cands.items()):
        which, ips = resolve_best(d)
        rows.append({"domain": d, "owner": owner, "pattern": pat,
                     "which": which, "ips": ",".join(ips)})

    # 共享 IP 统计（只看被当作"主 IP"的那个）
    ip_owner = {}
    for r in rows:
        if r["ips"]:
            ip_owner.setdefault(r["ips"].split(",")[0], set()).add(r["domain"])
    shared = {ip for ip, ds in ip_owner.items() if len(ds) > SHARED_IP_THRESHOLD}

    for r in rows:
        ip = r["ips"].split(",")[0] if r["ips"] else ""
        pref = ".".join(ip.split(".")[:3]) if ip and not ip.startswith("ERR") else ""
        if not ip:
            conf = "D 未解析"
        elif ip in shared:
            conf = "D 共享IP(停放/CDN)"
        elif r["which"] == "apex":
            conf = "C 仅apex(疑似停放)"
        elif pref in prefixes:
            conf = "A 与已知站同簇"
        else:
            conf = "B 独立IP"
        r["confidence"] = conf

    ok = sum(1 for r in rows if r["ips"])
    a_n = sum(1 for r in rows if r["confidence"].startswith("A"))
    print("候选 %d → 解析成功 %d；A 档 %d；共享 IP 排除 %d 个" % (len(rows), ok, a_n, len(shared)))
    print()
    for r in rows:
        if r["confidence"].startswith("A"):
            print("  ★A %-26s %-6s %-10s %s" % (r["domain"], r["owner"], r["which"], r["ips"]))

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["domain", "owner", "pattern", "which", "ips", "confidence"])
            w.writeheader()
            w.writerows(rows)
        print("\nCSV →", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())