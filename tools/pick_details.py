# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
两段式第 2 段的"清单生成器"。

第 1 段：只抓列表（detail 关闭）→ 数据里有 title/company/salary/region/welfare/detail_url
第 2 段：用本工具按规则筛出"值得抓详情"的那些 URL → 交给 crawler.py --detail-urls

为什么值得：foodlaw 这类"列表没正文"的站，全量开详情 = 78 个请求；
先筛再抓通常只剩 20~30 个，既快又少打扰站暴。

用法：
    python tools\\pick_details.py --job wzrc_fullsite_20261112 --keyword 外贸,运营 --out candidates.txt
    python tools\\pick_details.py --job xxx --only-pending --limit 50 --out c.txt
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

RAW = os.environ.get("CRAWLER_OUT_DIR") or str(_HOME / "data" / "raw")


def load_rows(job):
    p = Path(RAW) / ("%s.jsonl" % job)
    if not p.exists():
        raise SystemExit("数据文件不存在：%s（先跑第 1 段列表）" % p)
    rows = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit("数据文件第 %d 行不是合法 JSON（%s）" % (n, e))
    return rows


def salary_floor(raw):
    """取薪资区间下限（元/月）。认 3K-5K/月、3000-5000元、1万-1.5万/月 等。"""
    s = (raw or "").replace(" ", "")
    if not s or "面议" in s:
        return None
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*([KkWw千万]?)", s)
    if not nums:
        return None
    v, unit = nums[0]
    try:
        v = float(v)
    except ValueError:
        return None
    unit = unit.lower()
    if unit == "k":
        v *= 1000
    elif unit == "w" or unit == "万":
        v *= 10000
    elif unit == "千":
        v *= 1000
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keyword", default="", help="岗位名关键词，逗号分隔（命中任意一个即保留）")
    ap.add_argument("--region", default="", help="地区关键词，逗号分隔")
    ap.add_argument("--salary-min", type=float, default=0, help="薪资下限（元/月），0=不限")
    ap.add_argument("--only-pending", action="store_true",
                    help="只要详情还没抓全的（detail_fetch != ok）")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = load_rows(args.job)
    kws = [x.strip() for x in args.keyword.split(",") if x.strip()]
    regs = [x.strip() for x in args.region.split(",") if x.strip()]

    picked, seen = [], set()
    for r in rows:
        url = (r.get("detail_url") or "").strip()
        if not url or url in seen:
            continue
        if args.only_pending and r.get("detail_fetch") == "ok":
            continue
        if kws and not any(k in (r.get("title") or "") for k in kws):
            continue
        if regs and not any(k in (r.get("region") or "") for k in regs):
            continue
        if args.salary_min:
            fl = salary_floor(r.get("salary_raw"))
            if fl is None or fl < args.salary_min:
                continue
        seen.add(url)
        picked.append(url)
        if args.limit and len(picked) >= args.limit:
            break

    out = Path(args.out)
    out.write_text("\n".join(picked) + ("\n" if picked else ""), encoding="utf-8")
    print("总记录 %d 条 → 命中 %d 条 → 写入 %s" % (len(rows), len(picked), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())