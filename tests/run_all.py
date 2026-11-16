#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一条命令跑回归：默认只跑「克隆后能直接跑」的那一类。

    python tests/run_all.py              # 六套 + 基线校验（并刷新 logs/_crawler_tests_latest.txt）
    python tests/run_all.py --local      # 额外跑 baseline_compare / test_baseline_guard
    python tests/run_all.py --only crawler,transport
    python tests/run_all.py --list

设计口径（与 README 的「验证体系」一节一致）：
  · 第一类 = 克隆即跑：test_crawler / discover / identify / transport / rule0 / render_batch
    + verify_baseline（只看副本完整性，--check-source 只报告不判死）
  · 第二类 = 需要本机产物：baseline_compare（读 logs/_crawler_tests_latest.txt）、
    test_baseline_guard（读 data/ out/ logs/）。缺产物时**明确说缺什么**，
    并以「跳过」计，不算失败。
  · CI 只跑第一类（见 .github/workflows/test.yml）。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
# 子进程统一按 UTF-8 输出：本机是 GBK 控制台，子进程默认按 GBK 写管道，
# 父进程若按 UTF-8 解码会得到 U+FFFD，再打印回 GBK 控制台就崩（v14.13.18 实测）。
_ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

CLONE_SAFE = [
    ("crawler", "tests/test_crawler.py", "217"),
    ("discover", "tests/test_discover.py", "32"),
    ("identify", "tests/test_identify.py", "21"),
    ("transport", "tests/test_transport.py", "23"),
    ("rule0", "tests/test_rule0.py", "17"),
    ("render_batch", "tests/test_render_batch.py", "20"),
]

_RAW = []  # 每一套的原始输出，最后合并写 logs/_crawler_tests_latest.txt

LOCAL_ONLY = [
    ("baseline_compare", "tests/baseline_compare.py", "49",
     ["logs/_crawler_tests_latest.txt"]),
    ("baseline_guard", "tests/test_baseline_guard.py", "16",
     ["data", "out", "logs"]),
]


def has_all(needs):
    return all((ROOT / n).exists() for n in needs)


def run_one(name, rel, expected, needs=None):
    """跑一个脚本。返回 (状态, 说明)。状态 ∈ PASS / FAIL / SKIP。"""
    path = ROOT / rel
    if not path.exists():
        return "SKIP", "脚本不存在：%s" % rel
    if needs and not has_all(needs):
        missing = [n for n in needs if not (ROOT / n).exists()]
        return "SKIP", "缺本机产物：%s（这是设计如此，不是代码错）" % ", ".join(missing)

    r = subprocess.run([PY, str(path)], cwd=str(ROOT),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=_ENV)
    out = (r.stdout or "") + (r.stderr or "")
    tail = [l.strip() for l in out.splitlines() if l.strip()][-1:] or [""]
    ok = r.returncode == 0
    _RAW.append("# ===== %s (%s) =====\n%s" % (name, rel, out.rstrip("\n")))
    return ("PASS" if ok else "FAIL"), "rc=%d 期望项数≈%s | %s" % (r.returncode, expected, tail[0][:90])


def main():
    # 输出里可能出现替换字符（子进程异常时），控制台编码装不下就替换，不要崩
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="一条命令跑回归（默认零外网、不需要本机产物）")
    ap.add_argument("--local", action="store_true",
                    help="额外跑需要本机抓取产物的两道（baseline_compare / test_baseline_guard）")
    ap.add_argument("--only", default="", help="只跑指定几套，逗号分隔（如 crawler,identify）")
    ap.add_argument("--list", action="store_true", help="只列出会跑哪些，不执行")
    args = ap.parse_args()

    plan = list(CLONE_SAFE)
    if args.local:
        plan += LOCAL_ONLY

    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        plan = [p for p in plan if p[0] in want]
        if not plan:
            print("没有任何一套匹配 --only %r" % args.only)
            return 2

    if args.list:
        for name, rel, exp, *rest in plan:
            print("  %-18s %-34s 期望 %s 项" % (name, rel, exp))
        if not args.local:
            print("\n  （--local 还会加上：baseline_compare / test_baseline_guard）")
        return 0

    print("=" * 74)
    print("回归：%d 套｜Python %s｜%s" % (len(plan), sys.version.split()[0], ROOT))
    print("=" * 74)

    results = []
    for item in plan:
        name, rel, exp = item[0], item[1], item[2]
        needs = item[3] if len(item) > 3 else None
        status, detail = run_one(name, rel, exp, needs)
        results.append((name, status, detail))
        print("  %-4s %-18s %s" % (status, name, detail))

    # 基线校验（只跑副本完整性；源漂移只报告）
    print("-" * 74)
    vb = ROOT / "tests" / "verify_baseline.py"
    if vb.exists():
        r = subprocess.run([PY, str(vb), "--strict", "--check-source"], cwd=str(ROOT),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=_ENV)
        out = (r.stdout or "") + (r.stderr or "")
        ok = r.returncode == 0
        results.append(("verify_baseline", "PASS" if ok else "FAIL", "rc=%d" % r.returncode))
        for l in out.splitlines():
            if "副本完好" in l or "漂移" in l or "已损坏" in l:
                print("  %-4s %-18s %s" % ("PASS" if ok else "FAIL", "verify_baseline", l.strip()[:70]))
                break
        else:
            print("  %-4s %-18s rc=%d" % ("PASS" if ok else "FAIL", "verify_baseline", r.returncode))

    # 只有跑完整计划时才刷新证据文件，避免 --only 把日志截成残缺版
    if not args.only and _RAW:
        _log_dir = ROOT / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
        (_log_dir / "_crawler_tests_latest.txt").write_text(
            "\n".join(_RAW) + "\n", encoding="utf-8", newline="\n")
        print("  证据文件已刷新：logs/_crawler_tests_latest.txt")

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = [n for n, s, _ in results if s == "FAIL"]
    skipped = [n for n, s, _ in results if s == "SKIP"]

    print("=" * 74)
    print("通过 %d｜失败 %d｜跳过 %d" % (passed, len(failed), len(skipped)))
    if failed:
        print("失败：%s" % ", ".join(failed))
    if skipped:
        print("跳过：%s（需要本机产物，加 --local 并先跑过真实站点才会有）" % ", ".join(skipped))
    print("=" * 74)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())