# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""新增用例 127/128：筛选条件指纹（换条件清断点、同条件不清）。"""
from pathlib import Path

P = Path(str(_HOME / "tests" / "test_crawler.py"))
s = P.read_text(encoding="utf-8")
ANCHOR = '''    print("")\n    print("=" * 66)\n    passed = sum('''
assert s.count(ANCHOR) == 1

NEW = r'''    # ---------- 127 同一 job 换筛选 → 旧断点作废，不能静默跳过 ----------
    begin_case("c127")
    p = start_mock("none")
    try:
        # 第一次：筛选 f=alpha，抓满 3 页
        crawl(["--site", "mocktotal", "--job", "fp1"],
              env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3", "MOCK_FILTER": "alpha"})
        st_path = Path(CASE["state"]) / "state_fp1.json"
        st1 = json.loads(st_path.read_text(encoding="utf-8"))
        fp1 = st1.get("filters_fp")
        # 第二次：同一 job，换成 f=beta
        r2 = crawl(["--site", "mocktotal", "--job", "fp1"],
                   env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3", "MOCK_FILTER": "beta"})
        rep2 = latest_report("fp1") or {}
        st2 = json.loads(st_path.read_text(encoding="utf-8"))
        stt = rep2.get("stats", {})
        ok = (bool(fp1) and st2.get("filters_fp") not in ("", fp1)
              and stt.get("pages_skipped", 0) == 0      # 旧断点没把新条件拦住
              and stt.get("pages_ok", 0) == 3           # 真的重新抓了 3 页
              and rep2.get("coverage") == 1.0)
        record("127. 换筛选条件 → 旧断点作废、重新抓满", ok,
               "fp %s→%s skipped=%s ok=%s coverage=%s"
               % (fp1, st2.get("filters_fp"), stt.get("pages_skipped"),
                  stt.get("pages_ok"), rep2.get("coverage")))
    finally:
        stop_mock(p)

    # ---------- 128 同一 job 同筛选 → 断点保留，第二跑全跳过（noop） ----------
    begin_case("c128")
    p = start_mock("none")
    try:
        crawl(["--site", "mocktotal", "--job", "fp2"],
              env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3", "MOCK_FILTER": "same"})
        st_path = Path(CASE["state"]) / "state_fp2.json"
        fp1 = json.loads(st_path.read_text(encoding="utf-8")).get("filters_fp")
        r2 = crawl(["--site", "mocktotal", "--job", "fp2"],
                   env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3", "MOCK_FILTER": "same"})
        rep2 = latest_report("fp2") or {}
        st2 = json.loads(st_path.read_text(encoding="utf-8"))
        stt = rep2.get("stats", {})
        ok = (st2.get("filters_fp") == fp1
              and stt.get("pages_skipped", 0) == 3      # 同条件 → 全部按断点跳过
              and stt.get("pages_ok", 0) == 0
              and rep2.get("status") == "noop")
        record("128. 同筛选条件 → 断点保留、第二跑全跳过", ok,
               "fp相同=%s skipped=%s ok=%s status=%s"
               % (st2.get("filters_fp") == fp1, stt.get("pages_skipped"),
                  stt.get("pages_ok"), rep2.get("status")))
    finally:
        stop_mock(p)

''' + ANCHOR

s = s.replace(ANCHOR, NEW, 1)
P.write_text(s, encoding="utf-8", newline="\n")
print("已追加 127/128")