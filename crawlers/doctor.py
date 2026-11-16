#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓后体检（doctor）：读一份抓取报告，做 8 项检查，给 PASS / WARN / FAIL。

独立文件——crawler.py 一行都不改（引擎 MD5 必须与 v8 一致）。

用法：
    python crawlers\\doctor.py --job wzrc_dw_20261111
    python crawlers\\doctor.py --report out\\reports\\report-xxx.json

退出码：
    0 = 全部 PASS
    1 = 有 WARN（可用，但要看一眼）
    2 = 有 FAIL（不可用）
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AGENT = Path(__file__).resolve().parent.parent
REPORTS = Path(os.environ.get("CRAWLER_REPORT_DIR") or (AGENT / "out" / "reports"))
MANIFESTS = Path(os.environ.get("CRAWLER_STATE_DIR") or (AGENT / "manifests"))

RC = {"PASS": 0, "WARN": 1, "FAIL": 2}
KEY_FIELDS = ["title", "company", "salary_raw", "region"]


def pad(text, width):
    """按显示宽度补空格（中文占 2 列）。"""
    w = sum(2 if ord(ch) > 127 else 1 for ch in text)
    return text + " " * max(0, width - w)


def find_report(job):
    cands = sorted(REPORTS.glob("report-%s-*.json" % job),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def load_rows(path):
    """读 JSONL，返回 list[dict]；读不到返回 None。"""
    p = Path(path) if path else None
    if not p or not p.exists():
        return None
    rows = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    rows.append({})          # 坏行也计入总行数，字段算空
    except Exception:
        return None
    return rows


def check_status(rep):
    """success=PASS / noop=PASS / partial=WARN / failed=FAIL。"""
    status = rep.get("status")
    reason = rep.get("reason")
    if status not in {"success", "noop", "partial", "failed"}:
        return "FAIL", "未知状态 %r / %r" % (status, reason)
    if not reason:
        return "FAIL", "reason 为空"
    if status == "success":
        # success 不止 ok 一种合法 reason：
        #   details_repaired  = 两段式第 2 段 / 开跑前补抓（本次只补详情，没抓列表）
        #   details_repaired 在两段式里是**正常成功**，不是异常
        OK_REASONS = {"ok", "details_repaired"}
        if reason not in OK_REASONS:
            return "FAIL", "success 的 reason 应为 %s 之一，实际 %r" % (
                "/".join(sorted(OK_REASONS)), reason)
        return "PASS", "success / %s" % reason
    if status == "noop":
        return "PASS", "noop / %s" % reason
    if status == "partial":
        return "WARN", "partial / %s（有页失败或截断，数据不完整）" % reason
    return "FAIL", "failed / %s（本次抓取失败）" % reason


def check_coverage(rep):
    cov = rep.get("coverage")
    truncated = rep.get("truncated")
    if cov is None:
        return "PASS", "报告无 coverage 字段（旧格式，跳过）"
    if cov >= 1.0:
        return "PASS", "%s" % cov
    if truncated is True:
        return "PASS", "%s（truncated=True，显式分段）" % cov
    return "FAIL", "%s 且 truncated=False（有页没抓到，也没标截断）" % cov


def check_pages(rep):
    stats = rep.get("stats") or {}
    ok_n = stats.get("pages_ok")
    skipped = stats.get("pages_skipped") or 0
    eff = rep.get("pages_effective")
    decl = rep.get("pages_declared")
    total = stats.get("pages_total")

    # 旧报告没有 effective/declared，用 pages_total 兜底
    if eff is None:
        eff = total
    if decl is None:
        decl = total
    if ok_n is None:
        return "WARN", "报告缺 pages_ok"

    lhs = ok_n + skipped
    detail = "%s = %s = %s" % (lhs, eff, decl)
    if lhs == eff == decl:
        return "PASS", detail
    # 显式分段（--pages / truncated）时 effective < declared 属正常：
    # 自洽只要求 ok + skipped == effective
    if lhs == eff and rep.get("truncated") is True:
        return "PASS", "%s（truncated=True，declared 为站点总页数）" % detail
    return "WARN", detail + "（不自洽）"


def check_density(rep):
    stats = rep.get("stats") or {}
    pages_ok = stats.get("pages_ok") or 0
    cards = stats.get("cards_total")
    if cards is None:
        cards = stats.get("records_new")
    if cards is None:
        cards = (rep.get("datafile") or {}).get("records_new_this_run")
    if not pages_ok:
        # 两段式第 2 段、开跑前补抓 / 补附件这三类运行**本来就不抓列表页**，
        # “每页几条”对它们没有意义 —— 标“不适用”，别拿 WARN 制造噪声。
        if rep.get("reason") in ("details_repaired", "nothing_done") or \
                (rep.get("datafile") or {}).get("records_new_this_run") == 0:
            return "PASS", "不适用（本次未抓列表页：两段式第 2 段 / 补抓 / 补附件）"
        return "WARN", "pages_ok=0，无法算密度"
    if cards is None:
        return "WARN", "缺卡片数"
    density = float(cards) / pages_ok
    detail = "%d/%d = %.2f" % (cards, pages_ok, density)
    if density >= 4.0:
        return "PASS", detail
    if density >= 3.0:
        return "WARN", detail + "（3.0~4.0，偏低）"
    return "FAIL", detail + "（<3.0，疑似降级返回）"


def check_anomalies(rep):
    anoms = rep.get("anomalies") or []
    if not anoms:
        return "PASS", "0"
    others = [a for a in anoms
              if (a.get("page") != "state") and (a.get("type") != "state")]
    if not others:
        return "PASS", "%d 条，全是 state 类" % len(anoms)
    return "FAIL", "%d 条（非 state 类 %d 条，首条：%s）" % (
        len(anoms), len(others),
        json.dumps(others[0], ensure_ascii=False)[:80])


def check_cooldown():
    if not MANIFESTS.exists():
        return "PASS", "不存在"
    hits = sorted(MANIFESTS.glob("_cooldown_*.json"))
    if not hits:
        return "PASS", "不存在"
    return "WARN", "%d 个冷却文件（首个 %s）" % (len(hits), hits[0].name)


def check_fields(rows):
    if rows is None:
        return "WARN", "数据文件读不到，无法核验"
    if not rows:
        return "WARN", "数据文件为空"
    parts, worst = [], "PASS"
    for field in KEY_FIELDS:
        present = [r for r in rows if field in r]
        if not present:
            parts.append("%s 不适用" % field)
            continue
        filled = sum(1 for r in present
                     if r.get(field) is not None and str(r.get(field)).strip() != "")
        rate = filled / float(len(present))
        parts.append("%s %.0f%%" % (field, rate * 100))
        if rate < 0.99:
            worst = "FAIL"
    return worst, " / ".join(parts)


def check_rows(rep, rows, report_mtime=None):
    """数据行数：账目自洽 + 行数够 + 数据文件没在报告之后被改过。

    报告早于数据文件（后续任务又追加过），行数无法证明报告当时的真实性
    → WARN，不能判 PASS。
    """
    datafile = rep.get("datafile") or {}
    before = datafile.get("records_before_run")
    new = datafile.get("records_new_this_run")
    total = datafile.get("total_after_run")
    if before is None or new is None or total is None:
        return "PASS", "报告无 datafile 账目（跳过）"
    if rows is None:
        return "WARN", "数据文件读不到：账目 %d+%d=%d" % (before, new, total)

    data_path = (rep.get("artifacts") or {}).get("data")
    if data_path and report_mtime is not None:
        try:
            data_mtime = Path(data_path).stat().st_mtime
        except Exception:
            data_mtime = None
        if data_mtime is not None and data_mtime > report_mtime:
            return "WARN", ("数据文件比报告新（报告后被追加过），"
                            "现有 %d 行无法核验当时应有 %d 行"
                            % (len(rows), total))

    lines = len(rows)
    if before + new != total:
        return "WARN", "%d+%d != %d（账目不自洽）" % (before, new, total)
    if lines < total:
        return "WARN", "文件 %d 行 < 应有 %d 行（数据可能被截断）" % (lines, total)
    return "PASS", "%d 行（账目 %d+%d=%d）" % (lines, before, new, total)


def main():
    ap = argparse.ArgumentParser(description="抓后体检")
    ap.add_argument("--job", help="任务名，自动取最新报告")
    ap.add_argument("--report", help="直接指定报告路径")
    args = ap.parse_args()

    if not args.job and not args.report:
        print("需要 --job 或 --report")
        return 2

    if args.report:
        path = Path(args.report)
    else:
        path = find_report(args.job)
        if path is None:
            print("找不到 %s 的报告" % args.job)
            return 2

    if not path.exists():
        print("报告不存在：%s" % path)
        return 2

    rep = json.loads(path.read_text(encoding="utf-8"))
    job = rep.get("job") or path.stem

    data_path = (rep.get("artifacts") or {}).get("data")
    rows = load_rows(data_path)
    report_mtime = path.stat().st_mtime

    checks = [
        ("status/reason", check_status(rep)),
        ("coverage", check_coverage(rep)),
        ("页数自洽", check_pages(rep)),
        ("卡片密度", check_density(rep)),
        ("anomalies", check_anomalies(rep)),
        ("冷却文件", check_cooldown()),
        ("字段非空率", check_fields(rows)),
        ("数据行数", check_rows(rep, rows, report_mtime)),
    ]

    print("报告：%s" % path.name)
    print("")
    print(pad("检查项", 14) + pad("结果", 8) + "实测值")
    print("-" * 78)
    for name, (verdict, detail) in checks:
        print(pad(name, 14) + pad(verdict, 8) + detail)
    print("")

    verdicts = [v for _, (v, _) in checks]
    worst = "FAIL" if "FAIL" in verdicts else ("WARN" if "WARN" in verdicts else "PASS")
    n_pass = verdicts.count("PASS")
    n_warn = verdicts.count("WARN")
    n_fail = verdicts.count("FAIL")

    if worst == "PASS":
        print("结论：✅ 这份数据可以交付（%d 项全 PASS）" % n_pass)
    elif worst == "WARN":
        print("结论：⚠️ 可用，但要看一眼（PASS %d / WARN %d）" % (n_pass, n_warn))
    else:
        print("结论：❌ 这份数据不可用（FAIL %d 项）" % n_fail)

    out = {
        "job": job,
        "report": str(path),
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": worst,
        "exit_code": RC[worst],
        "counts": {"PASS": n_pass, "WARN": n_warn, "FAIL": n_fail},
        "checks": [{"name": n, "verdict": v, "detail": d} for n, (v, d) in checks],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = REPORTS / ("doctor-%s-%s.json" % (job, stamp))
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细已写入：%s" % out_path.name)

    return RC[worst]


if __name__ == "__main__":
    sys.exit(main())