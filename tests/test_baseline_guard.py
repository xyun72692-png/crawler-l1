# -*- coding: utf-8 -*-
"""
阶段 0 的自检：证明"基线护栏"真的会报警。

背景教训（2026-11-10）：
    上一轮我写了个检查工具，只跑"干净情况"就宣称它有效 —— 实际那个分支
    根本没被执行过。所以这里必须做故障注入：故意把数据改坏，确认它报错。

做法：
    1. 在 logs\\_baselinetest\\ 下搭一个假沙箱（真数据的副本）
    2. 用环境变量 BASELINE_DIR / BASELINE_AGENT 把两个脚本指过去
    3. 先建基线，跑比对，应该 exit 0
    4. 逐项注入故障，每次跑比对，应该 exit 1 且报出对应的键
    5. 每项测完复原
    全程不碰真实数据文件。

退出码：0 = 全部用例符合预期；1 = 有不符合预期的用例。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_venv_py = Path(__file__).resolve().parent.parent / "venv" / "Scripts" / "python.exe"
PY = str(_venv_py if _venv_py.exists() else sys.executable)
AGENT_REAL = Path(__file__).resolve().parent.parent
REAL_BASE = AGENT_REAL / "crawlers/_baseline_v14_13_4"  # 活跃基线（verify 用例在它上面做探针）
HERE = Path(__file__).resolve().parent
ROOT = AGENT_REAL / "logs/_baselinetest"

# 沙箱里要复刻的文件（源路径 → 相对位置）
FIXTURES = [
    "data/raw/foodlaw.jsonl",
    "data/raw/quotes.jsonl",
    "data/raw/books.jsonl",
    "out/foodlaw_clean_20261110-142932.csv",
    "out/foodlaw_clean_20261110-142932.json",
    "out/foodlaw_clean_20261110-142932.xlsx",
    "out/reports/report-foodlaw-20261110-142827-597.json",
    "logs/_crawler_tests_latest.txt",
]
DEFAULT_REPORT = "report-foodlaw-20261110-142827-597.json"


def build_sandbox():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    agent = ROOT / "agent"
    pristine = ROOT / "pristine"
    base = ROOT / "base"
    for sub in ("data/raw", "out/reports", "logs"):
        (agent / sub).mkdir(parents=True, exist_ok=True)
        (pristine / sub).mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)

    missing = []
    for rel in FIXTURES:
        src = AGENT_REAL / rel
        if not src.exists():
            missing.append(rel)
            continue
        shutil.copy2(src, pristine / rel)
        shutil.copy2(src, agent / rel)
    return agent, pristine, base, missing


def reset(agent, pristine):
    """把沙箱恢复成原始副本。"""
    for rel in FIXTURES:
        src = pristine / rel
        if src.exists():
            dst = agent / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def run(script, agent, base, expect_rc=None):
    env = dict(os.environ)
    env["BASELINE_DIR"] = str(base)
    env["BASELINE_AGENT"] = str(agent)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [PY, str(HERE / script)],
        cwd=str(AGENT_REAL), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    out = p.stdout.decode("utf-8", errors="replace")
    return p.returncode, out


# ------------------------------------------------------------ 故障注入手法
def inject_add_duplicate(agent):
    """给 foodlaw.jsonl 追加一条完全重复的记录 → duplicate_count 应从 0 变 1。"""
    p = agent / "data/raw/foodlaw.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    first = [l for l in lines if l.strip()][0]
    p.write_text("\n".join(lines + [first]) + "\n", encoding="utf-8")


def inject_drop_field(agent):
    """把每条记录的 abolish_date 删掉 → field_count 应少 1。"""
    p = agent / "data/raw/foodlaw.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        r.pop("abolish_date", None)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                 encoding="utf-8")


def inject_report_status(agent):
    """把报告 status 从 success 改成 failed。"""
    p = agent / "out/reports" / DEFAULT_REPORT
    d = json.loads(p.read_text(encoding="utf-8"))
    d["status"] = "failed"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def inject_csv_column(agent):
    """从导出 csv 里删掉 status_derived 这一列 → 列数 23 → 22。"""
    import csv
    p = agent / "out/foodlaw_clean_20261110-142932.csv"
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    idx = rows[0].index("status_derived")
    rows = [[v for i, v in enumerate(r) if i != idx] for r in rows]
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)


def inject_tests_log(agent):
    """测试日志里删掉一条 PASS → passed 应少 1。"""
    p = agent / "logs/_crawler_tests_latest.txt"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    out, dropped = [], False
    for l in lines:
        if not dropped and "  PASS  " in l:
            dropped = True
            continue
        out.append(l)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def inject_delete_tests_log(agent):
    """直接删掉测试日志 → 护栏必须报"无法核对"，而不是给绿灯。"""
    p = agent / "logs/_crawler_tests_latest.txt"
    if p.exists():
        p.unlink()


VERIFY_CASES_DOC = """
另外 3 条验证 verify_baseline.py 的"多余文件"检查。

为什么单独测这一段：2026-11-10 跑离线解析测试时，importlib 在基线目录里
生成了一个 __pycache__\\*.pyc，基线被污染而没有任何提示 —— 那时 verify 只查
manifest 里的条目，根本看不见多出来的文件。

这三个用例直接在【真实基线目录】里放一个探针文件再删掉，
不碰任何受哈希保护的文件。
"""


def run_verify(agent, base, extra_args=()):
    env = dict(os.environ)
    env["BASELINE_DIR"] = str(base)
    env["BASELINE_AGENT"] = str(agent)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([PY, str(HERE / "verify_baseline.py")] + list(extra_args),
                       cwd=str(AGENT_REAL), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", errors="replace")


def verify_cases(real_base):
    probe = real_base / "_probe_extra_file.tmp"
    out = []

    rc, txt = run_verify(AGENT_REAL, real_base)
    out.append(("干净（应通过）", rc == 0, "rc=%d" % rc))

    try:
        probe.write_text("probe", encoding="utf-8")
        rc2, txt2 = run_verify(AGENT_REAL, real_base)
        out.append(("多一个文件：默认只报告", rc2 == 0 and "多余文件" in txt2,
                    "rc=%d 提到多余=%s" % (rc2, "多余文件" in txt2)))

        rc3, txt3 = run_verify(AGENT_REAL, real_base, ("--strict",))
        out.append(("多一个文件：--strict 报错", rc3 == 1 and "多余文件" in txt3,
                    "rc=%d" % rc3))
    finally:
        if probe.exists():
            probe.unlink()

    rc4, txt4 = run_verify(AGENT_REAL, real_base)
    out.append(("删掉探针后恢复", rc4 == 0, "rc=%d" % rc4))
    return out


def separation_cases():
    """code/data 分离：data 改内容只报告；data 坏 JSON 必失败；code 改内容 strict 失败。"""
    import csv
    import hashlib
    import tempfile
    out = []
    with tempfile.TemporaryDirectory(prefix="sep_") as td:
        root = Path(td)
        agent, base = root / "agent", root / "base"
        (agent / "crawlers").mkdir(parents=True)
        (agent / "tools" / "geo").mkdir(parents=True)
        (base / "code").mkdir(parents=True)
        (base / "tools" / "geo").mkdir(parents=True)
        code_src = agent / "crawlers" / "a.py"
        data_src = agent / "tools" / "geo" / "d.json"
        code_src.write_text("x=1\n", encoding="utf-8")
        data_src.write_text('{"a":1}\n', encoding="utf-8")
        shutil.copy2(code_src, base / "code" / "a.py")
        shutil.copy2(data_src, base / "tools" / "geo" / "d.json")

        def row(rel, src_rel, kind):
            f = base / rel
            h = hashlib.md5(f.read_bytes()).hexdigest()
            return {"rel": rel, "src_rel": src_rel, "kind": kind, "bytes": f.stat().st_size,
                    "lastwrite": "", "md5_source": h, "md5_copy": h, "verify": "OK"}

        rows = [row("code/a.py", "crawlers/a.py", "code"),
                row("tools/geo/d.json", "tools/geo/d.json", "data")]
        with open(base / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

        def runv(*args):
            env = dict(os.environ, BASELINE_DIR=str(base), BASELINE_AGENT=str(agent),
                       PYTHONIOENCODING="utf-8")
            p = subprocess.run([PY, str(HERE / "verify_baseline.py"), "--check-source"] + list(args),
                               cwd=str(AGENT_REAL), env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            return p.returncode, p.stdout.decode("utf-8", "replace")

        rc, _ = runv("--strict")
        out.append(("分离：干净（应通过）", rc == 0, "rc=%d" % rc))

        data_src.write_text('{"a":2}\n', encoding="utf-8")
        rc, t = runv("--strict")
        out.append(("data 改内容：strict 通过但报告", rc == 0 and "data" in t, "rc=%d" % rc))

        data_src.write_text("{oops", encoding="utf-8")
        rc, t = runv()
        out.append(("data 坏 JSON：非 strict 也失败", rc == 1 and "JSON" in t, "rc=%d" % rc))

        data_src.write_text('{"a":2}\n', encoding="utf-8")
        code_src.write_text("x=2\n", encoding="utf-8")
        rc, t = runv("--strict")
        out.append(("code 改内容：strict 失败", rc == 1 and "code" in t, "rc=%d" % rc))
    return out


CASES = [
    ("干净状态（应通过）", None, 0, None),
    ("追加 1 条重复记录", inject_add_duplicate, 1, "duplicate_count"),
    ("删掉字段 abolish_date", inject_drop_field, 1, "field_count"),
    ("报告 status 改成 failed", inject_report_status, 1, "status"),
    ("导出 csv 删掉一列", inject_csv_column, 1, "csv_cols"),
    ("测试日志少一条 PASS", inject_tests_log, 1, "passed"),
    ("删掉测试日志（不能假绿）", inject_delete_tests_log, 1, "测试日志不存在"),
    ("复原后再跑（应通过）", None, 0, None),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    agent, pristine, base, missing = build_sandbox()
    print("=" * 70)
    print("阶段0 基线护栏 · 故障注入测试")
    print("=" * 70)
    print("沙箱: %s" % ROOT)
    if missing:
        print("!! 缺少源文件，无法建沙箱: %s" % missing)
        return 2

    rc, out = run("baseline_snapshot.py", agent, base)
    if rc != 0:
        print("!! 沙箱基线生成失败 rc=%d" % rc)
        print(out)
        return 2
    print("沙箱基线已生成\n")

    passed = failed = 0
    for i, (name, inject, expect_rc, expect_key) in enumerate(CASES, 1):
        reset(agent, pristine)
        if inject:
            inject(agent)
        rc, out = run("baseline_compare.py", agent, base)

        ok = (rc == expect_rc)
        note = ""
        if ok and expect_key:
            ok = (expect_key in out)
            if not ok:
                note = "（退出码对，但输出里没提到 %s）" % expect_key
        if ok:
            passed += 1
            print("  PASS  %d. %-26s rc=%d%s" % (i, name, rc, ("  [%s]" % expect_key) if expect_key else ""))
        else:
            failed += 1
            print("  FAIL  %d. %-26s 期望 rc=%d 实际 rc=%d %s"
                  % (i, name, expect_rc, rc, note))
            tail = "\n".join(out.splitlines()[-12:])
            print("        ---- 输出尾部 ----")
            for line in tail.splitlines():
                print("        " + line)

    reset(agent, pristine)

    print("")
    print(VERIFY_CASES_DOC.strip())
    print("")
    for i, (name, ok2, detail) in enumerate(verify_cases(REAL_BASE), 1):
        if ok2:
            passed += 1
            print("  PASS  V%d. %-26s %s" % (i, name, detail))
        else:
            failed += 1
            print("  FAIL  V%d. %-26s %s" % (i, name, detail))

    for i, (name, ok3, detail) in enumerate(separation_cases(), 1):
        if ok3:
            passed += 1
            print("  PASS  S%d. %-30s %s" % (i, name, detail))
        else:
            failed += 1
            print("  FAIL  S%d. %-30s %s" % (i, name, detail))

    print("=" * 70)
    print("结果: %d/%d 通过" % (passed, passed + failed))
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())