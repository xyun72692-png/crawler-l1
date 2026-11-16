# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""改写 115/116/119 断言 + 新增 123/124/125/126。"""
from pathlib import Path

P = Path(str(_HOME / "tests" / "test_crawler.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# ---------------- 115：M ≤ 计划 → 夹紧、success、cov 1.0 ----------------
sub('''        ok = (r.returncode == 3
              and rep.get("reason") == "page_range_truncated"
              and rep.get("pages_declared") == 3
              and rep.get("pages_planned") == 5
              and rep.get("pages_effective") == 3
              and rep.get("truncated") is True
              and rep.get("coverage") == 1.0)
        record("115. 声明 3 页 < 计划 5 页 → 截断 + partial", ok,''',
    '''        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("pages_declared") == 3
              and rep.get("pages_planned") == 5
              and rep.get("pages_effective") == 3
              and rep.get("truncated") is False
              and rep.get("coverage") == 1.0)
        record("115. 声明 3 页 ≤ 计划 5 页 → 夹紧到 3、success、coverage=1.0", ok,''',
    "115 断言")

# ---------------- 116：M > 计划 → partial、cov 0.3 ----------------
sub('''        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("pages_declared") == 10
              and rep.get("truncated") is False
              and rep.get("coverage") == 0.3)
        record("116. 声明 10 页 > 计划 3 页 → 不截断，coverage=0.3", ok,''',
    '''        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("reason") == "page_range_truncated"
              and rep.get("pages_declared") == 10
              and rep.get("truncated") is True
              and rep.get("coverage") == 0.3)
        record("116. 声明 10 页 > 计划 3 页 → partial/page_range_truncated，coverage=0.3", ok,''',
    "116 断言")

# ---------------- 119：续跑 → success、cov 1.0 ----------------
sub('''        ok = (rep.get("pages_declared") == 3 and rep.get("truncated") is True
              and rep.get("stats", {}).get("pages_skipped", 0) >= 1
              and rep.get("stats", {}).get("pages_ok", 0) == 2)
        record("119. 续跑跳过第 1 页仍读到 M=3", ok,''',
    '''        ok = (rep.get("pages_declared") == 3 and rep.get("truncated") is False
              and rep.get("coverage") == 1.0
              and rep.get("stats", {}).get("pages_skipped", 0) >= 1
              and rep.get("stats", {}).get("pages_ok", 0) == 2)
        record("119. 续跑跳过第 1 页仍读到 M=3（success、coverage=1.0）", ok,''',
    "119 断言")

# ---------------- 新增 123–126 ----------------
ANCHOR = '''    print("")\n    print("=" * 66)\n    passed = sum('''
NEW = r'''    # ---------- 123 noop 续跑：pages_ok=0 但 coverage 必须 1.0 ----------
    begin_case("c123")
    p = start_mock("none")
    try:
        crawl(["--site", "mocktotal", "--job", "nop1"],
              env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3"})
        r2 = crawl(["--site", "mocktotal", "--job", "nop1"],
                   env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3"})
        rep = latest_report("nop1") or {}
        st = rep.get("stats", {})
        ok = (st.get("pages_ok", -1) == 0 and rep.get("coverage") == 1.0
              and rep.get("pages_declared") == 3)
        record("123. noop 续跑：pages_ok=0 但 coverage=1.0", ok,
               "pages_ok=%s coverage=%s declared=%s status=%s"
               % (st.get("pages_ok"), rep.get("coverage"), rep.get("pages_declared"),
                  rep.get("status")))
    finally:
        stop_mock(p)

    # ---------- 124 站点没配 pattern → 不写 anomaly ----------
    begin_case("c124")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--job", "nopat", "--pages", "1"])
        rep = latest_report("nopat") or {}
        ok = (r.returncode == 0 and (rep.get("anomalies") or []) == []
              and rep.get("pages_declared") is None)
        record("124. 未配 pattern 的站点：静默跳过、anomalies 为空", ok,
               "rc=%s anomalies=%s declared=%s"
               % (r.returncode, len(rep.get("anomalies") or []), rep.get("pages_declared")))
    finally:
        stop_mock(p)

    # ---------- 125 window 模式：M > 计划 也算正常收工 ----------
    begin_case("c125")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocktotal", "--job", "win1"],
                  env_extra={"MOCK_TOTAL": "10", "MOCK_PLAN": "2",
                             "MOCK_COVERAGE_MODE": "window"})
        rep = latest_report("win1") or {}
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("truncated") is True
              and rep.get("coverage") == 0.2)
        record("125. coverage_mode=window：窗口模式 success，coverage=0.2", ok,
               "rc=%s status=%s truncated=%s coverage=%s"
               % (r.returncode, rep.get("status"), rep.get("truncated"), rep.get("coverage")))
    finally:
        stop_mock(p)

    # ---------- 126 页大小探测：第 2 页重叠 → broken_pagination ----------
    begin_case("c126")
    p = start_mock("none")
    try:
        port = CASE["port"]
        env = dict(os.environ)
        env.update({"PYTHONIOENCODING": "utf-8", "MOCK_PORT": str(port),
                    "MOCK_PS_BROKEN": "1",
                    "CRAWLER_STATE_DIR": CASE["state"],
                    "CRAWLER_OUT_DIR": str(Path(CASE["dir"]) / "data"),
                    "CRAWLER_LOG_DIR": str(Path(CASE["dir"]) / "log"),
                    "CRAWLER_REPORT_DIR": str(Path(CASE["dir"]) / "report")})
        rr = subprocess.run(
            [PY, str(Path(str(_HOME / "scripts" / "probe_pagesize.py"))),
             "--site", "mockprobe", "--param", "size", "--value", "8", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            timeout=120)
        try:
            data = json.loads(rr.stdout)
        except Exception:
            data = {}
        ok = (rr.returncode == 3 and data.get("verdict") == "broken_pagination")
        record("126. 页大小探测：第 2 页重叠 → broken_pagination（rc=3）", ok,
               "rc=%s verdict=%s note=%s"
               % (rr.returncode, data.get("verdict"), (data.get("note") or "")[:40]))
    finally:
        stop_mock(p)

''' + ANCHOR

s = s.replace(ANCHOR, NEW, 1)
P.write_text(s, encoding="utf-8", newline="\n")
print("测试已更新：115/116/119 改写 + 123–126 新增")