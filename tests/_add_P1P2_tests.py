# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""追加 106–109：为 P1-1 / P1-2 / P2-1+P2-2 / P2-3 建回归测试。"""
from pathlib import Path

P = Path(str(_HOME / "tests" / "test_crawler.py"))
s = P.read_text(encoding="utf-8")
ANCHOR = '''    print("")\n    print("=" * 66)\n    passed = sum('''
assert s.count(ANCHOR) == 1

NEW = r'''    # =================================================================
    # P1/P2 回归（106–109）
    # =================================================================

    # ---------- 106 软封时报告里 stop_reason 必须写上 ----------
    begin_case("c106")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocksoft", "--job", "sbr"],
                  env_extra={"MOCKSOFT_MODE": "blocked"})
        rep = latest_report("sbr") or {}
        ok = (r.returncode == 6
              and rep.get("reason") == "soft_block_suspected"
              and rep.get("stop_reason") == "soft_block_suspected")
        record("106. 软封时 stop_reason=soft_block_suspected（不被空值覆盖）", ok,
               "reason=%s stop_reason=%r"
               % (rep.get("reason"), rep.get("stop_reason")))
    finally:
        stop_mock(p)

    # ---------- 107 证据里的字节/响应头来自被拦页，不是 canary ----------
    begin_case("c107")
    p = start_mock("none")
    try:
        crawl(["--site", "mocksoft", "--job", "sbmeta"],
              env_extra={"MOCKSOFT_MODE": "blocked"})
        cds = list((Path(CASE["state"])).glob("_cooldown_*.json"))
        ev = json.loads(cds[0].read_text(encoding="utf-8"))["evidence"] if cds else {}
        # mock 里列表页和 canary 的假页内容不同：列表页 50 字节，canary 46 字节
        ok = bool(cds) and ev.get("resp_bytes") != ev.get("canary_bytes")
        record("107. 证据 resp_bytes 来自被拦页（与 canary 字节可区分）", ok,
               "resp_bytes=%s canary_bytes=%s"
               % (ev.get("resp_bytes"), ev.get("canary_bytes")))
    finally:
        stop_mock(p)

    # ---------- 108 冷却退出时报告能查到 until；软封页有单独计数 ----------
    begin_case("c108")
    p = start_mock("none")
    try:
        # 先跑一次软封，拿到冷却文件
        crawl(["--site", "mocksoft", "--job", "cd1"],
              env_extra={"MOCKSOFT_MODE": "blocked"})
        rep1 = latest_report("cd1") or {}
        sb_pages = rep1.get("stats", {}).get("pages_soft_blocked")
        # 再跑一次 → 被冷却挡
        r2 = crawl(["--site", "mocksoft", "--job", "cd2"],
                   env_extra={"MOCKSOFT_MODE": "ok"})
        rep2 = latest_report("cd2") or {}
        cd = rep2.get("cooldown") or {}
        ok = (r2.returncode == 6 and rep2.get("reason") == "cooldown_active"
              and sb_pages == 1
              and bool(cd.get("until")) and cd.get("strikes") == 1)
        record("108. 冷却报告带 until；软封页计入 pages_soft_blocked", ok,
               "soft_blocked_pages=%s cooldown.until=%s strikes=%s"
               % (sb_pages, cd.get("until"), cd.get("strikes")))
    finally:
        stop_mock(p)

    # ---------- 109 冷却按 group：换端口（换 host）也能拦住 ----------
    begin_case("c109")
    p1 = start_mock("none")
    try:
        crawl(["--site", "mocksoft", "--job", "g1"],
              env_extra={"MOCKSOFT_MODE": "blocked", "MOCKSOFT_GROUP": "wzrc"})
        cds = [x.name for x in Path(CASE["state"]).glob("_cooldown_*.json")]
    finally:
        stop_mock(p1)
    p2 = start_mock("none")
    try:
        port2 = CASE["port"]
        r2 = crawl(["--site", "mocksoft", "--job", "g2"],
                   env_extra={"MOCKSOFT_MODE": "ok", "MOCKSOFT_GROUP": "wzrc"})
        rep2 = latest_report("g2") or {}
        ok = (cds == ["_cooldown_wzrc.json"]
              and r2.returncode == 6 and rep2.get("reason") == "cooldown_active")
        record("109. 冷却按 group 锁：换 host（端口 %d）仍被拦" % port2, ok,
               "冷却文件=%s rc=%s reason=%s"
               % (cds, r2.returncode, rep2.get("reason")))
    finally:
        stop_mock(p2)

'''

s = s.replace(ANCHOR, NEW + ANCHOR, 1)
P.write_text(s, encoding="utf-8", newline="\n")
print("已追加 106–109")