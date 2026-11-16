# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""补 8 条状态断言（用例 131–138），把 130 项补到 138 项。"""
from pathlib import Path

P = Path(str(_HOME / "tests" / "test_crawler.py"))
s = P.read_text(encoding="utf-8")
ANCHOR = '''    print("")\n    print("=" * 66)\n    passed = sum('''
assert s.count(ANCHOR) == 1

NEW = r'''    # ================= 状态断言补齐（131–138）=================
    # 这 8 种 finalize 组合此前一条用例都没有（27 种状态 − 已断言 19 种）。
    # 「全绿」不等于「重构安全」，先把它们钉死。

    # ---------- 131 全部页面失败 ----------
    begin_case("c131")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockstates", "--job", "s_failall"],
                  env_extra={"MOCK_STATE": "failall"})
        rep = latest_report("s_failall") or {}
        stt = rep.get("stats", {})
        ok = (r.returncode == 4 and rep.get("status") == "failed"
              and rep.get("reason") == "all_pages_failed"
              and stt.get("pages_ok", -1) == 0 and stt.get("pages_failed", 0) == 2)
        record("131. 全部页面 500 → failed/all_pages_failed（rc=4）", ok,
               "rc=%s %s/%s ok=%s failed=%s"
               % (r.returncode, rep.get("status"), rep.get("reason"),
                  stt.get("pages_ok"), stt.get("pages_failed")))
    finally:
        stop_mock(p)

    # ---------- 132 部分页面失败（未熔断）----------
    begin_case("c132")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockstates", "--job", "s_failsome"],
                  env_extra={"MOCK_STATE": "failsome"})
        rep = latest_report("s_failsome") or {}
        stt = rep.get("stats", {})
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("reason") == "some_items_failed"
              and stt.get("pages_ok", 0) == 1 and stt.get("pages_failed", 0) == 1)
        record("132. 1 页成功 + 1 页失败 → partial/some_items_failed（rc=3）", ok,
               "rc=%s %s/%s ok=%s failed=%s"
               % (r.returncode, rep.get("status"), rep.get("reason"),
                  stt.get("pages_ok"), stt.get("pages_failed")))
    finally:
        stop_mock(p)

    # ---------- 133 所有页被 robots 禁止（入口 robots 本身可读）----------
    begin_case("c133")
    p = start_mock("forbid-all")
    try:
        r = crawl(["--site", "mockstates", "--job", "s_blocked"],
                  env_extra={"MOCK_STATE": "blocked"})
        rep = latest_report("s_blocked") or {}
        stt = rep.get("stats", {})
        ok = (r.returncode == 4 and rep.get("status") == "failed"
              and rep.get("reason") == "all_pages_blocked_by_robots"
              and stt.get("pages_blocked", 0) == 2 and stt.get("pages_ok", -1) == 0)
        record("133. 全部页被 robots 拒 → failed/all_pages_blocked_by_robots（rc=4）", ok,
               "rc=%s %s/%s blocked=%s ok=%s"
               % (r.returncode, rep.get("status"), rep.get("reason"),
                  stt.get("pages_blocked"), stt.get("pages_ok")))
    finally:
        stop_mock(p)

    # ---------- 134 paginate 配了非法值 ----------
    begin_case("c134")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockstates", "--job", "s_bogus"],
                  env_extra={"MOCK_STATE": "bogus"})
        rep = latest_report("s_bogus") or {}
        ok = (r.returncode == 1 and rep.get("status") == "failed"
              and rep.get("reason") == "bad_paginate_mode"
              and rep.get("stats", {}).get("pages_total", 0) == 0)
        record("134. paginate 非法 → failed/bad_paginate_mode（rc=1，零请求）", ok,
               "rc=%s %s/%s pages_total=%s"
               % (r.returncode, rep.get("status"), rep.get("reason"),
                  rep.get("stats", {}).get("pages_total")))
    finally:
        stop_mock(p)

    # ---------- 135 json.total_scope 非法 ----------
    begin_case("c135")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockstates", "--job", "s_scope"],
                  env_extra={"MOCK_STATE": "badscope"})
        rep = latest_report("s_scope") or {}
        ok = (r.returncode == 1 and rep.get("status") == "failed"
              and rep.get("reason") == "bad_total_scope")
        record("135. json.total_scope 非法 → failed/bad_total_scope（rc=1）", ok,
               "rc=%s %s/%s" % (r.returncode, rep.get("status"), rep.get("reason")))
    finally:
        stop_mock(p)

    # ---------- 136 页范围倒置（page_from > pages）----------
    begin_case("c136")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockstates", "--job", "s_range",
                   "--page-from", "5", "--pages", "3"],
                  env_extra={"MOCK_STATE": "normal"})
        rep = latest_report("s_range") or {}
        ok = (r.returncode == 1 and rep.get("status") == "failed"
              and rep.get("reason") == "empty_page_range")
        record("136. page_from > pages → failed/empty_page_range（rc=1）", ok,
               "rc=%s %s/%s" % (r.returncode, rep.get("status"), rep.get("reason")))
    finally:
        stop_mock(p)

    # ---------- 137 next 模式缺少 parse_next ----------
    begin_case("c137")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocknonext", "--job", "s_nonext"])
        rep = latest_report("s_nonext") or {}
        ok = (r.returncode == 1 and rep.get("status") == "failed"
              and rep.get("reason") == "missing_parse_next"
              and rep.get("stats", {}).get("pages_total", 0) == 0)
        record("137. next 模式没写 parse_next → failed/missing_parse_next（rc=1）", ok,
               "rc=%s %s/%s pages_total=%s"
               % (r.returncode, rep.get("status"), rep.get("reason"),
                  rep.get("stats", {}).get("pages_total")))
    finally:
        stop_mock(p)

    # ---------- 138 什么都没做（next 模式二跑：断点说没有下一页）----------
    begin_case("c138")
    p = start_mock("none")
    try:
        crawl(["--site", "mocknext", "--job", "s_nd1"])
        r2 = crawl(["--site", "mocknext", "--job", "s_nd1"])
        rep = latest_report("s_nd1") or {}
        stt = rep.get("stats", {})
        ok = (r2.returncode == 0 and rep.get("status") == "noop"
              and rep.get("reason") == "nothing_done"
              and stt.get("pages_ok", -1) == 0 and stt.get("pages_skipped", -1) == 0)
        record("138. 二跑无页可抓 → noop/nothing_done（rc=0）", ok,
               "rc=%s %s/%s ok=%s skipped=%s"
               % (r2.returncode, rep.get("status"), rep.get("reason"),
                  stt.get("pages_ok"), stt.get("pages_skipped")))
    finally:
        stop_mock(p)

''' + ANCHOR

s = s.replace(ANCHOR, NEW, 1)
P.write_text(s, encoding="utf-8", newline="\n")
print("已追加用例 131–138")