# -*- coding: utf-8 -*-
"""
建立 _baseline_v5_stage5（阶段 4 收尾：真实附件链路 + 导出链路 + 82 项测试）。

v1/v2/v3/v4 都原样保留。

与 v4 的差别：
    * 去重提前到详情/附件之前；整页全重复时跳过详情与附件
    * 附件阶段异常计入 partial；字段签名改为"本页字段并集"
    * magic 校验支持小分块；clean.py 附件列扁平化（xlsx 可导出）+ --site 参数
    * foodlaw 接入附件解析（真实跑过 1 页：26 个附件 19.2MB 全部 ok）
    * 测试从 73 项增到 82 项

用法：
    python tests\\make_baseline_v5.py

只删受管内容（code/tests/samples/data/artifacts + manifest.csv），
baseline.md / baseline-metrics.json 保留。
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
PREV = AGENT / "crawlers" / "_baseline_v4_stage4"
V5 = AGENT / "crawlers" / "_baseline_v5_stage5"

CODE_FILES = [
    "crawler.py", "clean.py",
    "sites/foodlaw.py", "sites/mock.py", "sites/mockdetail.py",
    "sites/mocknext.py", "sites/mockjson.py", "sites/mockattach.py",
    "sites/quotes.py",
]
TEST_FILES = [
    "test_crawler.py", "mock_site.py", "baseline_snapshot.py",
    "baseline_compare.py", "test_baseline_guard.py", "verify_baseline.py",
    "test_parse_detail_offline.py", "compare_detail_paths.py",
    "make_baseline_v2.py", "make_baseline_v3.py", "make_baseline_v4.py",
    "make_baseline_v5.py",
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
    for sub in ("code", "tests", "samples", "data", "artifacts"):
        p = V5 / sub
        if p.exists():
            shutil.rmtree(p)
    old_man = V5 / "manifest.csv"
    if old_man.exists():
        old_man.unlink()
    for sub in ("code/sites", "tests", "samples", "data", "artifacts"):
        (V5 / sub).mkdir(parents=True, exist_ok=True)

    rows, problems = [], []

    def add(rel, src, src_rel):
        dst = V5 / rel
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

    for rel in FROM_PREV:
        src = PREV / rel
        if not src.exists():
            problems.append("上一版里缺: %s" % rel)
            continue
        add(rel, src, "crawlers/_baseline_v4_stage4/" + rel)

    rel, src_rel = CURRENT_TESTS_LOG
    src = AGENT / src_rel
    if src.exists():
        add(rel, src, src_rel)
    else:
        problems.append("缺当前测试日志: %s" % src_rel)

    with open(V5 / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "src_rel", "bytes", "lastwrite",
                                          "md5_source", "md5_copy", "verify"])
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["rel"]):
            w.writerow(r)

    total = sum(r["bytes"] for r in rows)
    print("=" * 66)
    print("_baseline_v5_stage5 已建立")
    print("=" * 66)
    for r in sorted(rows, key=lambda x: x["rel"]):
        print("  %-52s %8d  %s" % (r["rel"], r["bytes"], r["verify"]))
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