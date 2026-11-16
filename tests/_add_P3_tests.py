# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""追加 110–112：P3-2 / P3-5+P3-3 / P3-4+P3-1。"""
from pathlib import Path

# mockspa 支持软封开关（用于 P3-2 的 json+soft_block 冲突）
p = Path(str(_HOME / "crawlers" / "sites" / "mockspa.py"))
s = p.read_text(encoding="utf-8")
if "MOCKSPA_SOFT" not in s:
    s = s.replace('MODE = os.environ.get("MOCKSPA_MODE", "api")',
                  'MODE = os.environ.get("MOCKSPA_MODE", "api")\nSOFT = os.environ.get("MOCKSPA_SOFT", "")   # "1" = 开软封（测 json 冲突）')
    s = s.replace('if MODE == "api":',
                  'if SOFT == "1":\n    CONFIG["soft_block"] = {"enabled": True,\n                            "canary_url": BASE + "/spa/index.html"}\n\nif MODE == "api":')
    p.write_text(s, encoding="utf-8", newline="\n")
    print("mockspa 支持 MOCKSPA_SOFT")

P = Path(str(_HOME / "tests" / "test_crawler.py"))
s = P.read_text(encoding="utf-8")
ANCHOR = '''    print("")\n    print("=" * 66)\n    passed = sum('''
assert s.count(ANCHOR) == 1

NEW = r'''    # =================================================================
    # P3 回归（110–112）
    # =================================================================

    # ---------- 110 json + soft_block → 启动即拒绝（假安全不能留） ----------
    begin_case("c110")
    p = start_mock("none")
    try:
        before = int((http_probe_json(p, "/api/hits?p=/spa/api/list").get("data") or {}).get("hits") or 0)
        r = crawl(["--site", "mockspa", "--job", "jsonsoft"],
                  env_extra={"MOCKSPA_MODE": "api", "MOCKSPA_SOFT": "1"})
        after = int((http_probe_json(p, "/api/hits?p=/spa/api/list").get("data") or {}).get("hits") or 0)
        rep = latest_report("jsonsoft") or {}
        ok = (r.returncode == 1 and rep.get("reason") == "soft_block_incompatible"
              and before == after)
        record("110. json + soft_block → 拒绝启动（rc=1，零请求）", ok,
               "rc=%s reason=%s 命中 %d→%d"
               % (r.returncode, rep.get("reason"), before, after))
    finally:
        stop_mock(p)

    # ---------- 111 冷却文件损坏 → fail-closed；字节数取 content ----------
    begin_case("c111")
    p = start_mock("none")
    try:
        port = CASE["port"]
        host = "127.0.0.1:%d" % port
        cdp = Path(CASE["state"]) / ("_cooldown_%s.json" % host.replace(":", "_"))
        cdp.write_text("{ 这不是合法 JSON ", encoding="utf-8")
        before = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        r = crawl(["--site", "mocksoft", "--job", "badcd"],
                  env_extra={"MOCKSOFT_MODE": "ok"})
        after = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        rep = latest_report("badcd") or {}
        cd = rep.get("cooldown") or {}
        # P3-3：_note_resp 用 content 而不是 text.encode
        import crawler as _c3

        class _Fake:
            content = "中文".encode("utf-8")     # 6 字节
            text = "中文再中文再中文"              # 故意更长
            headers = {}
            url = "http://x/"
        _c3._note_resp(_Fake())
        bytes_ok = _c3._LAST_META["bytes"] == len(_Fake.content)
        ok = (r.returncode == 6 and rep.get("reason") == "cooldown_active"
              and cd.get("reason") == "cooldown_file_corrupt"
              and before == after and bytes_ok)
        record("111. 冷却文件损坏 → fail-closed；字节数用 content", ok,
               "rc=%s reason=%s cooldown.reason=%s 命中 %d→%d bytes_content=%s"
               % (r.returncode, rep.get("reason"), cd.get("reason"), before, after, bytes_ok))
    finally:
        stop_mock(p)

    # ---------- 112 冷却中仍可 --rebuild-index；canary 过 robots ----------
    begin_case("c112")
    p = start_mock("none")
    try:
        port = CASE["port"]
        host = "127.0.0.1:%d" % port
        cdp = Path(CASE["state"]) / ("_cooldown_%s.json" % host.replace(":", "_"))
        cdp.write_text(json.dumps({
            "host": host,
            "until": (datetime.now(timezone(timedelta(hours=8)))
                      + timedelta(hours=2)).isoformat(timespec="seconds"),
            "reason": "soft_block_suspected", "strikes": 1,
            "evidence": {}, "updated_at": "2026-11-11T00:00:00+08:00"},
            ensure_ascii=False), encoding="utf-8")
        r = crawl(["--site", "mocksoft", "--job", "rb", "--rebuild-index"])
        rep = latest_report("rb") or {}

        # P3-1：canary 被 robots 禁止时，probe_canary 必须"无法判定"而不是当软封
        import crawler as _c1
        old_robots = dict(_c1._ROBOTS)
        try:
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(["User-agent: *", "Disallow: /soft/canary.html"])
            _c1._ROBOTS["loaded"] = True
            _c1._ROBOTS["parser"] = rp
            cards, nb, skip = _c1.probe_canary(
                None, lambda *a, **k: None,
                {"canary_url": "http://127.0.0.1:%d/soft/canary.html" % port},
                lambda html, u: [1, 2])
            robots_ok = (cards is None and skip == "robots_denied")
        finally:
            _c1._ROBOTS.clear()
            _c1._ROBOTS.update(old_robots)

        ok = (r.returncode == 0 and rep.get("reason") == "rebuild_index_only"
              and robots_ok)
        record("112. 冷却中 --rebuild-index 仍可跑；canary 也过 robots", ok,
               "rc=%s reason=%s canary_skip=%s"
               % (r.returncode, rep.get("reason"), "robots_denied" if robots_ok else "未拦"))
    finally:
        stop_mock(p)

'''

s = s.replace(ANCHOR, NEW + ANCHOR, 1)
if "import urllib.robotparser" not in s:
    s = s.replace("import subprocess\n", "import subprocess\nimport urllib.robotparser\n", 1)
P.write_text(s, encoding="utf-8", newline="\n")
print("已追加 110–112")