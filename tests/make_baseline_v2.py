# -*- coding: utf-8 -*-
"""
建立 _baseline_v2_stage2（阶段 2 冻结点）。

和 v1 的区别：
    v1 = 阶段 0 冻结（16 项测试、没有 mocknext/mockdetail、详情还是旧 detail_hook）
    v2 = 阶段 2 冻结（40 项测试、站点模块含 mocknext/mockdetail、
         详情已通用化 + 补抓、分页两种模式 + 防静默截断）

v1 保持原样不动（阶段 1 的离线对照还要用它的旧 foodlaw.py）。

用法：
    python tests\\make_baseline_v2.py

做的事：
    1. 建 v2 目录（已存在就整个删掉重建，幂等）
    2. 从"当前代码/测试"复制 code/ 和 tests/
    3. 从 v1 复制 samples/ 和 data/ 和 artifacts/（历史证据原样搬过来）
    4. artifacts/_baseline_tests.log 用当前这轮测试输出（40/40）
    5. 算 MD5 写 manifest.csv（带 src_rel 列，verify 靠它定位源文件）
    6. 写 baseline.md
"""
import csv
import hashlib
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AGENT = Path(r"D:\agent-work")
V1 = AGENT / "crawlers" / "_baseline_v1"
V2 = AGENT / "crawlers" / "_baseline_v2_stage2"

# (目标相对路径, 源相对 AGENT 的路径)
CODE_FILES = [
    ("code/crawler.py", "crawlers/crawler.py"),
    ("code/clean.py", "crawlers/clean.py"),
    ("code/sites/foodlaw.py", "crawlers/sites/foodlaw.py"),
    ("code/sites/mock.py", "crawlers/sites/mock.py"),
    ("code/sites/mockdetail.py", "crawlers/sites/mockdetail.py"),
    ("code/sites/mocknext.py", "crawlers/sites/mocknext.py"),
    ("code/sites/quotes.py", "crawlers/sites/quotes.py"),
]
TEST_FILES = [
    ("tests/test_crawler.py", "tests/test_crawler.py"),
    ("tests/mock_site.py", "tests/mock_site.py"),
    ("tests/baseline_snapshot.py", "tests/baseline_snapshot.py"),
    ("tests/baseline_compare.py", "tests/baseline_compare.py"),
    ("tests/test_baseline_guard.py", "tests/test_baseline_guard.py"),
    ("tests/verify_baseline.py", "tests/verify_baseline.py"),
    ("tests/test_parse_detail_offline.py", "tests/test_parse_detail_offline.py"),
    ("tests/compare_detail_paths.py", "tests/compare_detail_paths.py"),
    ("tests/make_baseline_v2.py", "tests/make_baseline_v2.py"),
]
# 这些从 v1 原样搬（历史证据，不重新生成）
FROM_V1 = [
    ("samples/_foodlaw_list1.html", "samples/_foodlaw_list1.html"),
    ("samples/_foodlaw_detail1.html", "samples/_foodlaw_detail1.html"),
    ("samples/_foodlaw_samples.json", "samples/_foodlaw_samples.json"),
    ("data/foodlaw.jsonl", "data/foodlaw.jsonl"),
    ("data/quotes.jsonl", "data/quotes.jsonl"),
    ("data/books.jsonl", "data/books.jsonl"),
    ("artifacts/foodlaw_clean_20261110-142932.csv", "artifacts/foodlaw_clean_20261110-142932.csv"),
    ("artifacts/foodlaw_clean_20261110-142932.json", "artifacts/foodlaw_clean_20261110-142932.json"),
    ("artifacts/foodlaw_clean_20261110-142932.xlsx", "artifacts/foodlaw_clean_20261110-142932.xlsx"),
    ("artifacts/report-foodlaw-20261110-142827-597.json", "artifacts/report-foodlaw-20261110-142827-597.json"),
    ("artifacts/report-foodlaw-20261110-142827-597.md", "artifacts/report-foodlaw-20261110-142827-597.md"),
]
# 用当前这轮的测试日志（v1 里那份是 16/16，早没意义了）
CURRENT_TESTS_LOG = ("artifacts/_baseline_tests.log", "logs/_crawler_tests_latest.txt")


def md5_of(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not V1.exists():
        print("v1 不存在，无法搬运历史证据：%s" % V1)
        return 2
    # 只删"受管内容"，保留 baseline.md / baseline-metrics.json 这两份活文档 —
    # 之前用 rmtree 整个目录，结果每次重建都把 baseline.md 一起删掉，属于坑。
    for sub in ("code", "tests", "samples", "data", "artifacts"):
        p = V2 / sub
        if p.exists():
            shutil.rmtree(p)
    man_old = V2 / "manifest.csv"
    if man_old.exists():
        man_old.unlink()
    for sub in ("code/sites", "tests", "samples", "data", "artifacts"):
        (V2 / sub).mkdir(parents=True, exist_ok=True)

    rows = []
    problems = []

    def add(rel, src):
        dst = V2 / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        hs, hd = md5_of(src), md5_of(dst)
        if hs != hd:
            problems.append("哈希不一致: %s" % rel)
        rows.append({
            "rel": rel,
            "src_rel": str(Path(src).relative_to(AGENT)).replace("\\", "/"),
            "bytes": dst.stat().st_size,
            "lastwrite": __import__("datetime").datetime.fromtimestamp(
                src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "md5_source": hs,
            "md5_copy": hd,
            "verify": "OK" if hs == hd else "MISMATCH",
        })

    for rel, src_rel in CODE_FILES + TEST_FILES:
        src = AGENT / src_rel
        if not src.exists():
            problems.append("缺源文件: %s" % src_rel)
            continue
        add(rel, src)

    for rel, v1_rel in FROM_V1:
        src = V1 / v1_rel
        if not src.exists():
            problems.append("v1 里缺: %s" % v1_rel)
            continue
        # src_rel 指向 v1（这些文件的"源头"就是 v1），verify 的源漂移检查靠它。
        # 注意必须带 crawlers/ 前缀 —— BASELINE_AGENT 是 D:\agent-work 而不是 crawlers\。
        dst = V2 / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        hs, hd = md5_of(src), md5_of(dst)
        rows.append({
            "rel": rel,
            "src_rel": "crawlers/_baseline_v1/%s" % v1_rel,
            "bytes": dst.stat().st_size,
            "lastwrite": __import__("datetime").datetime.fromtimestamp(
                src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "md5_source": hs, "md5_copy": hd,
            "verify": "OK" if hs == hd else "MISMATCH",
        })

    rel, src_rel = CURRENT_TESTS_LOG
    src = AGENT / src_rel
    if src.exists():
        add(rel, src)
    else:
        problems.append("缺当前测试日志: %s" % src_rel)

    man = V2 / "manifest.csv"
    with open(man, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "src_rel", "bytes", "lastwrite",
                                          "md5_source", "md5_copy", "verify"])
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["rel"]):
            w.writerow(r)

    total = sum(r["bytes"] for r in rows)
    print("=" * 66)
    print("_baseline_v2_stage2 已建立")
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
    print("manifest.csv 已写：%s" % man)
    return 0


if __name__ == "__main__":
    sys.exit(main())