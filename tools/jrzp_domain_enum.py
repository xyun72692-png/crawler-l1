# -*- coding: utf-8 -*-
"""
jrzp 域名语法枚举（**0 个 HTTP 请求**，只用 DNS 解析）。

依据（0 请求得出的规律，见 docs\\v13-离线指纹第一版）：
    {city_full}rc.com        cangnanrc / pingyangrc / yongjiarc
    wz{abbr}rc.com           wzlcrc / wzlwrc / wzohrc / wzdtrc / wztsrc / wzyqrc / wzwcrc
    wz{abbr}job.com          wzrajob（瑞安）
    {city_full}job.com       （兜底形态）

两条硬规矩：
  1. **先做召回校验**：用温州 11 个已知域名当答案，生成器必须全部生成出来；
     召回不过就不许拿它去枚举别的省（否则"什么都没找到"会被误读成"没有站"）。
  2. 只做 DNS（socket.getaddrinfo），**不发任何 HTTP**；未解析 ≠ 死站（可能被墙/DNS 抖动），
     所以失败默认重试 2 次，报表里区分 `nxdomain` 与 `error`。

用法：
    python tools\\jrzp_domain_enum.py --recall            # 只跑温州召回校验
    python tools\\jrzp_domain_enum.py --province 浙江 --out out\\zj_candidates.csv
"""

import argparse
import csv
import socket
import sys
from pathlib import Path

# ---------------- 已知答案（温州，jrzp 家族独立域名）----------------
WENZHOU_KNOWN = {
    "cangnanrc.com": ("苍南", "full"),
    "pingyangrc.com": ("平阳", "full"),
    "yongjiarc.com": ("永嘉", "full"),
    "wzwcrc.com": ("文成", "wz_abbr"),
    "wzlcrc.com": ("鹿城", "wz_abbr"),
    "wzlwrc.com": ("龙湾", "wz_abbr"),
    "wzohrc.com": ("瓯海", "wz_abbr"),
    "wzdtrc.com": ("洞头", "wz_abbr"),
    "wztsrc.com": ("泰顺", "wz_abbr"),
    "wzyqrc.com": ("乐清", "wz_abbr"),
    "wzrajob.com": ("瑞安", "wz_abbr_job"),
}

# 温州 12 个县级行政区（龙港尚无已知域名 → 召回不要求）
WENZHOU_ALL = {
    "鹿城": "lucheng", "龙湾": "longwan", "瓯海": "ouhai", "洞头": "dongtou",
    "永嘉": "yongjia", "平阳": "pingyang", "苍南": "cangnan", "文成": "wencheng",
    "泰顺": "taishun", "瑞安": "ruian", "乐清": "yueqing", "龙港": "longgang",
}
WENZHOU_ABBR = {
    "鹿城": "lc", "龙湾": "lw", "瓯海": "oh", "洞头": "dt", "永嘉": "yj",
    "平阳": "py", "苍南": "cn", "文成": "wc", "泰顺": "ts", "瑞安": "ra",
    "乐清": "yq", "龙港": "lg",
}

# ---------------- 浙江 / 江苏：市 + 主要区县（拼音，手写表）------------------
ZHEJIANG = {
    "杭州": "hangzhou", "宁波": "ningbo", "温州": "wenzhou", "嘉兴": "jiaxing",
    "湖州": "huzhou", "绍兴": "shaoxing", "金华": "jinhua", "衢州": "quzhou",
    "舟山": "zhoushan", "台州": "taizhou", "丽水": "lishui",
}
JIANGSU = {
    "南京": "nanjing", "无锡": "wuxi", "徐州": "xuzhou", "常州": "changzhou",
    "苏州": "suzhou", "南通": "nantong", "连云港": "lianyungang", "淮安": "huaian",
    "盐城": "yancheng", "扬州": "yangzhou", "镇江": "zhenjiang", "泰州": "taizhou_js",
    "宿迁": "suqian",
}
# 主要区县（市辖区里经济体量大 / 有独立人才网的常见几个，够试点用）
DISTRICTS = {
    "鄞州": "yinzhou", "余杭": "yuhang", "萧山": "xiaoshan", "慈溪": "cixi",
    "义乌": "yiwu", "诸暨": "zhuji", "温岭": "wenling", "瑞安2": "ruian2",
    "江阴": "jiangyin", "昆山": "kunshan", "张家港": "zhangjiagang", "常熟": "changshu",
    "武进": "wujin", "吴江": "wujiang", "宜兴": "yixing", "丹阳": "danyang",
}

PATTERNS = [
    "{full}rc.com",
    "{full}job.com",
    "wz{abbr}rc.com",      # 只对温州有意义
    "wz{abbr}job.com",
]


def gen_domains(cities, abbrs=None, with_wz=False):
    out = {}
    for name, full in cities.items():
        cands = ["{full}rc.com".format(full=full), "{full}job.com".format(full=full)]
        if with_wz and abbrs:
            cands.append("wz{abbr}rc.com".format(abbr=abbrs.get(name, "")))
            cands.append("wz{abbr}job.com".format(abbr=abbrs.get(name, "")))
        for d in cands:
            if "{abbr}" in d and with_wz and not abbrs.get(name):
                continue
            out.setdefault(d, name)
    return out


def resolve(host, retries=2, timeout=3.0):
    """返回 (状态, 说明)。状态：ok / nxdomain / error。"""
    last = ""
    for _ in range(retries + 1):
        try:
            socket.setdefaulttimeout(timeout)
            infos = socket.getaddrinfo(host, None)
            ips = sorted({i[4][0] for i in infos})
            return "ok", ",".join(ips[:3])
        except socket.gaierror as e:
            last = "gaierror:%s" % e.errno
        except Exception as e:                     # 超时/临时故障
            last = "%s" % type(e).__name__
    return ("nxdomain" if last.startswith("gaierror") else "error"), last


def recall():
    """召回校验：温州已知 11 个域名必须全部能被生成器产出。"""
    doms = gen_domains(WENZHOU_ALL, WENZHOU_ABBR, with_wz=True)
    hit = [d for d in WENZHOU_KNOWN if d in doms]
    miss = [d for d in WENZHOU_KNOWN if d not in doms]
    print("召回校验：生成器共产出 %d 个候选域名" % len(doms))
    print("  已知 11 个 → 命中 %d / 漏掉 %d" % (len(hit), len(miss)))
    if miss:
        print("  漏掉:", miss)
    return len(miss) == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recall", action="store_true")
    ap.add_argument("--province", choices=["浙江", "江苏", "两地"], default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-dns", action="store_true", help="只列候选，不解析")
    args = ap.parse_args()

    if args.recall:
        return 0 if recall() else 1

    if not args.province:
        print(__doc__)
        return 2

    cities = {}
    if args.province in ("浙江", "两地"):
        cities.update(ZHEJIANG)
    if args.province in ("江苏", "两地"):
        cities.update(JIANGSU)
    doms = gen_domains(cities, WENZHOU_ABBR, with_wz=False)
    # 温州自己的 12 个（含待探的龙港）
    doms.update(gen_domains(WENZHOU_ALL, WENZHOU_ABBR, with_wz=True))
    for name, full in DISTRICTS.items():
        doms.setdefault("%src.com" % full.rstrip("2"), name)

    print("候选域名 %d 个（省份=%s）" % (len(doms), args.province))
    rows = []
    for d, owner in sorted(doms.items()):
        if args.no_dns:
            rows.append([d, owner, "not_checked", ""])
            continue
        st, info = resolve(d)
        rows.append([d, owner, st, info])
        if st == "ok":
            print("  ✅ %-28s %-8s %s" % (d, owner, info))

    ok_n = sum(1 for r in rows if r[2] == "ok")
    nx_n = sum(1 for r in rows if r[2] == "nxdomain")
    err_n = sum(1 for r in rows if r[2] == "error")
    print("解析结果：存活 %d / nxdomain %d / 错误 %d（共 %d）"
          % (ok_n, nx_n, err_n, len(rows)))

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["domain", "owner_guess", "dns", "detail"])
            w.writerows(rows)
        print("CSV →", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())