#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量 identify：把 out/candidates.csv 里的 pending 候选逐站判一遍。

预算纪律：
  · 单站 **1 个请求**（只取首页；省掉 robots，WAF 同 MD5 那条规则在批量阶段不判）
  · 站间随机 3~5 秒
  · 断点：已判过的域名记在 out/identify_batch_state.json，重跑自动跳过
  · 结果写 out/candidates_identified.csv + out/identify_batch_cards.json

用法：
    python tools/identify_batch.py --in out/candidates.csv --limit 40
    python tools/identify_batch.py --resume            # 跳过已判过的
"""

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.dont_write_bytecode = True

import identify as ID  # noqa: E402

STATE = ROOT / "out" / "identify_batch_state.json"
OUT_CSV = ROOT / "out" / "candidates_identified.csv"
OUT_JSON = ROOT / "out" / "identify_batch_cards.json"

COLS = ["城市", "域名", "通道", "形态", "状态", "能力", "置信度", "预估量", "证据摘要", "下一步"]


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def ID_HEADERS():
    return {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=str(ROOT / "out" / "candidates.csv"))
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--max-requests", type=int, default=1)
    ap.add_argument("--delay", type=float, nargs=2, default=(3.0, 5.0))
    ap.add_argument("--resume", action="store_true", help="跳过 state 里已判过的域名")
    ap.add_argument("--scheme", default="https", choices=["https", "http"])
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--only", default=None,
                    help="只重判这些域名（逗号分隔）；配合 --resume 用")
    ap.add_argument("--save-html", action="store_true",
                    help="把取到的首页存到 out/_ident_html/<host>.html 供离线复核")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.src, encoding="utf-8-sig")))
    if args.only:
        want = {x.strip().lower() for x in args.only.split(",") if x.strip()}
        rows = [r for r in rows if (r.get("域名") or "").strip().lower() in want]
    rows = rows[: args.limit]
    st = load_state()
    done, cards = 0, []

    print("待判 %d 个站点；单站 ≤%d 请求，间隔 %.1f~%.1f 秒"
          % (len(rows), args.max_requests, args.delay[0], args.delay[1]))

    for i, r in enumerate(rows, 1):
        host = (r.get("域名") or "").strip()
        if not host:
            continue
        if args.resume and host in st:
            print("  [%2d/%d] %-32s 跳过（已判：%s）" % (i, len(rows), host, st[host].get("channel")))
            cards.append(st[host])
            continue
        url = (args.scheme or "https") + "://" + host + "/"
        time.sleep(random.uniform(*args.delay))
        card = ID.identify(url, allow_network=True, max_requests=args.max_requests,
                           timeout=args.timeout)
        if args.save_html and card.get("bytes"):
            # 再取一次不划算：直接把证据里能拿到的地址重取并存盘（只在显式要求时）
            import requests as _rq
            try:
                rr = _rq.get(url, headers=ID_HEADERS(), timeout=args.timeout)
                d = ROOT / "out" / "_ident_html"
                d.mkdir(parents=True, exist_ok=True)
                (d / (host.replace(":", "_") + ".html")).write_bytes(rr.content)
            except Exception:
                pass
        card["city_from_csv"] = r.get("城市") or ""
        st[host] = card
        save_state(st)
        done += 1
        print("  [%2d/%d] %-32s %-9s %-10s %-11s %-6s req=%d %s"
              % (i, len(rows), host, card["status"], card["form"] or "-",
                 card["channel"], card["capability"], card["requests_made"],
                 (card["evidence"][0] if card["evidence"] else "")[:46]))
        cards.append(card)

    # ---- 汇总 CSV ----
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for c in cards:
            w.writerow({
                "城市": c.get("city_from_csv") or "-",
                "域名": c["host"],
                "通道": c["channel"],
                "形态": c["form"] or "-",
                "状态": c["status"],
                "能力": c["capability"],
                "置信度": c["confidence"],
                "预估量": c["est_volume"],
                "证据摘要": "；".join(c["evidence"])[:120],
                "下一步": c["next_step"][:90],
            })
    OUT_JSON.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 汇总（本轮新判 %d，累计 %d）=====" % (done, len(cards)))
    by_ch = Counter(c["channel"] for c in cards)
    by_cap = Counter(c["capability"] for c in cards)
    for k, v in by_ch.most_common():
        print("  通道 %-12s %d" % (k, v))
    print("  ----")
    for k, v in by_cap.most_common():
        print("  能力 %-12s %d" % (k, v))
    print("\n可抓的（capability=ok）：")
    for c in cards:
        if c["capability"] == "ok":
            print("  %-32s %-10s %s" % (c["host"], c["channel"], c["next_step"][:60]))
    print("\n→", OUT_CSV)
    print("→", OUT_JSON)
    return 0


if __name__ == "__main__":
    sys.exit(main())