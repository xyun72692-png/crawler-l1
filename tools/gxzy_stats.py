# -*- coding: utf-8 -*-
"""
国学资源网 · 六爻清单统计（0 请求，只读 data/raw/gxzy_liuyao.jsonl）

用法：
    python tools\\gxzy_stats.py                    # 基础统计
    python tools\\gxzy_stats.py --ratio            # 追加性价比排名（页/学分）
    python tools\\gxzy_stats.py --json OUT.json    # 机器可读输出
"""
import argparse
import collections
import json
import pathlib
import statistics
import sys

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "gxzy_liuyao.jsonl"
# 充值档位（站方页面：充100得130 / 充200得300 / 充300得600）
TIERS = [(100, 130), (200, 300), (300, 600)]


def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        sys.exit(f"清单不存在：{p}")
    # 纪律：读 jsonl 用 split("\n")，禁用 splitlines()（U+2028 会撕行）
    return [json.loads(l) for l in p.read_text("utf-8").split("\n") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT))
    ap.add_argument("--ratio", action="store_true", help="输出性价比排名")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()

    rows = load(a.file)
    cr = [r["credits"] for r in rows if r.get("credits")]
    mb = [r["size_mb"] for r in rows if r.get("size_mb")]
    pg = [r["pages"] for r in rows if r.get("pages")]
    total_credit = sum(cr)

    out = {
        "records": len(rows),
        "format": dict(collections.Counter(r.get("format") for r in rows)),
        "credits_total": total_credit,
        "credits_median": statistics.median(cr) if cr else None,
        "credits_max": max(cr) if cr else None,
        "size_gb": round(sum(mb) / 1024, 1) if mb else None,
        "pages_labeled": len(pg),
        "pages_total": sum(pg) if pg else 0,
        "price_estimate": {f"充{p}得{g}": round(total_credit * p / g)
                           for p, g in TIERS},
    }
    if a.ratio:
        docs = [r for r in rows if r.get("format") == "文档" and r.get("pages") and r.get("credits")]
        docs.sort(key=lambda r: -(r["pages"] / r["credits"]))
        out["ratio_top"] = [{"title": r["title"], "pages": r["pages"],
                             "credits": r["credits"],
                             "pages_per_credit": round(r["pages"] / r["credits"], 1)}
                            for r in docs[:15]]

    if a.json_out:
        pathlib.Path(a.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
        print("written:", a.json_out)

    print(f"记录 {out['records']} 条 | 格式 {out['format']}")
    print(f"学分合计 {out['credits_total']}（中位 {out['credits_median']}，最高 {out['credits_max']}）")
    print(f"体积合计 {out['size_gb']} GB | 标注页数 {out['pages_labeled']} 条，共 {out['pages_total']:,} 页")
    print("全买估价：" + " / ".join(f"{k} ≈ {v} 元" for k, v in out["price_estimate"].items()))
    if a.ratio:
        print("\n性价比 Top（文档类，页/学分）：")
        for r in out["ratio_top"]:
            print(f"  {r['pages']:>4}页 / {r['credits']:>2}学分 = {r['pages_per_credit']:5.1f}  {r['title'][:46]}")


if __name__ == "__main__":
    main()