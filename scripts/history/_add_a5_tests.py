# -*- coding: utf-8 -*-
"""把 A5 的两条用例插进 test_crawler.py（139 跨天必重抓 / 140 full 不受影响）。"""
from pathlib import Path

P = Path(r"D:\agent-work\tests\test_crawler.py")
t = P.read_text(encoding="utf-8")

# 1) 补 import
if "from datetime import date, timedelta" not in t:
    old = "import json\n"
    assert old in t
    t = t.replace(old, "import json\nfrom datetime import date, timedelta\n", 1)

# 2) 插入用例函数（放在 def main 之前）
FUNC = '''
def a5_cases():
    """A5：window 模式的时间维度断点（跨天作废 + 只看前 N 页 + 提前停）。"""
    # ---------- 139 核心验收：跨天后第 1 页必须重抓 ----------
    begin_case("c139")
    p = start_mock("none")
    try:
        job = "a5w"
        crawl(["--site", "mockwindow", "--job", job, "--allow-empty"])
        st_path = Path(CASE["state"]) / ("state_%s.json" % job)
        st1 = json.loads(st_path.read_text(encoding="utf-8"))
        done1 = sorted(st1.get("pages_done") or [])
        at1 = dict(st1.get("pages_done_at") or {})
        rep1 = latest_report(job) or {}
        # 把每一页的日期戳改成"昨天" —— 模拟隔天再跑同一个 job
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        st1["pages_done_at"] = {k: yesterday for k in at1}
        st_path.write_text(json.dumps(st1, ensure_ascii=False), encoding="utf-8")

        crawl(["--site", "mockwindow", "--job", job, "--allow-empty"])
        rep2 = latest_report(job) or {}
        stt2 = rep2.get("stats", {})
        st2 = json.loads(st_path.read_text(encoding="utf-8"))
        at2 = st2.get("pages_done_at") or {}
        today = date.today().isoformat()
        ok = (len(done1) >= 1
              and stt2.get("pages_total", 0) >= 1          # 真的发了请求
              and stt2.get("pages_ok", 0) >= 1             # 第 1 页真的重抓了
              and stt2.get("pages_skipped", 0) == 0        # 没有被"已完成"挡掉
              and rep2.get("status") != "noop"             # 不是"看起来已完成"
              and all(v == today for v in at2.values()))   # 戳已翻新成今天
        record("139. A5 window 跨天 → 断点作废、第 1 页重抓（不再永远已完成）", ok,
               "首轮 done=%s → 跨天后 total=%s ok=%s skipped=%s status=%s 戳全新=%s"
               % (done1, stt2.get("pages_total"), stt2.get("pages_ok"),
                  stt2.get("pages_skipped"), rep2.get("status"),
                  all(v == today for v in at2.values())))
    finally:
        stop_mock(p)

    # ---------- 140 对照：full 模式跨天 → 断点必须保留 ----------
    begin_case("c140")
    p = start_mock("none")
    try:
        job = "a5f"
        crawl(["--site", "mock", "--pages", "2", "--job", job])
        st_path = Path(CASE["state"]) / ("state_%s.json" % job)
        st1 = json.loads(st_path.read_text(encoding="utf-8"))
        done1 = sorted(st1.get("pages_done") or [])
        # 就算硬塞一个旧戳，full 模式也不该看它（它没有"时间维度"这回事）
        st1["pages_done_at"] = {str(x): "2020-01-01" for x in done1}
        st_path.write_text(json.dumps(st1, ensure_ascii=False), encoding="utf-8")

        crawl(["--site", "mock", "--pages", "2", "--job", job])
        rep2 = latest_report(job) or {}
        stt2 = rep2.get("stats", {})
        ok = (len(done1) >= 2
              and stt2.get("pages_skipped", 0) >= 2       # 全被断点跳过
              and stt2.get("pages_ok", 0) == 0
              and rep2.get("status") == "noop")
        record("140. A5 full 模式跨天 → 断点保留、照旧续跑（window 不污染 full）", ok,
               "done=%s → skipped=%s ok=%s status=%s"
               % (done1, stt2.get("pages_skipped"), stt2.get("pages_ok"),
                  rep2.get("status")))
    finally:
        stop_mock(p)


def main():
'''
if "def a5_cases():" not in t:
    assert "def main():\n" in t
    t = t.replace("def main():\n", FUNC, 1)

# 3) main 里调用（放在 138 之后）
if "    a5_cases()" not in t:
    marker = 'record("138.'
    i = t.index(marker)
    # 找到该 record(...) 语句结束的右括号所在行
    j = t.index("\n", t.index(")", t.index('"138.')))
    t = t[:j + 1] + "    a5_cases()\n" + t[j + 1:]

P.write_text(t, encoding="utf-8")
print("已插入 a5_cases 并在 main 调用")
print("含 139/140:", "139. A5" in t, "140. A5" in t)