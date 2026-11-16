# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
离线解析 golden：用**当前**站点模块把真实样本解析一遍，存成基准。

用途：抽 `sites/_common.py` 之前先冻结"现在的解析结果"，
抽完再跑一次，逐字段对比必须 0 差异（v8 的验收标准）。

用法：
    python tools\\parse_golden.py            # 生成 tools\\golden\\*.json（覆盖）
    python tools\\parse_golden.py --check    # 与已有 golden 对比，0 差异返回 0
"""
import argparse
import importlib
import json
import re
import sys
from pathlib import Path

AGENT = Path(str(_HOME))
RAW = AGENT / "data" / "raw"
GOLD = AGENT / "tools" / "golden"

# 样本 → 站点模块（只映射"样本是哪个站的页面"）
SAMPLES = [
    ("_probe_wzrc.html", "wzrc_all"),
    ("_probe_wzrc_dw_p1.html", "wzrc_all"),
    ("_probe_yqwzrc.html", "yqwzrc"),
    ("_probe_yqwzrc_list.html", "yqwzrc"),
    ("_probe_yqrc_job.html", "yqrc"),
]

BASE = "https://www.wzrc.net/index.php?m=&c=Jobs&a=jobs_list&citycategory=wenzhou&jobtag=147"
PAGE_URL = {
    "_probe_wzrc.html": BASE + "&page=1",
    "_probe_wzrc_dw_p1.html": BASE + "&page=1&sort=rtime",
    "_probe_yqwzrc.html": "https://yq.wzrc.net/index.php?m=&c=Jobs&a=jobs_list&jobtag=147&page=1",
    "_probe_yqwzrc_list.html": "https://yq.wzrc.net/index.php?m=&c=Jobs&a=jobs_list&page=1",
    "_probe_yqrc_job.html": "https://www.yqrc.com/job?page=1",
}


def load_mod(name):
    sys.path.insert(0, str(AGENT / "crawlers"))
    return importlib.import_module("sites." + name)


def snapshot(sample, mod_name):
    html = (RAW / sample).read_text(encoding="utf-8", errors="replace")
    mod = load_mod(mod_name)
    rows = mod.parse_list(html, PAGE_URL[sample])

    # 记录声明总页数（抽 _common 后这一项也必须一模一样）
    pat = (mod.CONFIG or {}).get("total_pages_pattern") or ""
    m = re.search(pat, html) if pat else None
    declared = int(m.group(1)) if m else None

    # 字段按 key 排序，保证可比
    norm = [{k: r.get(k) for k in sorted(r)} for r in rows]
    return {
        "sample": sample,
        "site": mod_name,
        "sample_bytes": len(html.encode("utf-8")),
        "page_url": PAGE_URL[sample],
        "total_pages_pattern": pat,
        "declared_total_pages": declared,
        "cards": len(norm),
        "rows": norm,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只对比，不覆盖")
    a = ap.parse_args()

    GOLD.mkdir(parents=True, exist_ok=True)
    diffs = 0
    print("%-26s %-10s %6s %8s" % ("样本", "站点", "卡片", "声明页数"))
    print("-" * 62)
    for sample, mod_name in SAMPLES:
        cur = snapshot(sample, mod_name)
        print("%-26s %-10s %6d %8s" % (sample, mod_name, cur["cards"],
                                       cur["declared_total_pages"]))
        gf = GOLD / (sample.replace(".html", "") + ".json")
        if a.check:
            if not gf.exists():
                print("   !! 缺 golden：%s" % gf.name)
                diffs += 1
                continue
            old = json.loads(gf.read_text(encoding="utf-8"))
            if old == cur:
                print("   ✅ 0 差异")
            else:
                diffs += 1
                print("   ❌ 有差异")
                for key in ("cards", "declared_total_pages", "total_pages_pattern"):
                    if old.get(key) != cur.get(key):
                        print("      %s: %r -> %r" % (key, old.get(key), cur.get(key)))
                orows, crows = old.get("rows", []), cur.get("rows", [])
                if len(orows) != len(crows):
                    print("      行数: %d -> %d" % (len(orows), len(crows)))
                for i, (orow, crow) in enumerate(zip(orows, crows)):
                    if orow != crow:
                        ks = sorted(set(orow) | set(crow))
                        bad = [k for k in ks if orow.get(k) != crow.get(k)]
                        print("      第 %d 行字段不同: %s" % (i + 1, bad[:6]))
                        for k in bad[:3]:
                            print("         %s: %r -> %r" % (k, orow.get(k), crow.get(k)))
                        break
        else:
            gf.write_text(json.dumps(cur, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8", newline="\n")
            print("   → 已写 %s" % gf.name)

    if a.check:
        print()
        print("结论：%s" % ("0 差异 ✅" if diffs == 0 else "%d 个样本有差异 ❌" % diffs))
        return 0 if diffs == 0 else 1
    print()
    print("golden 已生成：%s" % GOLD)
    return 0


if __name__ == "__main__":
    sys.exit(main())