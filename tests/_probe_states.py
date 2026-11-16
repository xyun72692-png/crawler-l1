# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""先探一遍：8 种状态到底怎么触发、rc 与 reason 是不是如预期（不写测试，只看事实）。"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PY = sys.executable
AGENT = Path(str(_HOME))
CRAWLER = AGENT / "crawlers" / "crawler.py"
MOCK = AGENT / "tests" / "mock_site.py"


def start_mock(robots="none"):
    p = subprocess.Popen([PY, str(MOCK), "--port", "0", "--robots", robots],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, encoding="utf-8", errors="replace")
    line = p.stdout.readline()
    port = int(line.strip().split("=", 1)[1])
    time.sleep(0.3)
    return p, port


def run(port, args, state, extra_env=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["MOCK_PORT"] = str(port)
    env["CRAWLER_OUT_DIR"] = str(state / "data")
    env["CRAWLER_LOG_DIR"] = str(state / "log")
    env["CRAWLER_STATE_DIR"] = str(state / "state")
    env["CRAWLER_REPORT_DIR"] = str(state / "report")
    for k, v in (extra_env or {}).items():
        env[k] = v
    for d in ("data", "log", "state", "report"):
        (state / d).mkdir(parents=True, exist_ok=True)
    r = subprocess.run([PY, str(CRAWLER)] + args, capture_output=True, text=True,
                       env=env, encoding="utf-8", errors="replace", timeout=120)
    reps = sorted((state / "report").glob("report-*.json"))
    rep = json.loads(reps[-1].read_text(encoding="utf-8")) if reps else {}
    return r.returncode, rep.get("status"), rep.get("reason"), rep.get("stats", {}), r.stdout


CASES = [
    ("131 all_pages_failed", ["--site", "mockstates", "--job", "s_failall"], {"MOCK_STATE": "failall"}, "none"),
    ("132 some_items_failed", ["--site", "mockstates", "--job", "s_failsome"], {"MOCK_STATE": "failsome"}, "none"),
    ("133 blocked_by_robots", ["--site", "mockstates", "--job", "s_blocked"], {"MOCK_STATE": "blocked"}, "forbid-all"),
    ("134 bad_paginate_mode", ["--site", "mockstates", "--job", "s_bogus"], {"MOCK_STATE": "bogus"}, "none"),
    ("135 bad_total_scope", ["--site", "mockstates", "--job", "s_scope"], {"MOCK_STATE": "badscope"}, "none"),
    ("136 empty_page_range", ["--site", "mockstates", "--job", "s_range", "--page-from", "5", "--pages", "3"], {"MOCK_STATE": "normal"}, "none"),
    ("137 missing_parse_next", ["--site", "mocknonext", "--job", "s_nonext"], {}, "none"),
    ("138 nothing_done(测法1: next二跑)", ["--site", "mocknext", "--job", "s_nd1"], {}, "none"),
]

tmp = Path(tempfile.mkdtemp(prefix="probe_states_"))
for name, args, extra, robots in CASES:
    d = tmp / name.split()[0]
    p, port = start_mock(robots)
    try:
        if "nothing_done" in name:
            run(port, args, d, extra)          # 第一跑
            rc, st, rs, stt, out = run(port, args, d, extra)   # 第二跑
        else:
            rc, st, rs, stt, out = run(port, args, d, extra)
        print("%-34s rc=%-2s %-8s %-28s pages(ok/skip/fail/blk/empty)=%s/%s/%s/%s/%s"
              % (name, rc, st, rs,
                 stt.get("pages_ok"), stt.get("pages_skipped"), stt.get("pages_failed"),
                 stt.get("pages_blocked"), stt.get("pages_empty")))
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()