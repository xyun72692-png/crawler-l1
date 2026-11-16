# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""阶段A 测试（95–105）追加到 test_crawler.py。

编号说明：原计划的 92–102 已被现有用例占用（92 坏 JSONL、93/94 SPA 两层），
所以这里顺延为 95–105，功能一一对应，不改旧编号（改编号会让基线对不上）。
"""
from pathlib import Path

P = Path(str(_HOME / "tests" / "test_crawler.py"))
s = P.read_text(encoding="utf-8")

ANCHOR = '''    print("")\n    print("=" * 66)\n    passed = sum('''
assert s.count(ANCHOR) == 1, "锚点不是唯一"

NEW = r'''    # =================================================================
    # 阶段A：Retry-After / 软封 / 冷却 / Referer（95–105）
    # =================================================================

    # ---------- 95 429 + Retry-After: 2 → 真按 2 秒等 ----------
    begin_case("c95")
    p = start_mock("none")
    try:
        t0 = time.time()
        r = crawl(["--site", "mockra", "--job", "ra_sec"],
                  env_extra={"MOCKRA_MODE": "sec"})
        dt = time.time() - t0
        rep = latest_report("ra_sec") or {}
        st = rep.get("stats", {})
        lg = read_log_file(CRAWLER_LOG_A) if CRAWLER_LOG_A else ""
        ok = (r.returncode == 0 and st.get("retry_after_waits") == 1
              and st.get("retry_after_max_sec") == 2
              and 1.8 <= dt <= 6.0
              and "Retry-After=2s" in lg)
        record("95. 429 + Retry-After: 2 → 按 2 秒等（读的是响应头）", ok,
               "waits=%s max=%s 耗时=%.1fs 日志含头=%s"
               % (st.get("retry_after_waits"), st.get("retry_after_max_sec"), dt,
                  "Retry-After=2s" in lg))
    finally:
        stop_mock(p)

    # ---------- 96 429 + Retry-After: HTTP-date ----------
    begin_case("c96")
    p = start_mock("none")
    try:
        t0 = time.time()
        r = crawl(["--site", "mockra", "--job", "ra_date"],
                  env_extra={"MOCKRA_MODE": "date"})
        dt = time.time() - t0
        rep = latest_report("ra_date") or {}
        st = rep.get("stats", {})
        lg = read_log_file(CRAWLER_LOG_A) if CRAWLER_LOG_A else ""
        ok = (r.returncode == 0 and st.get("retry_after_waits") == 1
              and 1 <= st.get("retry_after_max_sec", 0) <= 6
              and 1.0 <= dt <= 8.0
              and "Retry-After=" in lg)
        record("96. 429 + Retry-After: HTTP-date → 解析成秒并等待", ok,
               "max=%s 耗时=%.1fs 日志含=%s"
               % (st.get("retry_after_max_sec"), dt, "Retry-After=" in lg))
    finally:
        stop_mock(p)

    # ---------- 97 429 无 Retry-After → 回退退避，行为不变 ----------
    begin_case("c97")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockra", "--job", "ra_none"],
                  env_extra={"MOCKRA_MODE": "none"})
        rep = latest_report("ra_none") or {}
        st = rep.get("stats", {})
        lg = read_log_file(CRAWLER_LOG_A) if CRAWLER_LOG_A else ""
        ok = (r.returncode == 0 and st.get("retry_after_waits") == 1
              and st.get("retry_after_max_sec") == 0     # 0.3s 取整为 0
              and "退避=" in lg and "Retry-After=" not in lg)
        record("97. 429 无 Retry-After → 用退避（日志写明来源）", ok,
               "waits=%s max=%s 含退避=%s 含RA头=%s"
               % (st.get("retry_after_waits"), st.get("retry_after_max_sec"),
                  "退避=" in lg, "Retry-After=" in lg))
    finally:
        stop_mock(p)

    # ---------- 98 空页 + canary 也空 → 软封，且之后零页面请求 ----------
    begin_case("c98")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocksoft", "--job", "soft_blocked"],
                  env_extra={"MOCKSOFT_MODE": "blocked"})
        rep = latest_report("soft_blocked") or {}
        st = rep.get("stats", {})
        h1 = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        h2 = int((http_probe_json(p, "/api/hits?p=/soft/p2.html").get("data") or {}).get("hits") or 0)
        hc = int((http_probe_json(p, "/api/hits?p=/soft/canary.html").get("data") or {}).get("hits") or 0)
        ok = (r.returncode == 6 and rep.get("status") == "failed"
              and rep.get("reason") == "soft_block_suspected"
              and st.get("soft_block_detected") == 1
              and st.get("canary_requests") == 1
              and h1 == 1 and h2 == 0 and hc == 1)
        record("98. 空页+canary 也空 → 软封 rc=6，第 2 页 0 次请求", ok,
               "rc=%s reason=%s p1=%d p2=%d canary=%d"
               % (r.returncode, rep.get("reason"), h1, h2, hc))
    finally:
        stop_mock(p)

    # ---------- 99 空页 + canary 有卡片 → 不误判，按原 empty 逻辑继续 ----------
    begin_case("c99")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocksoft", "--job", "soft_ok"],
                  env_extra={"MOCKSOFT_MODE": "ok"})
        rep = latest_report("soft_ok") or {}
        st = rep.get("stats", {})
        ok = (rep.get("status") == "partial"
              and rep.get("reason") == "empty_page_seen"
              and st.get("soft_block_detected") in (0, None)
              and st.get("canary_requests") == 1        # 只探一次
              and st.get("pages_total", 0) >= 2)        # 没有被软封打断，继续翻页
        record("99. 空页但 canary 有卡片 → 仍 partial/empty_page_seen（不误判）", ok,
               "status=%s reason=%s canary=%s pages_total=%s"
               % (rep.get("status"), rep.get("reason"), st.get("canary_requests"),
                  st.get("pages_total")))
    finally:
        stop_mock(p)

    # ---------- 100 冷却未到期 → rc=6 且零请求 ----------
    begin_case("c100")
    p = start_mock("none")
    try:
        port = CASE["port"]
        host = "127.0.0.1:%d" % port
        cdp = Path(CASE["state"]) / ("_cooldown_%s.json" % host)
        cdp.write_text(json.dumps({
            "host": host,
            "until": (datetime.now(timezone(timedelta(hours=8)))
                      + timedelta(hours=2)).isoformat(timespec="seconds"),
            "reason": "soft_block_suspected", "strikes": 1,
            "evidence": {"page_url": "x", "resp_bytes": 3103, "canary_bytes": 3103},
            "updated_at": "2026-11-11T00:00:00+08:00"}, ensure_ascii=False),
            encoding="utf-8")
        before = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        r = crawl(["--site", "mocksoft", "--job", "cool"],
                  env_extra={"MOCKSOFT_MODE": "ok"})
        after = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        rep = latest_report("cool") or {}
        ok = (r.returncode == 6 and rep.get("reason") == "cooldown_active"
              and before == after)
        record("100. 冷却未到期 → rc=6，页面请求计数不变", ok,
               "rc=%s reason=%s 命中 %d→%d"
               % (r.returncode, rep.get("reason"), before, after))
    finally:
        stop_mock(p)

    # ---------- 101 冷却已过期 → 正常抓，不再报 cooldown_active ----------
    begin_case("c101")
    p = start_mock("none")
    try:
        port = CASE["port"]
        host = "127.0.0.1:%d" % port
        cdp = Path(CASE["state"]) / ("_cooldown_%s.json" % host)
        cdp.write_text(json.dumps({
            "host": host,
            "until": (datetime.now(timezone(timedelta(hours=8)))
                      - timedelta(minutes=5)).isoformat(timespec="seconds"),
            "reason": "soft_block_suspected", "strikes": 1,
            "evidence": {}, "updated_at": "2026-11-11T00:00:00+08:00"},
            ensure_ascii=False), encoding="utf-8")
        r = crawl(["--site", "mocksoft", "--job", "cool2"],
                  env_extra={"MOCKSOFT_MODE": "ok"})
        rep = latest_report("cool2") or {}
        ok = (r.returncode != 6 and rep.get("reason") != "cooldown_active"
              and rep.get("stats", {}).get("pages_total", 0) >= 1)
        record("101. 冷却已过期 → 正常运行", ok,
               "rc=%s reason=%s pages_total=%s"
               % (r.returncode, rep.get("reason"), rep.get("stats", {}).get("pages_total")))
    finally:
        stop_mock(p)

    # ---------- 102 Referer：第 1 页站点根，第 2 页上一页 URL ----------
    begin_case("c102")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockref", "--job", "refjob"])
        rows = read_rows(str(Path(CASE["dir"]) / "data" / "refjob.jsonl"))
        port = CASE["port"]
        want1 = "http://127.0.0.1:%d/" % port
        want2 = "http://127.0.0.1:%d/echo/ref?page=1" % port
        got = sorted({str(x.get("title") or "") for x in rows})
        ok = (r.returncode == 0 and len(rows) == 2
              and want1 in got and want2 in got)
        record("102. Referer：第 1 页=站点根，第 2 页=上一页 URL", ok,
               "实测=%s" % got)
    finally:
        stop_mock(p)

    # ---------- 103 WZ_SETTR 装配：3 生效 / 9 报错 ----------
    begin_case("c103")
    try:
        import importlib
        import sites.wzrc_all as _wz
        os.environ["WZ_SETTR"] = "3"
        _wz = importlib.reload(_wz)
        url_ok = "settr=3" in _wz.CONFIG["url_template"]
        delay_ok = (_wz.CONFIG["delay_min"], _wz.CONFIG["delay_max"]) == (3.0, 5.0)
        pages_ok = _wz.CONFIG["page_end"] == 40
        bad = None
        os.environ["WZ_SETTR"] = "9"
        try:
            importlib.reload(_wz)
        except SystemExit as e:
            bad = str(e)
        os.environ.pop("WZ_SETTR", None)
        importlib.reload(_wz)
        ok = url_ok and delay_ok and pages_ok and bad is not None
        record("103. WZ_SETTR=3 生效（3~5 秒/40 页），=9 直接报错", ok,
               "url含settr=%s 间隔=%s 页数=%s 非法值=%s"
               % (url_ok, delay_ok, pages_ok, "已拦截" if bad else "没拦"))
    finally:
        pass

    # ---------- 104 报告新字段是真实值 ----------
    begin_case("c104")
    p = start_mock("none")
    try:
        crawl(["--site", "mocksoft", "--job", "fields"],
              env_extra={"MOCKSOFT_MODE": "ok"})
        rep = latest_report("fields") or {}
        st = rep.get("stats", {})
        need = ["resp_bytes_min", "resp_bytes_total", "cards_total",
                "canary_requests", "soft_block_detected",
                "retry_after_waits", "retry_after_max_sec"]
        missing = [k for k in need if k not in st]
        ok = (not missing and st.get("resp_bytes_min", 0) > 0
              and st.get("resp_bytes_total", 0) >= st.get("resp_bytes_min", 0)
              and st.get("canary_requests") == 1)
        record("104. 报告含 resp_bytes/cards/canary/soft_block/retry_after", ok,
               "缺失=%s min=%s total=%s cards=%s"
               % (missing, st.get("resp_bytes_min"), st.get("resp_bytes_total"),
                  st.get("cards_total")))
    finally:
        stop_mock(p)

    # ---------- 105 真实样本离线回归：cards>0，且不是被软封页 ----------
    begin_case("c105")
    try:
        import sites.wzrc_all as _wz2
        smp = Path(str(_HOME / "data" / "raw" / "_probe_wzrc.html"))
        html = smp.read_text(encoding="utf-8", errors="replace")
        rows = _wz2.parse_list(html, "https://www.wzrc.net/index.php?x=1")
        markers = ["no_page_group"]
        hit = [m for m in markers if m in html]
        ok = (smp.exists() and len(rows) > 0 and not hit
              and Path(CASE["dir"]).exists())   # 本用例全程没建 mock、没发请求
        record("105. 真实样本离线：cards>0 且无软封标记（0 请求）", ok,
               "cards=%d bytes=%d 软封标记=%s" % (len(rows), len(html), hit))
    finally:
        pass

'''

s = s.replace(ANCHOR, NEW + ANCHOR, 1)
P.write_text(s, encoding="utf-8", newline="\n")
print("已追加 95–105")