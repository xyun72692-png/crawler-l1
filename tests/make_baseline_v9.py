# -*- coding: utf-8 -*-
"""
建立 _baseline_v9_stageA（阶段A v9：doctor + registry 校验，143 → 149 项测试）。

v1~v8 原样保留，一个字节都不动。

与 v8 的差别：
    * 新增 `crawlers/doctor.py`：独立抓后体检（8 项检查，0=PASS/1=WARN/2=FAIL）
      ——crawler.py 一行未改，MD5 与 v8 完全一致
    * 新增 `tools/check_registry.py`：站点清单校验（结构/字段/status/模块存在性）
    * `sites/registry.json` 定稿：25 条，已接入 2 / 待接入 3 / blocked 5 / 不相关 15
    * 新增用例 144–149：doctor 四份已知报告回放 + anomalies/字段率构造用例 + registry 校验
    * 测试 143 → 149 项

注意：doctor.py 的"页数自洽"判据是
    pages_ok + pages_skipped == pages_effective
    且 truncated=False 时还要求 pages_effective == pages_declared
（显式 --pages 分段时 effective < declared 属正常，不能判 WARN）

用法：
    python tests\\make_baseline_v9.py
"""
import csv
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AGENT = Path(r"D:\agent-work")
PREV = AGENT / "crawlers" / "_baseline_v8_stageB"
V9 = AGENT / "crawlers" / "_baseline_v9_stageA"

CODE_FILES = [
    "crawler.py", "clean.py", "doctor.py",
    "sites/foodlaw.py", "sites/mock.py", "sites/mockdetail.py",
    "sites/mocknext.py", "sites/mockjson.py", "sites/mockattach.py",
    "sites/mockspa.py", "sites/mocksoft.py", "sites/mockra.py",
    "sites/mockref.py", "sites/mocktotal.py", "sites/mockprobe.py",
    "sites/mockstates.py", "sites/mocknonext.py", "sites/_common.py",
    "sites/quotes.py", "sites/wzrc_all.py", "sites/wzrc_inc.py",
    "sites/yqwzrc.py", "sites/yqwzrc_wage.py", "sites/yqrc.py",
]
TEST_FILES = [
    "test_crawler.py", "mock_site.py", "baseline_snapshot.py",
    "baseline_compare.py", "test_baseline_guard.py", "verify_baseline.py",
    "test_parse_detail_offline.py", "compare_detail_paths.py",
    "probe_spa.py", "fix_attachment_names.py",
    "make_baseline_v2.py", "make_baseline_v3.py", "make_baseline_v4.py",
    "make_baseline_v5.py", "make_baseline_v6.py", "make_baseline_v7.py",
    "make_baseline_v8.py", "make_baseline_v9.py",
]
SCRIPT_FILES = ["probe_pagesize.py"]
# v9 新增：不在 crawlers/ 或 tests/ 下、但属于本版交付物的文件
EXTRA_FILES = [
    ("tools/check_registry.py", "tools/check_registry.py"),
    ("sites/registry.json", "sites/registry.json"),
]
FROM_PREV = [
    "samples/_foodlaw_list1.html", "samples/_foodlaw_detail1.html",
    "samples/_foodlaw_samples.json",
    "data/foodlaw.jsonl", "data/quotes.jsonl", "data/books.jsonl",
    "artifacts/foodlaw_clean_20261110-142932.csv",
    "artifacts/foodlaw_clean_20261110-142932.json",
    "artifacts/foodlaw_clean_20261110-142932.xlsx",
    "artifacts/report-foodlaw-20261110-142827-597.json",
    "artifacts/report-foodlaw-20261110-142827-597.md",
]
CURRENT_TESTS_LOG = ("artifacts/_baseline_tests.log", "logs/_crawler_tests_latest.txt")


def md5_of(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not PREV.exists():
        print("上一版不存在：%s" % PREV)
        return 2
    for sub in ("code", "tests", "scripts", "samples", "data", "artifacts", "tools", "sites"):
        p = V9 / sub
        if p.exists():
            shutil.rmtree(p)
    old_man = V9 / "manifest.csv"
    if old_man.exists():
        old_man.unlink()
    for sub in ("code/sites", "tests", "scripts", "samples", "data", "artifacts", "tools", "sites"):
        (V9 / sub).mkdir(parents=True, exist_ok=True)

    rows, problems = [], []

    def add(rel, src, src_rel):
        dst = V9 / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        hs, hd = md5_of(src), md5_of(dst)
        if hs != hd:
            problems.append("哈希不一致: %s" % rel)
        rows.append({
            "rel": rel, "src_rel": src_rel,
            "bytes": dst.stat().st_size,
            "lastwrite": datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "md5_source": hs, "md5_copy": hd,
            "verify": "OK" if hs == hd else "MISMATCH",
        })

    for f in CODE_FILES:
        src = AGENT / "crawlers" / f
        if not src.exists():
            problems.append("缺源文件: crawlers/%s" % f)
            continue
        add("code/" + f, src, "crawlers/" + f)

    for f in TEST_FILES:
        src = AGENT / "tests" / f
        if not src.exists():
            problems.append("缺源文件: tests/%s" % f)
            continue
        add("tests/" + f, src, "tests/" + f)

    for f in SCRIPT_FILES:
        src = AGENT / "scripts" / f
        if not src.exists():
            problems.append("缺源文件: scripts/%s" % f)
            continue
        add("scripts/" + f, src, "scripts/" + f)

    for rel, src_rel in EXTRA_FILES:
        src = AGENT / src_rel
        if not src.exists():
            problems.append("缺源文件: %s" % src_rel)
            continue
        add(rel, src, src_rel)

    for rel in FROM_PREV:
        src = PREV / rel
        if not src.exists():
            problems.append("上一版里缺: %s" % rel)
            continue
        add(rel, src, "crawlers/_baseline_v8_stageB/" + rel)

    rel, src_rel = CURRENT_TESTS_LOG
    src = AGENT / src_rel
    if src.exists():
        add(rel, src, src_rel)
    else:
        problems.append("缺当前测试日志: %s" % src_rel)

    with open(V9 / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "src_rel", "bytes", "lastwrite",
                                          "md5_source", "md5_copy", "verify"])
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["rel"]):
            w.writerow(r)

    total = sum(r["bytes"] for r in rows)
    print("=" * 66)
    print("_baseline_v9_stageA 已建立")
    print("=" * 66)
    for r in sorted(rows, key=lambda x: x["rel"]):
        print("  %-58s %8d  %s" % (r["rel"], r["bytes"], r["verify"]))
    print("-" * 66)
    print("条目 %d / 字节 %d (%.1f KB)" % (len(rows), total, total / 1024.0))
    if problems:
        print("!! 问题 %d 个：" % len(problems))
        for p in problems:
            print("   " + p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())