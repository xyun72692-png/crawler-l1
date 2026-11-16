# -*- coding: utf-8 -*-
"""
阶段 0 的配套工具：把"当前状态"量化成一份指纹。

⚠ 它默认会【覆盖基线里的 baseline-metrics.json】—— 这等于把参考值改成"现在这样"。
   所以正确用法是：
      1. 平时回归：只跑 baseline_compare.py（它自己会采集当前状态，不需要先跑这个）
      2. 确认要接受新数字时，才跑本脚本把基线刷新
   曾经的错误做法：先 snapshot 再 compare —— 先改参考值再比对，永远是 0，等于没测。

不做的事：不发网络请求、不修改任何数据文件、不触发爬虫。

命令行：
    python tests\\baseline_snapshot.py                  # 重新生成基线指纹
    python tests\\baseline_snapshot.py --print          # 只打印，不落盘
"""
import argparse
import csv as _csv
import hashlib
import json
import os
import sys
from pathlib import Path

# 允许用环境变量把"基线目录"和"数据目录"指到别处。
# 为什么需要：为了做故障注入测试（证明这套护栏真的会报警），
# 必须能在沙箱里改数据，而不是去动真实数据。
# 阶段2 之后用 v2 作为活跃基线；v1 保持原样（阶段1 的离线对照还要用它）
BASE = Path(os.environ.get("BASELINE_DIR") or (Path(__file__).resolve().parent.parent / "crawlers" / "_baseline_v14_13_18"))
AGENT = Path(os.environ.get("BASELINE_AGENT") or Path(__file__).resolve().parent.parent)

JOBS = [
    ("foodlaw", AGENT / "data/raw/foodlaw.jsonl", "detail_url"),
    ("quotes",  AGENT / "data/raw/quotes.jsonl",  "quote_key"),
    ("books",   AGENT / "data/raw/books.jsonl",   "detail_url"),
]

DEFAULT_REPORT = "report-foodlaw-20261110-142827-597.json"
DEFAULT_CLEAN_STEM = "foodlaw_clean_20261110-142932"
# 用"当前这份测试输出"而不是阶段0 冻结的那份：
# 冻结的那份永远不变，拿它比对等于自己比自己，测不出新增/减少了几个用例。
DEFAULT_TESTS_LOG = "logs/_crawler_tests_latest.txt"


# ---------------------------------------------------------------- 基础工具
def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def is_blank(v):
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    if isinstance(v, float) and v != v:      # NaN
        return True
    return False


def _value_counts(rows, field):
    out = {}
    for r in rows:
        if field not in r:
            continue
        k = str(r.get(field))
        out[k] = out.get(k, 0) + 1
    return out


def _value_counts_sorted(rows, field):
    return dict(sorted(_value_counts(rows, field).items()))


# ---------------------------------------------------------------- 各项统计
def job_stats(name, path, dedup_key):
    if not path.exists():
        return {"job": name, "status": "file_missing", "path": str(path)}
    rows = load_jsonl(path)
    fields = sorted({k for r in rows for k in r})
    blanks = {k: sum(1 for r in rows if is_blank(r.get(k))) for k in fields}
    keys = [str(r.get(dedup_key, "")) for r in rows]
    nonblank_keys = [k for k in keys if k]
    return {
        "job": name,
        "path": str(path),
        "bytes": path.stat().st_size,
        "md5": md5_of(path),
        "records": len(rows),
        "dedup_key": dedup_key,
        "dedup_key_nonblank": len(nonblank_keys),
        "dedup_key_unique": len(set(nonblank_keys)),
        "duplicate_count": len(nonblank_keys) - len(set(nonblank_keys)),
        "field_count": len(fields),
        "fields": fields,
        "blank_fields": {k: v for k, v in blanks.items() if v > 0},
        "detail_fetch_values": _value_counts_sorted(rows, "detail_fetch"),
        "detail_http_status_values": _value_counts_sorted(rows, "detail_http_status"),
        "valid_status_values": _value_counts_sorted(rows, "valid_status"),
        "status_confirmed_values": _value_counts_sorted(rows, "status_confirmed"),
    }


def report_stats(name=DEFAULT_REPORT):
    """取指定的一份 foodlaw 采集报告的关键字段（默认=基线那份）。"""
    p = AGENT / "out/reports" / name
    if not p.exists():
        return {"status": "report_missing", "file": name}
    with open(p, "r", encoding="utf-8") as f:
        d = json.load(f)
    # field_signature 是 {"field_count": N, "fields": [...]} 这样一个 dict。
    # 早期我误当 list 用 len() 数，得到恒等于 2，属于口径错误，这里改正。
    fs = d.get("field_signature") or {}
    if isinstance(fs, dict):
        fs_count, fs_fields = fs.get("field_count"), fs.get("fields")
    else:                                     # 兼容旧格式（纯 list）
        fs_fields, fs_count = fs, len(fs)
    return {
        "file": p.name,
        "md5": md5_of(p),
        "status": d.get("status"),
        "reason": d.get("reason"),
        "mode": d.get("mode"),
        "rc": d.get("rc"),
        "field_signature_count": fs_count,
        "field_signature": fs_fields,
        "datafile": d.get("datafile"),
        "per_page_summary": d.get("per_page_summary"),
        "anomalies_count": len(d.get("anomalies") or []),
        "stats": d.get("stats"),
    }


def export_stats(stem=DEFAULT_CLEAN_STEM):
    """foodlaw 某一次清洗导出的形状。"""
    base = AGENT / "out" / stem
    out = {}
    for ext in ("csv", "json", "xlsx"):
        p = base.with_suffix("." + ext)
        out[ext] = {"exists": p.exists(),
                    "bytes": p.stat().st_size if p.exists() else None,
                    "md5": md5_of(p) if p.exists() else None}
    csvp = base.with_suffix(".csv")
    if csvp.exists():
        with open(csvp, "r", encoding="utf-8-sig", newline="") as f:
            rd = list(_csv.reader(f))
        out["csv_rows"] = len(rd) - 1
        out["csv_cols"] = len(rd[0]) if rd else 0
        out["csv_header"] = rd[0] if rd else []
    return out


def tests_stats(log_rel=DEFAULT_TESTS_LOG):
    log = AGENT / log_rel
    if not log.exists():
        return {"status": "no_log", "log": str(log)}
    txt = log.read_text(encoding="utf-8", errors="replace")
    import re
    return {
        "log": log_rel,
        "md5": md5_of(log),
        # 各套件缩进/对齐不同，按行首计数才准（"  PASS  " 字面匹配会漏 render_batch）
        "passed": len(re.findall(r"(?m)^\s*PASS\b", txt)),
        "failed": len(re.findall(r"(?m)^\s*FAIL\b", txt)),
        "summary": [l.strip() for l in txt.splitlines() if l.strip().startswith("结果")],
    }


# ---------------------------------------------------------------- 组装
def collect(report_name=DEFAULT_REPORT, clean_stem=DEFAULT_CLEAN_STEM,
            tests_log=DEFAULT_TESTS_LOG):
    return {
        "frozen_at": "2026-11-10",
        "purpose": "阶段0回归基线：改动前后必须逐项比对",
        "python": sys.version.split()[0],
        "jobs": [job_stats(n, p, k) for n, p, k in JOBS],
        "report": report_stats(report_name),
        "exports": export_stats(clean_stem),
        "tests": tests_stats(tests_log),
    }


def print_summary(data):
    print("=" * 66)
    print("阶段0 基线指纹")
    print("=" * 66)
    for j in data["jobs"]:
        if j.get("status") == "file_missing":
            print("  %-9s 文件不存在" % j["job"])
            continue
        print("  %-9s 记录 %-5d 去重键 %-11s 唯一 %-5d 重复 %-3d 字段 %-2d 空字段 %d"
              % (j["job"], j["records"], j["dedup_key"], j["dedup_key_unique"],
                 j["duplicate_count"], j["field_count"], len(j["blank_fields"])))
        if j["blank_fields"]:
            print("             空字段明细: %s" % j["blank_fields"])
    r = data["report"]
    print("  报告      %s  status=%s reason=%s mode=%s 字段签名=%s anomalies=%s"
          % (r.get("file"), r.get("status"), r.get("reason"), r.get("mode"),
             r.get("field_signature_count"), r.get("anomalies_count")))
    e = data["exports"]
    print("  导出      csv %s 行 / %s 列  xlsx %s 字节"
          % (e.get("csv_rows"), e.get("csv_cols"), (e.get("xlsx") or {}).get("bytes")))
    t = data["tests"]
    print("  测试      通过 %s / 失败 %s  %s"
          % (t.get("passed"), t.get("failed"), " ".join(t.get("summary") or [])))
    print("=" * 66)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="dry", action="store_true", help="只打印，不写入文件")
    ap.add_argument("--tests-log", dest="tests_log", default=None,
                    help="用哪份测试日志算用例数（默认读最新的 logs/_crawler_tests_latest.txt）")
    args = ap.parse_args()

    # 沙箱测试时输出到文件，控制台编码可能是 GBK
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    data = collect(tests_log=args.tests_log or DEFAULT_TESTS_LOG)
    print_summary(data)
    if args.dry:
        print("（--print 模式，未写入文件）")
        return 0
    out = BASE / "baseline-metrics.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写入: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())