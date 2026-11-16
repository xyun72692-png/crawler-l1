# -*- coding: utf-8 -*-
"""
校验基线副本有没有腐坏。

判定模型（沿用 verify-snapshot.ps1 的结论，别再改回去）：
    manifest.csv 里的 md5_source 是【唯一基准】。
    副本 MD5 ≠ manifest  → 快照失效（exit 1）
    manifest 里 md5 为空 → 无法验证（exit 3）
    副本文件缺失         → 快照失效（exit 1）
    源文件缺失 / 源与 manifest 不符 → 只报告，默认不失败（--check-source 时才报告，--strict 才失败）

为什么不做"源 vs 副本"比较：
    那样会漏掉两种情况 —— 源和副本被同时改成一样、manifest 本身写错。
    manifest 才是基线，副本必须向它看齐。

用法：
    python tests\\verify_baseline.py
    python tests\\verify_baseline.py --sample 5
    python tests\\verify_baseline.py --check-source --strict

退出码：0 有效 / 1 损坏 / 2 参数问题 / 3 无法验证
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

BASE = Path(os.environ.get("BASELINE_DIR") or (Path(__file__).resolve().parent.parent / "crawlers" / "_baseline_v14_13_19"))
AGENT = Path(os.environ.get("BASELINE_AGENT") or Path(__file__).resolve().parent.parent)

# manifest 里的 rel 是相对基线的路径，还原成源路径要按这个映射
SRC_MAP = {
    "code/crawler.py":                 "crawlers/crawler.py",
    "code/clean.py":                   "crawlers/clean.py",
    "code/sites/foodlaw.py":           "crawlers/sites/foodlaw.py",
    "code/sites/mock.py":              "crawlers/sites/mock.py",
    "code/sites/quotes.py":            "crawlers/sites/quotes.py",
    "tests/test_crawler.py":           "tests/test_crawler.py",
    "tests/mock_site.py":              "tests/mock_site.py",
    "tests/verify_foodlaw.py":         "tests/verify_foodlaw.py",
    "tests/check_exports.py":          "tests/check_exports.py",
    "tests/baseline_snapshot.py":      "tests/baseline_snapshot.py",
    "tests/baseline_compare.py":       "tests/baseline_compare.py",
    "tests/test_baseline_guard.py":    "tests/test_baseline_guard.py",
    "samples/_foodlaw_list1.html":     "tests/_foodlaw_list1.html",
    "samples/_foodlaw_detail1.html":   "tests/_foodlaw_detail1.html",
    "samples/_foodlaw_samples.json":   "tests/_foodlaw_samples.json",
    "data/foodlaw.jsonl":              "data/raw/foodlaw.jsonl",
    "data/quotes.jsonl":               "data/raw/quotes.jsonl",
    "data/books.jsonl":                "data/raw/books.jsonl",
    "artifacts/foodlaw_clean_20261110-142932.csv":  "out/foodlaw_clean_20261110-142932.csv",
    "artifacts/foodlaw_clean_20261110-142932.json": "out/foodlaw_clean_20261110-142932.json",
    "artifacts/foodlaw_clean_20261110-142932.xlsx": "out/foodlaw_clean_20261110-142932.xlsx",
    "artifacts/report-foodlaw-20261110-142827-597.json": "out/reports/report-foodlaw-20261110-142827-597.json",
    "artifacts/report-foodlaw-20261110-142827-597.md":   "out/reports/report-foodlaw-20261110-142827-597.md",
    "artifacts/_baseline_tests.log":   "logs/_baseline_tests.log",
}


# 三份活文档，不属于"冻结内容"，多余文件检查里要排除
LIVE_DOCS = {"manifest.csv", "baseline.md", "baseline-metrics.json"}


def kind_of(row):
    """条目类型：code / data。

    优先读 manifest 的 kind 列；老 manifest 没有这一列时按路径推导，
    这样旧基线也能立刻享受"data 不判失败"的行为。
    """
    k = (row.get("kind") or "").strip().lower()
    if k in ("code", "data"):
        return k
    rel = (row.get("rel") or "").replace("\\", "/")
    if rel.startswith("code/"):
        return "code"
    if rel.startswith("tools/") and rel.endswith(".py"):
        return "code"
    if rel.startswith("tests/") and not rel.startswith("tests/data/"):
        return "code"
    return "data"


def json_ok(path):
    try:
        json.loads(Path(path).read_text(encoding="utf-8"))
        return True, ""
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:80])


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0,
                    help="只抽检 N 个文件（0=全部）")
    ap.add_argument("--check-source", action="store_true",
                    help="额外检查源文件是否还在、是否与 manifest 一致")
    ap.add_argument("--strict", action="store_true",
                    help="源文件漂移也算失败（默认只报告）")
    args = ap.parse_args()

    man_path = BASE / "manifest.csv"
    if not man_path.exists():
        print("manifest.csv 不存在：%s" % man_path)
        return 2

    with open(man_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("manifest.csv 是空的")
        return 2

    if args.sample and 0 < args.sample < len(rows):
        rows = rows[: args.sample]

    print("=" * 70)
    print("基线校验：%s" % BASE)
    print("共 %d 个条目%s" % (len(rows), "（抽检）" if args.sample else ""))
    print("=" * 70)

    bad, unverifiable, missing = [], [], []
    src_drift, src_missing = [], []
    code_drift, data_drift, data_invalid = [], [], []

    for r in rows:
        rel = (r.get("rel") or "").replace("\\", "/")
        expect = (r.get("md5_source") or "").strip()
        copy_path = BASE / rel
        if not copy_path.exists():
            missing.append(rel)
            continue
        if not expect:
            unverifiable.append(rel)
            continue
        got = md5_of(copy_path)
        if got.lower() != expect.lower():
            bad.append((rel, expect, got))

        if args.check_source:
            # manifest 新增了 src_rel 列时优先用它；老 manifest 退回映射表
            src_rel = (r.get("src_rel") or "").replace("\\", "/").strip() or SRC_MAP.get(rel)
            if not src_rel:
                continue
            src = AGENT / src_rel
            kind = kind_of(r)
            if not src.exists():
                src_missing.append(rel)
            elif md5_of(src).lower() != expect.lower():
                src_drift.append(rel)
                (data_drift if kind == "data" else code_drift).append(rel)
            if kind == "data" and src.exists() and str(src).lower().endswith(".json"):
                okj, err = json_ok(src)
                if not okj:
                    data_invalid.append((rel, err))

    for rel in missing:
        print("  ✗ 副本缺失: %s" % rel)
    for rel, e, g in bad:
        print("  ✗ 副本被改: %s" % rel)
        print("      manifest: %s" % e)
        print("      现在    : %s" % g)
    for rel in unverifiable:
        print("  ? manifest 无哈希，无法验证: %s" % rel)
    for rel in src_missing:
        print("  ~ 源文件已不存在（不影响基线有效性）: %s" % rel)
    for rel in code_drift:
        print("  ~ 源文件与基线不同（code）: %s" % rel)
    for rel in data_drift:
        print("  ~ 源文件与基线不同（data，仅报告）: %s" % rel)
    for rel, err in data_invalid:
        print("  ✗ data 文件不是合法 JSON（数据坏了，不能只报告）: %s" % rel)
        print("      %s" % err)

    # ---- 多余文件检查 ----
    # 为什么要有：2026-11-10 我跑离线解析测试时，importlib 在
    # _baseline_v1\code\sites\ 下生成了一个 __pycache__\foodlaw.cpython-312.pyc，
    # 基线目录被"污染"了而没有任何提示。那时 verify 只查 manifest 里的条目，
    # 根本看不到多出来的东西。
    known = {(r.get("rel") or "").replace("\\", "/") for r in rows}
    extras = []
    for p in BASE.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(BASE).as_posix()
        if rel in known or rel in LIVE_DOCS:
            continue
        extras.append(rel)
    for rel in sorted(extras):
        print("  ~ 基线目录里有多余文件（不属冻结内容）: %s" % rel)

    print("-" * 70)
    if unverifiable and not bad and not missing:
        print("结论：无法验证（%d 个条目没有哈希）" % len(unverifiable))
        return 3
    if bad or missing:
        print("结论：快照已损坏（改坏 %d / 缺失 %d，共 %d 条）"
              % (len(bad), len(missing), len(rows)))
        return 1
    if data_invalid:
        print("结论：data 文件解析失败（%d 个）—— 数据坏了，基线不能放行" % len(data_invalid))
        return 1
    if extras and args.strict:
        print("结论：副本完好，但有 %d 个多余文件（--strict 下算失败）：%s"
              % (len(extras), ", ".join(sorted(extras))))
        return 1
    if code_drift and args.strict:
        print("结论：副本完好，但 code 源文件与基线不同（%d 个），--strict 下算失败"
              % len(code_drift))
        return 1
    print("结论：副本完好（%d/%d 一致%s%s%s）"
          % (len(rows) - len(unverifiable), len(rows),
             "；code 漂移 %d 个%s" % (len(code_drift), "（--strict 失败）" if code_drift and args.strict else "（仅报告）") if code_drift else "",
             "；data 漂移 %d 个（仅报告）" % len(data_drift) if data_drift else "",
             "；多余文件 %d 个（仅报告）" % len(extras) if extras else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())