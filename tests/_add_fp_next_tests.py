# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""新增用例 129/130：next 模式换筛选 → 断点（含 urls_done/next_url）也要清。"""
from pathlib import Path

P = Path(str(_HOME / "tests" / "test_crawler.py"))
s = P.read_text(encoding="utf-8")
ANCHOR = '''    print("")\n    print("=" * 66)\n    passed = sum('''
assert s.count(ANCHOR) == 1

NEW = r'''    # ---------- 129 next 模式换筛选 → urls_done/next_url 也要清干净 ----------
    begin_case("c129")
    p = start_mock("none")
    try:
        crawl(["--site", "mocknext", "--job", "nf1"],
              env_extra={"MOCKNEXT_FILTER": "alpha"})
        st_path = Path(CASE["state"]) / "state_nf1.json"
        st1 = json.loads(st_path.read_text(encoding="utf-8"))
        first_fp = st1.get("filters_fp")
        urls1 = list(st1.get("urls_done") or [])
        # 换成 beta：旧 urls_done / next_url 必须清空，并且要重新抓（不能 noop）
        r2 = crawl(["--site", "mocknext", "--job", "nf1"],
                   env_extra={"MOCKNEXT_FILTER": "beta"})
        rep2 = latest_report("nf1") or {}
        stt = rep2.get("stats", {})
        st2 = json.loads(st_path.read_text(encoding="utf-8"))
        ok = (bool(first_fp) and st2.get("filters_fp") not in ("", first_fp)
              and stt.get("pages_ok", 0) >= 1          # 真的重新抓了
              and rep2.get("status") != "noop"         # 不是"看起来已完成"
              and all(("f=alpha") not in u for u in (st2.get("urls_done") or [])))
        record("129. next 模式换筛选 → urls_done/next_url 清空并重抓", ok,
               "fp %s→%s pages_ok=%s status=%s 旧URL残留=%s"
               % (first_fp, st2.get("filters_fp"), stt.get("pages_ok"),
                  rep2.get("status"),
                  any(("f=alpha") in u for u in (st2.get("urls_done") or []))))
    finally:
        stop_mock(p)

    # ---------- 130 next 模式同筛选 → 断点保留，第二跑 noop ----------
    begin_case("c130")
    p = start_mock("none")
    try:
        crawl(["--site", "mocknext", "--job", "nf2"],
              env_extra={"MOCKNEXT_FILTER": "same"})
        st_path = Path(CASE["state"]) / "state_nf2.json"
        fp1 = json.loads(st_path.read_text(encoding="utf-8")).get("filters_fp")
        urls1 = list(json.loads(st_path.read_text(encoding="utf-8")).get("urls_done") or [])
        r2 = crawl(["--site", "mocknext", "--job", "nf2"],
                   env_extra={"MOCKNEXT_FILTER": "same"})
        rep2 = latest_report("nf2") or {}
        stt = rep2.get("stats", {})
        st2 = json.loads(st_path.read_text(encoding="utf-8"))
        ok = (st2.get("filters_fp") == fp1
              and len(urls1) >= 2                       # 第一跑确实记了断点
              and len(st2.get("urls_done") or []) >= 2  # 第二跑没被清掉
              and stt.get("records_new", 0) == 0)
        record("130. next 模式同筛选 → 断点保留、第二跑不新增", ok,
               "fp相同=%s urls_done %d→%d 新增=%s"
               % (st2.get("filters_fp") == fp1, len(urls1),
                  len(st2.get("urls_done") or []), stt.get("records_new")))
    finally:
        stop_mock(p)

''' + ANCHOR

s = s.replace(ANCHOR, NEW, 1)
P.write_text(s, encoding="utf-8", newline="\n")
print("已追加 129/130")