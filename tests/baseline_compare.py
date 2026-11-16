# -*- coding: utf-8 -*-
"""
阶段 0 的配套工具：拿当前状态和 baseline-metrics.json 逐项比对。

用法：
    python tests\\baseline_compare.py

退出码：
    0 = 与基线完全一致（硬指标全过；只有 MD5/字节数这类软指标变化）
    1 = 有硬指标发生变化（必须解释：是故意的吗？要不要更新基线？）
    2 = 基线文件不存在 / 目标文件缺失，无法比对

"硬指标"指会影响使用结果的东西：条数、字段名、去重、空值、状态码分布、
报告的 status/reason、导出形状、测试通过数。
"软指标"指 MD5、字节数：字段一加就会变，只看不做判定。
"""
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK，直接 print "✓" 会 UnicodeEncodeError 崩掉。
# 强制切 UTF-8，编不出来的字符退化成 ? 而不是抛异常。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_snapshot as bs  # noqa: E402

HARD_JOB_KEYS = [
    "records", "dedup_key", "dedup_key_nonblank", "dedup_key_unique",
    "duplicate_count", "field_count", "fields", "blank_fields",
    "detail_fetch_values", "detail_http_status_values",
    "valid_status_values", "status_confirmed_values",
]
HARD_REPORT_KEYS = [
    "status", "reason", "mode", "field_signature_count", "field_signature",
    "datafile", "per_page_summary", "anomalies_count",
]
HARD_EXPORT_KEYS = ["csv_rows", "csv_cols", "csv_header"]
HARD_TEST_KEYS = ["passed", "failed"]


def norm(v):
    """把 dict 的键统一成字符串再比较（JSON 会把 int 键变成 str）。"""
    if isinstance(v, dict):
        return {str(k): norm(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [norm(x) for x in v]
    return v


def diff_block(title, cur, base, hard_keys, soft_keys=()):
    diffs, softs = [], []
    for k in hard_keys:
        a, b = norm(cur.get(k)), norm(base.get(k))
        if a != b:
            diffs.append((k, b, a))
    for k in soft_keys:
        a, b = cur.get(k), base.get(k)
        if a != b:
            softs.append((k, b, a))
    return diffs, softs


def main():
    base_path = bs.BASE / "baseline-metrics.json"
    if not base_path.exists():
        print("基线不存在：%s" % base_path)
        print("先跑 python tests\\baseline_snapshot.py 生成基线")
        return 2

    base = json.loads(base_path.read_text(encoding="utf-8"))

    # 按基线里记录的文件名去取当前值，避免"最新一份"选错文件
    rep = base.get("report") or {}
    exp = base.get("exports") or {}
    tst = base.get("tests") or {}
    clean_stem = None
    if exp.get("csv", {}).get("md5"):
        # 从基线里还原出清洗文件名（去掉扩展名）
        pass
    cur = bs.collect(
        report_name=rep.get("file") or bs.DEFAULT_REPORT,
        clean_stem=bs.DEFAULT_CLEAN_STEM,
        # 当前侧【永远读最新的实时日志】。基线里存的是"当时的数字"（passed/failed），
        # 不是"去读某个文件"——否则会把基线自己那份冻结日志读回来，两边恒等，永远绿灯。
        tests_log=bs.DEFAULT_TESTS_LOG,
    )

    hard_total = 0
    changed = 0
    soft_changed = 0

    print("=" * 72)
    print("基线比对：当前状态 vs %s" % base_path)
    print("=" * 72)

    # ---- 数据文件 ----
    base_jobs = {j["job"]: j for j in base.get("jobs", [])}
    for cj in cur.get("jobs", []):
        name = cj["job"]
        bj = base_jobs.get(name)
        print("\n[数据] %s" % name)
        if bj is None:
            print("  基线里没有这个 job → 新增，需人工确认")
            changed += 1
            continue
        if cj.get("status") == "file_missing":
            print("  ✗ 文件不存在：%s" % cj.get("path"))
            changed += 1
            continue
        diffs, softs = diff_block(name, cj, bj, HARD_JOB_KEYS, ("md5", "bytes"))
        hard_total += len(HARD_JOB_KEYS)
        if not diffs:
            print("  ✓ 硬指标全部一致（%d 项：记录 %d / 唯一 %d / 重复 %d / 字段 %d / 空字段 %d）"
                  % (len(HARD_JOB_KEYS), cj["records"], cj["dedup_key_unique"],
                     cj["duplicate_count"], cj["field_count"], len(cj["blank_fields"])))
        for k, b, a in diffs:
            changed += 1
            print("  ✗ %s" % k)
            print("      基线: %s" % _short(b))
            print("      现在: %s" % _short(a))
        for k, b, a in softs:
            soft_changed += 1
            print("  ~ %s 变化（软指标，不计失败）: %s → %s" % (k, b, a))

    # ---- 报告 ----
    print("\n[报告] %s" % (rep.get("file") or "?"))
    if cur["report"].get("status") == "report_missing":
        print("  ✗ 报告文件不存在")
        changed += 1
    else:
        diffs, softs = diff_block("report", cur["report"], rep,
                                  HARD_REPORT_KEYS, ("md5",))
        hard_total += len(HARD_REPORT_KEYS)
        if not diffs:
            print("  ✓ 硬指标全部一致（status=%s reason=%s 字段签名=%s anomalies=%s）"
                  % (cur["report"]["status"], cur["report"]["reason"],
                     cur["report"]["field_signature_count"],
                     cur["report"]["anomalies_count"]))
        for k, b, a in diffs:
            changed += 1
            print("  ✗ %s" % k)
            print("      基线: %s" % _short(b))
            print("      现在: %s" % _short(a))
        for k, b, a in softs:
            soft_changed += 1
            print("  ~ %s 变化（软指标）" % k)

    # ---- 导出 ----
    print("\n[导出] csv/json/xlsx")
    diffs, softs = diff_block("exports", cur["exports"], exp,
                              HARD_EXPORT_KEYS, ("csv", "json", "xlsx"))
    hard_total += len(HARD_EXPORT_KEYS)
    if not diffs:
        print("  ✓ 硬指标全部一致（csv %s 行 / %s 列）"
              % (cur["exports"].get("csv_rows"), cur["exports"].get("csv_cols")))
    for k, b, a in diffs:
        changed += 1
        print("  ✗ %s" % k)
        print("      基线: %s" % _short(b))
        print("      现在: %s" % _short(a))
    if softs:
        print("  （md5/字节数变化属正常，未计入失败）")

    # ---- 测试 ----
    print("\n[测试] test_crawler.py")
    if cur["tests"].get("status") == "no_log":
        # 别在这里静默放过：日志不存在时 passed/failed 都是 None，
        # 两边一比"相等"，会给出假的绿灯。这是护栏自身的 fail-open，必须堵掉。
        changed += 1
        print("  ✗ 测试日志不存在：%s" % cur["tests"].get("log"))
        print("      先跑一次 test_crawler.py 并把输出写到这个文件，再做比对")
    else:
        diffs, softs = diff_block("tests", cur["tests"], tst, HARD_TEST_KEYS, ("md5",))
        hard_total += len(HARD_TEST_KEYS)
        if not diffs:
            print("  ✓ 通过 %s / 失败 %s" % (cur["tests"].get("passed"),
                                            cur["tests"].get("failed")))
        for k, b, a in diffs:
            changed += 1
            print("  ✗ %s 基线 %s → 现在 %s" % (k, b, a))

    # ---- 结论 ----
    print("\n" + "=" * 72)
    if changed == 0:
        print("结论：与基线一致（硬指标 %d 项全过，软指标变化 %d 项）"
              % (hard_total, soft_changed))
        print("=" * 72)
        return 0
    print("结论：%d 项硬指标发生变化，需逐条解释后再决定是否更新基线" % changed)
    print("=" * 72)
    return 1


def _short(v, limit=220):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    if len(s) > limit:
        s = s[:limit] + "...(截断)"
    return s


if __name__ == "__main__":
    sys.exit(main())