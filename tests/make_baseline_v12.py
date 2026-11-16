# -*- coding: utf-8 -*-
"""
建立 _baseline_v12（v12 / v12.1：请求闸门）。

v1~v11 原样保留（v11 已被误覆盖，见 _baseline_v11/_DAMAGED.txt），历史指针请看 v10。

这一版的内容：
    * 新增 crawlers/gate.py：滑窗（默认 60s / 12 次）+ 最小间隔抖动 uniform(4.8, 6.5)
      + 单任务预算（200）+ 时长上限（1800s），时间源可注入（测试用假时钟，不 sleep）
    * session_factory() 返回 GatedSession，钩子挂 **Session.send()**（挂 request() 会漏掉每一跳重定向）
    * 报告新增 gate 块：requests_used / actual_rpm / throttled / stopped_by / by_host
    * 
ebuild_seen() 坏行改 fail-closed（BadDataFile → failed/data_file_corrupt）
    * 
obots_rules.crawl_delay() 增加 isfinite + 非负校验
    * 测试 178 → 193

v12.1（本次）追加的四个阶段穿透：
    * 详情 / 附件 / canary / 补抓 四个阶段里，闸门异常一律**不被 except Exception 吞掉**
    * 停止时先把本页列表数据落盘（一个字段都不丢），详情标 detail_fetch=skipped_budget，
      附件标 status=skipped_budget（字符串条目自动规范化成 dict），二者都进可重试集合 → 可续跑
    * finalize 把"闸门原因"提到"详情待补"之前：报告写 request_budget_exceeded，
      不再被 detail_pending_remains 盖住
    * 新增用例 190–193（四个阶段的集成测试，断言"保数据 / 挂起标记 / 无 traceback / rc"）

用法：
    python tests\\make_baseline_v12.py
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
PREV = AGENT / "crawlers" / "_baseline_v11"
V12 = AGENT / "crawlers" / "_baseline_v12"

CODE_FILES = [
    "crawler.py", "clean.py", "doctor.py", "gate.py",
    "sites/foodlaw.py", "sites/mock.py", "sites/mockdetail.py",
    "sites/mocknext.py", "sites/mockjson.py", "sites/mockattach.py",
    "sites/mockspa.py", "sites/mocksoft.py", "sites/mockra.py",
    "sites/mockref.py", "sites/mocktotal.py", "sites/mockprobe.py",
    "sites/mockstates.py", "sites/mocknonext.py", "sites/_common.py",
    "sites/quotes.py", "sites/wzrc_all.py", "sites/wzrc_inc.py",
    "sites/yqwzrc.py", "sites/yqwzrc_wage.py", "sites/yqrc.py", "robots_rules.py",
]
TEST_FILES = [
    "test_crawler.py", "mock_site.py", "baseline_snapshot.py",
    "baseline_compare.py", "test_baseline_guard.py", "verify_baseline.py",
    "test_parse_detail_offline.py", "compare_detail_paths.py",
    "probe_spa.py", "fix_attachment_names.py",
    "make_baseline_v2.py", "make_baseline_v3.py", "make_baseline_v4.py",
    "make_baseline_v5.py", "make_baseline_v6.py", "make_baseline_v7.py",
    "make_baseline_v8.py", "make_baseline_v9.py", "make_baseline_v95.py", "make_baseline_v12.py",
]
SCRIPT_FILES = ["probe_pagesize.py"]
EXTRA_FILES = [
    ("tools/check_registry.py", "tools/check_registry.py"),
    ("tools/pick_details.py", "tools/pick_details.py"),
    ("tools/probe_one.py", "tools/probe_one.py"),
    ("tools/fetch_rendered.py", "tools/fetch_rendered.py"),
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
        p = V12 / sub
        if p.exists():
            shutil.rmtree(p)
    old_man = V12 / "manifest.csv"
    if old_man.exists():
        old_man.unlink()
    for sub in ("code/sites", "tests", "scripts", "samples", "data", "artifacts", "tools", "sites"):
        (V12 / sub).mkdir(parents=True, exist_ok=True)

    rows, problems = [], []

    def add(rel, src, src_rel):
        dst = V12 / rel
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

    PREV_FALLBACK = AGENT / "crawlers" / "_baseline_v10"

    PREV_FALLBACK = AGENT / "crawlers" / "_baseline_v10"
    for rel in FROM_PREV:
        src = PREV / rel
        src_base = "crawlers/_baseline_v11/"
        if not src.exists() and (PREV_FALLBACK / rel).exists():
            # v11 冻结时 artifacts 只保留了测试日志；这些样例/产物自 v10 起没变
            src = PREV_FALLBACK / rel
            src_base = "crawlers/_baseline_v10/"
        if not src.exists():
            problems.append("上一版里缺: %s" % rel)
            continue
        add(rel, src, src_base + rel)

    rel, src_rel = CURRENT_TESTS_LOG
    src = AGENT / src_rel
    if src.exists():
        add(rel, src, src_rel)
    else:
        problems.append("缺当前测试日志: %s" % src_rel)

    with open(V12 / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "src_rel", "bytes", "lastwrite",
                                          "md5_source", "md5_copy", "verify"])
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["rel"]):
            w.writerow(r)

    total = sum(r["bytes"] for r in rows)
    print("=" * 66)
    print("_baseline_v12 已建立")
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
