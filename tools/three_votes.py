# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
v13 三票制 v3（平台与皮肤分轴）。

分轴原则（R6 复核后定稿）：
    平台 = 你在用谁家的资源 → **看平台资源域名引用数**（>=20 判同平台），二值，不投票
    皮肤 = 你用的是哪一代模板 → 路径数 + favicon → A / B / unknown
    三票 = 只用于**皮肤内部确认**（robots / favicon / 出站域名），不再用于判平台

三票（皮肤确认用，全是"是/否"）：
    票1 robots.txt 字节相同     票2 favicon 字节相同     票3 出站域名 3a 集合相等 / 3b 交集>=2 且平台域相交

皮肤分代：
    A 代 = 路径 >= 120 且 favicon == 0de05b2a
    B 代 = 路径 <= 110 且非 A 图标
    unknown = 其余

用法：
    python tools\\three_votes.py --a cangnan --b r6_chinajsjob
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True

import fingerprint_offline as fp   # noqa: E402

A_GEN_ICON_MD5 = "0de05b2ab638"
PLATFORM_SUFFIX = ("img.jrzp.com", "jrzp.com")
PLATFORM_REF_MIN = 20


def md5(b):
    return hashlib.md5(b).hexdigest()


def collect(raw, prefix):
    raw = Path(raw)
    out = {}
    for kind, suffix in (("robots", "_robots.txt"), ("home", "_home.html"),
                         ("favicon", "_favicon.bin")):
        p = raw / ("_probe_%s%s" % (prefix, suffix))
        out[kind] = p if p.exists() else None
    return out


def is_image(b):
    return b[:4] in (b"\x00\x00\x01\x00", b"\x89PNG", b"GIF8")


def plat_core(hosts):
    out = set()
    for h in hosts:
        for p in PLATFORM_SUFFIX:
            if h == p or h.endswith("." + p):
                out.add(p)
    return out


def detect_platform(analysis):
    """平台 = 平台资源域名（img.jrzp.com / jrzp.com 系）的引用次数；>=20 判同平台。"""
    refs = 0
    for h, n in (analysis.get("resource_all") or analysis.get("resource_hosts") or []):
        if plat_core([h]):
            refs += n
    if refs < PLATFORM_REF_MIN:
        refs2 = 0
        for h, n in (analysis.get("outbound_all") or analysis.get("outbound_hosts") or []):
            if plat_core([h]):
                refs2 += n
        refs = max(refs, refs2)
    return ("jrzp", refs) if refs >= PLATFORM_REF_MIN else ("unknown", refs)


def template_gen(paths, favicon_md5):
    if paths is None:
        return "unknown"
    is_a = bool(favicon_md5) and favicon_md5.startswith(A_GEN_ICON_MD5)
    if paths >= 120 and is_a:
        return "A"
    if paths <= 110 and not is_a:
        return "B"
    return "unknown"


def votes(a, b):
    res = {"robots": None, "favicon": None, "outbound": None}
    paths_a = paths_b = None
    fav_a = fav_b = None
    ra = rb = {}

    if a["robots"] and b["robots"]:
        ma, mb = md5(a["robots"].read_bytes()), md5(b["robots"].read_bytes())
        res["robots"] = (ma == mb, ma, mb)

    if a["favicon"] and b["favicon"]:
        ba, bb = a["favicon"].read_bytes(), b["favicon"].read_bytes()
        if is_image(ba) and is_image(bb):
            fav_a, fav_b = md5(ba), md5(bb)
            res["favicon"] = (fav_a == fav_b, fav_a, fav_b)

    jac = None
    if a["home"] and b["home"]:
        ra = fp.analyze(str(a["home"]), "")
        rb = fp.analyze(str(b["home"]), "")
        sa = {h for h, _ in (ra.get("outbound_all") or ra["outbound_hosts"])}
        sb = {h for h, _ in (rb.get("outbound_all") or rb["outbound_hosts"])}
        inter = sa & sb
        paths_a, paths_b = ra["static_paths_count"], rb["static_paths_count"]
        tier_a = bool(sa) and sa == sb
        tier_b = len(inter) >= 2 and bool(plat_core(sa) & plat_core(sb))
        tier = "3a" if tier_a else ("3b" if tier_b else "")
        res["outbound"] = (bool(tier), len(sa), len(sb), len(inter), tier,
                           sorted(plat_core(sa) & plat_core(sb)))
        pa, pb = set(ra["static_paths"]), set(rb["static_paths"])
        union = pa | pb
        jac = (len(pa & pb) / float(len(union))) if union else None

    if fav_a is None and a["favicon"] and is_image(a["favicon"].read_bytes()):
        fav_a = md5(a["favicon"].read_bytes())
    if fav_b is None and b["favicon"] and is_image(b["favicon"].read_bytes()):
        fav_b = md5(b["favicon"].read_bytes())

    yes = sum(1 for v in res.values() if v is not None and v[0] is True)
    voted = sum(1 for v in res.values() if v is not None)

    if yes >= 3:
        skin_note = "皮肤一致（可批量）"
    elif yes == 2:
        skin_note = "皮肤待定（需单独适配）"
    elif yes == 1:
        skin_note = "仅同部署特征"
    else:
        skin_note = "皮肤无共同点"

    gen_a = template_gen(paths_a, fav_a)
    gen_b = template_gen(paths_b, fav_b)
    plat_a = detect_platform(ra) if a["home"] else ("unknown", 0)
    plat_b = detect_platform(rb) if b["home"] else ("unknown", 0)

    return {
        "res": res, "jaccard": jac, "yes": yes, "voted": voted, "skin_note": skin_note,
        "gen_a": gen_a, "paths_a": paths_a, "gen_b": gen_b, "paths_b": paths_b,
        "fav_a": fav_a, "fav_b": fav_b,
        "plat_a": plat_a, "plat_b": plat_b,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(_HOME / "data" / "raw"))
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    a, b = collect(args.raw, args.a), collect(args.raw, args.b)
    d = votes(a, b)
    res = d["res"]

    print("A=%s  B=%s" % (args.a, args.b))
    print("-" * 66)
    r = res["robots"]
    print("票1 robots  : %s" % ("未投" if r is None else
                            ("✅ %s" % r[1][:12] if r[0] else "❌ %s vs %s" % (r[1][:12], r[2][:12]))))
    f = res["favicon"]
    print("票2 favicon : %s" % ("未投（缺/非图片）" if f is None else
                             ("✅ %s" % f[1][:12] if f[0] else "❌ %s vs %s" % (f[1][:12], f[2][:12]))))
    o = res["outbound"]
    if o is None:
        print("票3 出站域名: 未投")
    else:
        print("票3 出站域名: %s%s  %d vs %d 交集 %d  平台核心=%s"
              % ("✅ " if o[0] else "❌ ", o[4] or "-", o[1], o[2], o[3], o[5] or "-"))
    print("-" * 66)
    print("平台（不投票，看资源引用）：A=%s(%d 次)  B=%s(%d 次)"
          % (d["plat_a"][0], d["plat_a"][1], d["plat_b"][0], d["plat_b"][1]))
    print("皮肤：A=%s(%s 路径, 图标 %s)  B=%s(%s 路径, 图标 %s)"
          % (d["gen_a"], d["paths_a"], (d["fav_a"] or "-")[:8],
             d["gen_b"], d["paths_b"], (d["fav_b"] or "-")[:8]))
    print("皮肤一致性：%d/%d 票（%s）   Jaccard=%s"
          % (d["yes"], d["voted"], d["skin_note"],
             "%.3f" % d["jaccard"] if d["jaccard"] is not None else "-"))

    if args.json:
        Path(args.json).write_text(json.dumps({
            "a": args.a, "b": args.b,
            "platform_a": d["plat_a"][0], "platform_refs_a": d["plat_a"][1],
            "platform_b": d["plat_b"][0], "platform_refs_b": d["plat_b"][1],
            "gen_a": d["gen_a"], "paths_a": d["paths_a"],
            "gen_b": d["gen_b"], "paths_b": d["paths_b"],
            "votes_yes": d["yes"], "voted": d["voted"], "skin_note": d["skin_note"],
            "jaccard": d["jaccard"],
            "tickets": {k: (v[0] if v else None) for k, v in res.items()},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())