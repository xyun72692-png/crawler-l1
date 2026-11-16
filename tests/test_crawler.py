# -*- coding: utf-8 -*-
"""
爬虫故障注入测试（全程本地，不访问外网）

覆盖 codex 要求的场景：
  1. 正常抓取
  2. 空页不标记完成
  3. 连续 3 页空 → 熔断
  4. --allow-empty 允许空页完成
  5. robots.txt 返回 403 → 拒绝抓取并退出
  6. robots 允许 p1、禁止 p2 → p2 被 blocked
  7. 403 页面不重试
  8. --rebuild-index 不发任何请求
  9. dedup_key 写错 → 中止而不是静默失效
 10. 页范围为空 → 明确报错

跑法：
    python tests\\test_crawler.py
"""

import sys as _sys0
from pathlib import Path as _path0
_sys0.path.insert(0, str(_path0(__file__).resolve().parents[1] / "crawlers"))
from identity import UA as _identity_ua  # noqa: E402  ← 唯一身份源
import http.client
import json
from datetime import date, timedelta
import os
import shutil
import socket
import subprocess
import urllib.robotparser
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- CI 编码护栏（v14.13.20）------------------------------------------------
# 为什么需要：GitHub 的 windows runner 默认 locale 是 cp1252，子进程（crawler.py）
# 往管道里打中文会抛 UnicodeEncodeError；而本机是中文 Windows（cp936）能编码中文，
# 所以这个坑只在 CI 暴露。v14.13.19 的 test_crawler 就栽在这一点上。
# 这里统一给「本进程 + 它启动的子进程」钉死 UTF-8。
import os as _os_enc
_os_enc.environ.setdefault("PYTHONIOENCODING", "utf-8")
_os_enc.environ.setdefault("PYTHONUTF8", "1")
# ---------------------------------------------------------------------------


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# =====================================================================
# 隔离基础设施（2026-11-10 重写）
#
# 原来的问题：所有用例共用 8765 端口 + 共用 data/raw、manifests、logs、out\reports。
# 结果是一个用例的残留会污染下一个用例（"robots 设置失效""行数对不上"都是这么来的），
# 而且失败信息全指向错误方向，排查成本极高。
#
# 现在的规矩：
#   1. 每个用例一个独立端口（--port 0 让系统分配，mock 把自己绑到的端口打印出来）
#   2. start_mock 必须验证：进程活着 + 端口真的在监听 + 应答确实是我们的 mock
#   3. stop_mock 必须等到进程退出 + 端口释放
#   4. 每个用例一个独立临时目录，data/state/log/report 全部落在里面
#
# 并行安全（2026-11-11 加）：
#   同一台机器上可能同时有多个会话在跑这套测试（例如两个 agent 并行），
#   共用 logs\_cases 会互相删目录 / 数据翻倍 / 日志编码串台，
#   表现为 PermissionError(WinError 32)、rows 翻倍、UnicodeDecodeError。
#   因此临时根目录可用环境变量 CRAWLER_TEST_TMP 覆盖，各跑各的：
#       $env:CRAWLER_TEST_TMP = 'D:\agent-work\logs\_cases_lead'
#   默认值保持原样，单实例行为不变。
# =====================================================================
ROOT = Path(__file__).resolve().parents[1]
TMPROOT = Path(os.environ.get("CRAWLER_TEST_TMP") or (ROOT / "logs" / "_cases")).resolve()
PY = sys.executable
CRAWLER = str(ROOT / "crawlers" / "crawler.py")
ROOT_TOOLS = ROOT / "tools"
MOCK = str(ROOT / "tests" / "mock_site.py")

# 当前用例的上下文（由 begin_case 设置）
CASE = {"dir": None, "port": None, "name": None, "state": None}

# 这些是"当前用例"的路径，begin_case 会重新赋值。
# 保留模块级名字是为了让各个用例的断言代码保持原样。
RAW = STATE = CRAWLER_LOG = None
RAW_D = STATE_D = CRAWLER_LOG_D = None
RAW_N = STATE_N = CRAWLER_LOG_N = None
RAW_J = STATE_J = CRAWLER_LOG_J = None
RAW_A = STATE_A = CRAWLER_LOG_A = None
PORT = None

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("   " + detail) if detail else ""))


def begin_case(name):
    """开一个新用例：全新临时目录，data/state/log/report 各自独立。"""
    global RAW, STATE, CRAWLER_LOG, RAW_D, STATE_D, CRAWLER_LOG_D, PORT
    global RAW_N, STATE_N, CRAWLER_LOG_N, RAW_J, STATE_J, CRAWLER_LOG_J
    global RAW_A, STATE_A, CRAWLER_LOG_A
    d = TMPROOT / name
    if d.exists():
        shutil.rmtree(d)
    for sub in ("data", "state", "log", "report"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    CASE["dir"] = d
    CASE["state"] = str(d / "state")
    CASE["name"] = name
    CASE["port"] = None
    PORT = None

    RAW = str(d / "data" / "mock.jsonl")
    STATE = str(d / "state" / "state_mock.json")
    CRAWLER_LOG = str(d / "log" / "crawler-mock.log")
    RAW_D = str(d / "data" / "mockdetail.jsonl")
    STATE_D = str(d / "state" / "state_mockdetail.json")
    CRAWLER_LOG_D = str(d / "log" / "crawler-mockdetail.log")
    RAW_N = str(d / "data" / "mocknext.jsonl")
    STATE_N = str(d / "state" / "state_mocknext.json")
    CRAWLER_LOG_N = str(d / "log" / "crawler-mocknext.log")
    RAW_J = str(d / "data" / "mockjson.jsonl")
    STATE_J = str(d / "state" / "state_mockjson.json")
    CRAWLER_LOG_J = str(d / "log" / "crawler-mockjson.log")
    RAW_A = str(d / "data" / "mockattach.jsonl")
    STATE_A = str(d / "state" / "state_mockattach.json")
    CRAWLER_LOG_A = str(d / "log" / "crawler-mockattach.log")
    return d


def case_env(extra=None):
    """每个子进程都要带上的隔离环境：4 个目录 + 当前端口。"""
    d = CASE["dir"]
    env = {
        "CRAWLER_OUT_DIR": str(d / "data"),
        "CRAWLER_LOG_DIR": str(d / "log"),
        "CRAWLER_STATE_DIR": str(d / "state"),
        "CRAWLER_REPORT_DIR": str(d / "report"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # 端口只在"确实有 mock 在跑"时才注入。
    # 服务器关掉之后（比如 --rebuild-index 那个用例）不能写 "None" 进去，
    # 否则站点模块 int("None") 直接崩，报出来的错会指向完全无关的地方。
    if CASE.get("port"):
        env["MOCK_PORT"] = str(CASE["port"])
    if extra:
        env.update(extra)
    return env


def reset():
    """兼容旧写法：因为每个用例已经是全新目录，这里不需要再删东西。"""
    return


def reset_detail():
    return


def count_lines(path):
    if not path or not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for ln in f if ln.strip())


def port_in_use(port):
    """有进程在监听这个端口吗？（连得上就是有；connect 被拒就是没人）"""
    try:
        socket.create_connection(("127.0.0.1", port), 0.3).close()
        return True
    except OSError:
        return False


def http_probe(port, path="/robots.txt", timeout=3):
    """真发一个 HTTP 请求，确认应答来自我们的 mock。返回 (status, body)。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def http_probe_json(proc, path, timeout=3):
    """向 mock 要一段 JSON（用当前用例的端口）。"""
    port = CASE.get("port")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()


def start_mock(robots):
    """
    起一个 mock，端口由系统分配（--port 0），然后把真实端口读回来。

    三条都必须成立才返回，否则抛异常：
        1. 进程活着（没有启动即崩）
        2. 端口真的在监听（TCP 连得上）
        3. 应答确实是 mock（/robots.txt 的内容和 robots 模式对得上）
    只看"端口能连"是不够的 —— 那可能连到别人的残留进程。
    """
    global PORT
    p = subprocess.Popen([PY, MOCK, "--port", "0", "--robots", robots],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, encoding="utf-8", errors="replace")
    # mock 绑定成功后第一行就打印 PORT=<n>
    line = p.stdout.readline()
    if not line or not line.startswith("PORT="):
        rc = p.poll()
        try:
            p.kill()
        except Exception:
            pass
        raise RuntimeError("mock 没报告端口（rc=%s，首行=%r）" % (rc, line))

    port = int(line.strip().split("=", 1)[1])
    CASE["port"] = port
    PORT = port

    # 1) 进程活着
    if p.poll() is not None:
        raise RuntimeError("mock 报完端口就退出了（rc=%s）" % p.returncode)

    # 2) 端口真的在监听
    deadline = time.time() + 5
    while time.time() < deadline:
        if port_in_use(port):
            break
        time.sleep(0.05)
    else:
        p.kill()
        raise RuntimeError("mock 报了端口 %d，但连不上" % port)

    # 3) 应答确实是我们的 mock（用 robots 内容做指纹）
    expect = {
        "none": None,
        "allow": b"Allow: /",
        "deny-p2": b"Disallow: /v1/p2.html",
        "deny-detail": b"Disallow: /detail/",
        "deny-files": b"Disallow: /files-deny/",
        "robots500": None,
        "robots500once": None,
        "robotstimeoutonce": b"pong",   # 探活打的是 /__ping
        "crawldelay": b"Crawl-delay: 1",
        "forbid-all": b"Disallow: /\n",
        "err403": None,
        "html": b"Access Verification",
    }[robots]
    try:
        if robots == "robotstimeoutonce":
            status, body = http_probe(port, "/__ping", timeout=5)
        else:
            status, body = http_probe(port)
    except Exception as e:
        p.kill()
        raise RuntimeError("mock 端口 %d 不响应 HTTP：%s" % (port, e))

    if robots == "none" and status != 404:
        p.kill()
        raise RuntimeError("mock robots=none 应返回 404，实际 %d（端口 %d 上可能不是我们的进程）"
                           % (status, port))
    if robots == "err403" and status != 403:
        p.kill()
        raise RuntimeError("mock robots=err403 应返回 403，实际 %d" % status)
    if robots == "robots500" and status != 500:
        p.kill()
        raise RuntimeError("mock robots=robots500 应返回 500，实际 %d" % status)
    if expect is not None and expect not in body:
        p.kill()
        raise RuntimeError("mock 应答内容与 robots=%s 不符（body=%r）" % (robots, body[:80]))

    return p


def stop_mock(p):
    """停掉 mock，并且等到进程真的退出、端口真的释放。"""
    port = CASE["port"]
    try:
        p.terminate()
    except Exception:
        pass
    try:
        p.wait(timeout=5)
    except Exception:
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:
            pass

    # 收掉管道，避免资源警告
    try:
        p.stdout.close()
    except Exception:
        pass

    if p.returncode is None:
        raise RuntimeError("mock 进程没有退出（pid=%s）" % p.pid)

    if port:
        deadline = time.time() + 5
        while time.time() < deadline:
            if not port_in_use(port):
                CASE["port"] = None
                return
            time.sleep(0.05)
        raise RuntimeError("mock 已退出，但端口 %d 仍在监听（有别的进程占着？）" % port)


def crawl(args, timeout=90, env_extra=None):
    env = dict(os.environ)
    env.update(case_env(env_extra))
    r = subprocess.run([PY, CRAWLER] + args,
                       capture_output=True, text=True, env=env,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r


def read_log_file(path):
    if not path or not Path(path).exists():
        return ""
    # errors="replace"：日志里若混进非 UTF-8 字节（例如旧进程写过 GBK），
    # 不能让整套测试因为解码失败而中断——断言会自然失败，我们能看到是哪一条。
    return Path(path).read_text(encoding="utf-8", errors="replace")


def read_rows(path):
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                out.append(json.loads(ln))
    return out


def read_log():
    return read_log_file(CRAWLER_LOG)


def latest_report(job):
    """读当前用例目录里该 job 最新的报告 JSON（报告名带毫秒，字典序即时间序）。"""
    d = CASE["dir"] / "report"
    fs = sorted(d.glob("report-%s-*.json" % job))
    if not fs:
        return None
    try:
        with open(fs[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None



def a5_cases():
    """A5：window 模式的时间维度断点（跨天作废 + 只看前 N 页 + 提前停）。"""
    # ---------- 139 核心验收：跨天后第 1 页必须重抓 ----------
    begin_case("c209")
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
        record("209. A5 window 跨天 → 断点作废、第 1 页重抓（不再永远已完成）", ok,
               "首轮 done=%s → 跨天后 total=%s ok=%s skipped=%s status=%s 戳全新=%s"
               % (done1, stt2.get("pages_total"), stt2.get("pages_ok"),
                  stt2.get("pages_skipped"), rep2.get("status"),
                  all(v == today for v in at2.values())))
    finally:
        stop_mock(p)

    # ---------- 140 对照：full 模式跨天 → 断点必须保留 ----------
    begin_case("c210")
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
        record("210. A5 full 模式跨天 → 断点保留、照旧续跑（window 不污染 full）", ok,
               "done=%s → skipped=%s ok=%s status=%s"
               % (done1, stt2.get("pages_skipped"), stt2.get("pages_ok"),
                  rep2.get("status")))
    finally:
        stop_mock(p)

    # ---------- 211 同一天连跑两次：第二次必须重抓，不能 noop ----------
    # mockwindow 用 /v5 路由：每页 5 条，3 页 = 15 条（正好是阈值 15 的口径）。
    begin_case("c211")
    p = start_mock("none")
    try:
        job = "a5s"
        crawl(["--site", "mockwindow", "--job", job])
        rep1 = latest_report(job) or {}
        n1 = rep1.get("stats", {}).get("records_new", 0)
        crawl(["--site", "mockwindow", "--job", job])
        rep2 = latest_report(job) or {}
        stt2 = rep2.get("stats", {})
        ok = (n1 >= 15
              and stt2.get("pages_total", 0) == 3      # 3 页都发了请求
              and stt2.get("pages_ok", 0) == 3         # 3 页都算处理完
              and stt2.get("pages_skipped", 0) == 0    # 一个都没被断点挡掉
              and rep2.get("status") != "noop"
              and stt2.get("records_new", -1) == 0)    # 靠 seen_keys 去重，不重复写
        record("211. A5 window 同一天连跑两次 → 第二次仍重抓 3 页（不是 noop）", ok,
               "首轮 new=%s → 二轮 total=%s ok=%s skipped=%s new=%s status=%s"
               % (n1, stt2.get("pages_total"), stt2.get("pages_ok"),
                  stt2.get("pages_skipped"), stt2.get("records_new"),
                  rep2.get("status")))
    finally:
        stop_mock(p)

    # ---------- 212 3 页全重复 → refresh_no_new（阈值 15）----------
    begin_case("c212")
    p = start_mock("none")
    try:
        job = "a5r"
        crawl(["--site", "mockwindow", "--job", job])
        crawl(["--site", "mockwindow", "--job", job])
        rep = latest_report(job) or {}
        stt = rep.get("stats", {})
        ok = (rep.get("reason") == "refresh_no_new"      # 提前停的专用 reason
              and stt.get("records_dup", 0) >= 15        # 15 条全见过
              and stt.get("pages_ok", 0) == 3            # 但 3 页都算处理完
              and rep.get("status") == "success")        # window 下没新数据=正常收工
        record("212. A5 3 页全重复 → refresh_no_new（阈值 15）且仍报 success", ok,
               "reason=%s dup=%s ok=%s status=%s"
               % (rep.get("reason"), stt.get("records_dup"),
                  stt.get("pages_ok"), rep.get("status")))
    finally:
        stop_mock(p)


def swallow_cases():
    """213：静默异常统一入口 _swallow 的计数、分级与实际日志落点。

    v14.13.18 的承诺是「计数 + 关键路径额外写一行日志」，但当时 _swallow 里
    引用的 `log` 在模块作用域并不存在（NameError 被 except 吞掉），
    所以关键路径只计数、从不落日志。本用例同时钉住三件事：
      ① 普通标签只进 _SWALLOWED
      ② 关键标签进 _SWALLOW_CRITICAL
      ③ 关键标签真的把一行日志交给注入的日志器
    """
    import crawler as engine
    engine._SWALLOWED.clear()
    engine._SWALLOW_CRITICAL.clear()
    got = []
    old = getattr(engine, "_ACTIVE_LOG", None)
    engine._ACTIVE_LOG = got.append
    try:
        engine._swallow("download_attachments", ValueError("cleanup"))
        engine._swallow("hash", RuntimeError("bad hash"))
    finally:
        engine._ACTIVE_LOG = old
    ok = (len(engine._SWALLOWED) == 2
          and [t for t, _ in engine._SWALLOWED] == ["download_attachments", "hash"]
          and len(engine._SWALLOW_CRITICAL) == 1
          and engine._SWALLOW_CRITICAL[0][0] == "hash"
          and len(got) == 1 and "hash" in got[0])
    record("213. _swallow 计数 + critical 分级 + 关键路径日志真实落点", ok,
           "all=%d critical=%s logged=%d"
           % (len(engine._SWALLOWED),
              [t for t, _ in engine._SWALLOW_CRITICAL], len(got)))


def main():
    # 每次开跑先清掉上一轮的用例目录，避免陈旧文件混进来
    if TMPROOT.exists():
        shutil.rmtree(TMPROOT)
    TMPROOT.mkdir(parents=True, exist_ok=True)

    print("=" * 66)
    a5_cases()
    swallow_cases()
    print("爬虫故障注入测试（本地 mock，无外网）")
    print("=" * 66)

    # ---------- 1 正常 ----------
    begin_case("c01")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--pages", "2", "--reset"])
        n = count_lines(RAW)
        record("1. 正常抓 2 页 → 6 条", (r.returncode == 0 and n == 6),
               "rc=%d lines=%d" % (r.returncode, n))
    finally:
        stop_mock(p)

    # ---------- 2 空页不标记完成 ----------
    begin_case("c02")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--pages", "3", "--reset"])
        n = count_lines(RAW)
        state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
        pages_done = state.get("pages_done", [])
        ok = (n == 6 and 3 not in pages_done and "不标记为完成" in read_log())
        record("2. 第 3 页空 → 不标记完成", ok,
               "lines=%d pages_done=%s" % (n, pages_done))
    finally:
        stop_mock(p)

    # ---------- 3 连续空页熔断 ----------
    begin_case("c03")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--pages", "5", "--reset"])
        log = read_log()
        ok = ("连续 3 页解析出 0 条" in log and "中止" in log)
        record("3. 连续 3 页空 → 熔断中止", ok, "见日志" if ok else "日志里没有熔断提示")
    finally:
        stop_mock(p)

    # ---------- 4 --allow-empty ----------
    begin_case("c04")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--pages", "3", "--reset", "--allow-empty"])
        state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
        pages_done = state.get("pages_done", [])
        ok = (3 in pages_done)
        record("4. --allow-empty → 空页算完成", ok, "pages_done=%s" % pages_done)
    finally:
        stop_mock(p)

    # ---------- 5 robots 403 ----------
    begin_case("c05")
    reset()
    p = start_mock("err403")
    try:
        r = crawl(["--site", "mock", "--pages", "2", "--reset"])
        n = count_lines(RAW)
        log = read_log()
        ok = (r.returncode == 2 and n == 0 and "视为不允许" in log)
        record("5. robots.txt 403 → 拒绝并退出", ok,
               "rc=%d lines=%d" % (r.returncode, n))
    finally:
        stop_mock(p)

    # ---------- 6 robots 逐页禁止 ----------
    begin_case("c06")
    reset()
    p = start_mock("deny-p2")
    try:
        r = crawl(["--site", "mock", "--pages", "2", "--reset"])
        n = count_lines(RAW)
        log = read_log()
        ok = (n == 3 and "robots 禁止抓取该页" in log and "p2.html" in log)
        record("6. robots 禁 p2 → 只抓 p1（3 条）", ok,
               "lines=%d" % n)
    finally:
        stop_mock(p)

    # ---------- 6b robots 200 但内容是 HTML → fail-closed ----------
    begin_case("c06b")
    reset()
    p = start_mock("html")
    try:
        r = crawl(["--site", "mock", "--pages", "2", "--reset"])
        n = count_lines(RAW)
        log = read_log()
        ok = (r.returncode == 2 and n == 0 and "不是 robots" in log)
        record("6b. robots 200 但内容是 HTML → 拒绝（fail-closed）", ok,
               "rc=%d lines=%d" % (r.returncode, n))
    finally:
        stop_mock(p)

    # ---------- 6c classify_robots 四态（含 552B 小 HTML） ----------
    begin_case("c06c")
    reset()
    try:
        import robots_rules as _rr
        cases = [
            ((404, "text/plain", ""), "absent"),
            ((403, "text/plain", ""), "denied"),
            ((500, "text/plain", ""), "denied"),
            ((200, "text/html", "<html></html>"), "unparsable"),
            ((200, "text/plain", "<html>" + "x" * 540 + "</html>"), "unparsable"),
            ((200, "text/plain", "User-agent: *\nDisallow: /\n"), "ok"),
            ((200, "text/html", "User-agent: *\nDisallow: /\n"), "ok"),
            ((200, "text/plain", ""), "ok"),
        ]
        got = [_rr.classify_robots(*a) for a, _ in cases]
        want = [e for _, e in cases]
        record("6c. classify_robots 四态（含 552B 小 HTML）", got == want,
               "%s" % (got if got != want else "7/7"))
    except Exception as e:
        record("6c. classify_robots 四态（含 552B 小 HTML）", False,
               "%s: %s" % (type(e).__name__, e))

    # ---------- 6d robots Crawl-delay 生效（列表页） ----------
    begin_case("c06d")
    reset()
    p = start_mock("crawldelay")
    try:
        t0 = time.time()
        r = crawl(["--site", "mock", "--pages", "2", "--reset"])
        elapsed = time.time() - t0
        log = read_log()
        reps = sorted((CASE["dir"] / "report").glob("*.json"))
        rep = json.loads(reps[-1].read_text(encoding="utf-8")) if reps else {}
        cd = (rep.get("robots") or {}).get("crawl_delay_sec")
        ok = (r.returncode == 0 and cd == 1.0
              and "Crawl-delay=1.0" in log and elapsed >= 1.0)
        record("6d. robots Crawl-delay=1 → 列表页按 1s 间隔", ok,
               "cd=%s elapsed=%.1fs" % (cd, elapsed))
    finally:
        stop_mock(p)

    # ---------- 6e 74cms 家族：golden 4 站逐字节一致 ----------
    begin_case("c06e")
    reset()
    try:
        import sites.wzrc_all as _wa
        import sites.wzrc_inc as _wi
        import sites.yqwzrc as _yq
        import sites.yqwzrc_wage as _yqw
        gold = json.loads((ROOT / "tests" / "data" / "qscms74_golden.json")
                          .read_text(encoding="utf-8"))
        mods = {"wzrc_all": _wa, "wzrc_inc": _wi,
                "yqwzrc": _yq, "yqwzrc_wage": _yqw}
        bad = []
        for _name, _mod in mods.items():
            raw = ((ROOT / "tests" / "data" / "qscms74") / (_name + "_p1.html")).read_bytes()
            rows = _mod.parse_list(raw.decode("utf-8"), gold[_name]["page_url"])
            if rows != gold[_name]["rows"]:
                bad.append(_name)
        record("6e. 74cms 家族 golden 4 站逐字节一致", not bad,
               "diff=%s" % (bad or "无"))
    except Exception as e:
        record("6e. 74cms 家族 golden 4 站逐字节一致", False,
               "%s: %s" % (type(e).__name__, e))

    # ---------- 7 403 不重试 ----------
    begin_case("c07")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--pages", "6", "--page-from", "6", "--reset"])
        log = read_log()
        # 403 只应出现一次（不重试）；"跳过（HTTP 403）"是主循环的另一条日志，不算重试
        occurrences = log.count("HTTP 403 被拒")
        ok = (occurrences == 1 and "不重试" in log)
        record("7. 403 页面 → 只尝试 1 次", ok, "「被拒」出现 %d 次" % occurrences)
    finally:
        stop_mock(p)

    # ---------- 8 rebuild-index 不发请求 ----------
    begin_case("c08")
    reset()
    # 先造点数据
    p = start_mock("none")
    try:
        crawl(["--site", "mock", "--pages", "1", "--reset"])
    finally:
        stop_mock(p)
    before = count_lines(RAW)
    # 关掉服务器再跑 rebuild-index —— 如果要发请求就会失败
    r = crawl(["--site", "mock", "--rebuild-index"])
    after = count_lines(RAW)
    ok = (r.returncode == 0 and before == after and "未请求任何页面" in r.stdout)
    record("8. --rebuild-index 零网络（服务器已关）", ok,
           "rc=%d lines=%d→%d %s" % (r.returncode, before, after,
                                     "" if ok else (r.stderr or r.stdout)[-200:].replace("\n", " ")))

    # ---------- 9 dedup_key 写错 ----------
    begin_case("c09")
    reset()
    p = start_mock("none")
    try:
        # 用一个不存在的去重键：临时改 sites/mock.py 里的 dedup_key 不方便，
        # 改用 CLI 无法覆盖，于是复制一份临时站点模块
        site_dir = str(ROOT / "crawlers" / "sites")
        tmp = os.path.join(site_dir, "_baddkey.py")
        src = open(os.path.join(site_dir, "mock.py"), encoding="utf-8").read()
        src = src.replace('"dedup_key": "detail_url"', '"dedup_key": "no_such_field"')
        src = src.replace('"job": "mock"', '"job": "mockbad"')
        open(tmp, "w", encoding="utf-8").write(src)
        try:
            r = crawl(["--site", "_baddkey", "--pages", "1", "--reset"])
            # 日志文件跟 job 同名：crawler-mockbad.log，落在本用例的 log 目录里
            badlog = os.path.join(CASE["dir"], "log", "crawler-mockbad.log")
            txt = open(badlog, encoding="utf-8").read() if os.path.exists(badlog) else ""
            ok = ("没有去重键字段" in txt and "中止" in txt)
            record("9. dedup_key 写错 → 中止", ok, "" if ok else "日志里没有中止提示")
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
            for f in (os.path.join(CASE["dir"], "log", "crawler-mockbad.log"),):
                try:
                    os.remove(f)
                except Exception:
                    pass
    finally:
        stop_mock(p)

    # ---------- 10 页范围为空 ----------
    begin_case("c10")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--page-from", "5", "--pages", "2"])
        ok = (r.returncode == 1 and "页范围为空" in r.stdout)
        record("10. --page-from 5 --pages 2 → 明确报错", ok, "rc=%d" % r.returncode)
    finally:
        stop_mock(p)

    # ---------- 11 500 重试后成功（退避生效） ----------
    begin_case("c11")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--page-from", "9", "--pages", "9", "--reset"])
        n = count_lines(RAW)
        log = read_log()
        retried = ("HTTP 500" in log) and ("重试" in log)
        ok = (n == 3 and retried)
        record("11. 500 两次后成功（退避重试生效）", ok,
               "lines=%d retried=%s" % (n, retried))
    finally:
        stop_mock(p)

    # ---------- 12 持续 500 → 重试耗尽后放弃 ----------
    begin_case("c12")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--page-from", "8", "--pages", "8", "--reset"])
        n = count_lines(RAW)
        log = read_log()
        ok = (n == 0 and "放弃这一页" in log)
        record("12. 持续 500 → 重试耗尽后放弃", ok, "lines=%d" % n)
    finally:
        stop_mock(p)

    # ---------- 13 慢响应 → 超时后放弃，不无限等 ----------
    begin_case("c13")
    reset()
    p = start_mock("none")
    try:
        t0 = time.time()
        r = crawl(["--site", "mock", "--page-from", "10", "--pages", "10", "--reset"])
        dt = time.time() - t0
        n = count_lines(RAW)
        log = read_log()
        timed_out = ("ReadTimeout" in log) or ("Timeout" in log)
        ok = (n == 0 and "放弃这一页" in log and dt < 40)
        record("13. 慢响应超时后放弃（不卡死）", ok,
               "lines=%d 耗时=%.1fs timeout_seen=%s" % (n, dt, timed_out))
    finally:
        stop_mock(p)

    # ---------- 14 报告里的 field_signature 必须非空 ----------
    begin_case("c14")
    reset()
    p = start_mock("none")
    try:
        crawl(["--site", "mock", "--pages", "1", "--reset"])
        rep = latest_report("mock")
        fc = (rep or {}).get("field_signature", {}).get("field_count", 0)
        fields = (rep or {}).get("field_signature", {}).get("fields", [])
        ok = (fc > 0 and len(fields) == fc and "detail_url" in fields)
        record("14. 报告 field_signature 非空", ok,
               "field_count=%d fields=%s" % (fc, ",".join(fields[:4])))
    finally:
        stop_mock(p)

    # ---------- 15 全部页面失败 → status=failed ----------
    begin_case("c15")
    reset()
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--page-from", "8", "--pages", "8", "--reset"])
        rep = latest_report("mock") or {}
        st = rep.get("status")
        stt = rep.get("stats", {})
        ok = (st == "failed" and r.returncode == 4
              and stt.get("pages_ok") == 0 and stt.get("pages_failed", 0) > 0)
        record("15. 全部页面失败 → status=failed", ok,
               "status=%s rc=%d ok=%s failed=%s" %
               (st, r.returncode, stt.get("pages_ok"), stt.get("pages_failed")))
    finally:
        stop_mock(p)

    # ---------- 16 部分页面失败 → status=partial ----------
    begin_case("c16")
    reset()
    p = start_mock("none")
    try:
        # p1 p2 正常，p3 起连续空页 → 熔断；pages_ok>0 且 pages_failed>0
        r = crawl(["--site", "mock", "--pages", "5", "--reset"])
        rep = latest_report("mock") or {}
        st = rep.get("status")
        stt = rep.get("stats", {})
        ok = (st == "partial" and r.returncode == 3
              and stt.get("pages_ok", 0) > 0 and stt.get("pages_failed", 0) > 0)
        record("16. 部分页面失败 → status=partial", ok,
               "status=%s rc=%d ok=%s failed=%s" %
               (st, r.returncode, stt.get("pages_ok"), stt.get("pages_failed")))
    finally:
        stop_mock(p)

    # =====================================================================
    # 阶段1：引擎通用详情流程（sites/mockdetail.py）
    # 这些用例验证"详情阶段由引擎负责"的行为，以及失败率熔断的口径。
    # =====================================================================

    def detail_env(kind, ratio="0.5", max_items="0", robots="0"):
        # 端口由 case_env() 通过 MOCK_PORT 统一注入，这里只管站点行为开关
        return {"MOCKDETAIL_KIND": kind, "MOCKDETAIL_RATIO": ratio,
                "MOCKDETAIL_MAX_ITEMS": max_items, "MOCKDETAIL_ROBOTS": robots}

    def run_detail(kind, ratio="0.5", max_items="0", robots="0", mock_robots="none",
                   reset_data=True):
        if reset_data:
            reset_detail()
        p = start_mock(mock_robots)
        try:
            r = crawl(["--site", "mockdetail", "--detail-mode", "generic"],
                      env_extra=detail_env(kind, ratio, max_items, robots))
        finally:
            stop_mock(p)
        return r, latest_report("mockdetail") or {}, read_rows(RAW_D), read_log_file(CRAWLER_LOG_D)

    def run_detail_twice(kind, ratio="0.5", max_items="0", robots="0",
                         mock_robots="none"):
        """
        同一个 mock 进程连跑两轮，只返回第二轮的日志增量。

        为什么必须同一个进程：flaky 模式的计数器在 mock 进程内存里，
        换进程就重置了，第二轮又会 500，测不出"补抓成功"。
        为什么只取增量：crawler 日志是 append 的，第一轮的"第 1/1 页"
        会一直留在文件里，不切掉就会误判"第二轮重抓了列表页"。
        """
        reset_detail()
        p = start_mock(mock_robots)
        try:
            env = detail_env(kind, ratio, max_items, robots)
            r1 = crawl(["--site", "mockdetail", "--detail-mode", "generic"],
                       env_extra=env)
            rep1 = latest_report("mockdetail") or {}
            rows1 = read_rows(RAW_D)
            lg_before = read_log_file(CRAWLER_LOG_D)

            r2 = crawl(["--site", "mockdetail", "--detail-mode", "generic"],
                       env_extra=env)
            rep2 = latest_report("mockdetail") or {}
            rows2 = read_rows(RAW_D)
            lg2 = read_log_file(CRAWLER_LOG_D)[len(lg_before):]
        finally:
            stop_mock(p)
        return r1, rep1, rows1, r2, rep2, rows2, lg2

    # ---------- 17 通用详情：全部成功 ----------
    begin_case("c17")
    r, rep, rows, lg = run_detail("ok")
    st = rep.get("stats", {})
    ok = (r.returncode == 0 and rep.get("status") == "success"
          and st.get("detail_ok") == 20 and st.get("detail_failed", 0) == 0
          and len(rows) == 20
          and all(x.get("detail_fetch") == "ok" for x in rows)
          and all(x.get("detail_http_status") == 200 for x in rows)
          and all(x.get("detail_fetched_at") for x in rows)
          and all(x.get("detail_title") for x in rows))
    record("17. 通用详情：20 条全成功", ok,
           "status=%s rc=%d ok=%s failed=%s rows=%d"
           % (rep.get("status"), r.returncode, st.get("detail_ok"),
              st.get("detail_failed"), len(rows)))

    # ---------- 18 熔断口径：20 条全 500，ratio=0.5 → 失败第 10 条后停 ----------
    begin_case("c18")
    # 这是 codex 指出的矛盾点：分母必须是"计划条数"，否则 20 条不可能失败到 20。
    r, rep, rows, lg = run_detail("fail", ratio="0.5")
    st = rep.get("stats", {})
    ok = (r.returncode == 3 and rep.get("status") == "partial"
          and rep.get("reason") == "detail_fail_ratio_exceeded"
          and st.get("detail_failed") == 10
          and st.get("detail_skipped") == 10
          and len(rows) == 20
          and sum(1 for x in rows if x.get("detail_fetch") == "skipped_aborted") == 10)
    record("18. 通用详情：失败率 0.5 → 第 10 条失败后熔断", ok,
           "status=%s reason=%s failed=%s skipped=%s"
           % (rep.get("status"), rep.get("reason"),
              st.get("detail_failed"), st.get("detail_skipped")))

    # ---------- 19 熔断阈值 1.0 → 20 条全部试过才停 ----------
    begin_case("c19")
    r, rep, rows, lg = run_detail("fail", ratio="1.0")
    st = rep.get("stats", {})
    ok = (r.returncode == 3 and rep.get("status") == "partial"
          and st.get("detail_failed") == 20 and st.get("detail_skipped", 0) == 0)
    record("19. 通用详情：阈值 1.0 → 跑完 20 条再报告", ok,
           "status=%s failed=%s skipped=%s" %
           (rep.get("status"), st.get("detail_failed"), st.get("detail_skipped")))

    # ---------- 20 详情 403 → 立刻整体停（不继续打剩下的） ----------
    begin_case("c20")
    r, rep, rows, lg = run_detail("forbid", ratio="0.5")
    ok = (r.returncode == 4 and rep.get("status") == "failed"
          and rep.get("reason") == "detail_http_403"
          and lg.count("详情返回 HTTP 403") == 1)
    record("20. 通用详情：403 立即中止", ok,
           "status=%s reason=%s 403次数=%d"
           % (rep.get("status"), rep.get("reason"), lg.count("详情返回 HTTP 403")))

    # ---------- 21 必填字段缺失 → detail_fetch=field_missing（不是 ok） ----------
    begin_case("c21")
    # max_items=5 → 只处理前 5 条，其余 15 条标 skipped_limit（不是 failed）
    r, rep, rows, lg = run_detail("nofield", ratio="1.0", max_items="5")
    st = rep.get("stats", {})
    n_miss = sum(1 for x in rows if x.get("detail_fetch") == "field_missing")
    n_lim = sum(1 for x in rows if x.get("detail_fetch") == "skipped_limit")
    ok = (r.returncode == 3 and rep.get("status") == "partial"
          and st.get("detail_failed") == 5
          and n_miss == 5 and n_lim == 15
          and all(x.get("detail_missing") == "pub"
                  for x in rows if x.get("detail_fetch") == "field_missing"))
    record("21. 通用详情：必填字段缺失标记 field_missing", ok,
           "status=%s failed=%s missing=%d limit=%d"
           % (rep.get("status"), st.get("detail_failed"), n_miss, n_lim))

    # ---------- 22 详情超时 → 重试耗尽记失败，不卡死 ----------
    begin_case("c22")
    r, rep, rows, lg = run_detail("slow", ratio="1.0", max_items="2")
    st = rep.get("stats", {})
    n_err = sum(1 for x in rows if x.get("detail_fetch") == "error")
    ok = (st.get("detail_failed") == 2 and n_err == 2
          and all("重试耗尽" in (x.get("detail_error") or "")
                  for x in rows if x.get("detail_fetch") == "error")
          and sum(1 for x in rows if x.get("detail_fetch") == "skipped_limit") == 18)
    record("22. 通用详情：超时重试耗尽后记失败", ok,
           "failed=%s error=%d" % (st.get("detail_failed"), n_err))

    # ---------- 23 详情 URL 被 robots 禁止 → 跳过，且确实没发请求 ----------
    begin_case("c23")
    r, rep, rows, lg = run_detail("ok", ratio="1.0", max_items="5",
                                  robots="1", mock_robots="deny-detail")
    st = rep.get("stats", {})
    n_deny = sum(1 for x in rows if x.get("detail_fetch") == "robots_denied")
    # 证据：url_allowed 每次拒绝都会写一行"robots 禁止抓取该页"；
    # 同时全程不能出现"详情 ok"（出现了就说明真的请求过详情页）
    blocked_logs = lg.count("robots 禁止抓取该页")
    fetched_any = lg.count("详情 ok") + lg.count("详情 HTTP")
    ok = (st.get("detail_robots_blocked") == 5 and st.get("detail_failed") == 5
          and n_deny == 5 and blocked_logs == 5 and fetched_any == 0)
    record("23. 通用详情：robots 禁止详情 URL 则跳过", ok,
           "blocked=%s denied=%d robots日志=%d 详情请求=%d"
           % (st.get("detail_robots_blocked"), n_deny, blocked_logs, fetched_any))

    # =====================================================================
    # 阶段1 补强（codex 第 2 条）：详情失败后下次必须能补上，而不是被永久跳过
    # =====================================================================

    # ---------- 24 详情首次失败 → 下次运行自动补抓（不重抓列表页） ----------
    begin_case("c24")
    # mock 的 flaky 模式：每个详情 URL 第一次 500，第二次起 200。
    # 注意：必须【同一个 mock 进程】跑两轮，否则计数器重置，第二轮又会 500。
    # 这里把熔断关掉（ratio="0"），单独验证"补抓语义"，
    # 否则 3 条全失败会先触发 3/3=100% 熔断，reason 变成 detail_fail_ratio_exceeded，
    # 测的就不是补抓了。
    r1, rep1, rows1, r2, rep2, rows2, lg2 = run_detail_twice(
        "flaky", ratio="0", max_items="3")
    st1 = rep1.get("stats", {})
    st2 = rep2.get("stats", {})
    pending1 = st1.get("detail_pending_after_run")
    n_fail1 = sum(1 for x in rows1 if x.get("detail_fetch") == "error")
    n_ok2 = sum(1 for x in rows2 if x.get("detail_fetch") == "ok")
    checks = {
        "pending1==3": pending1 == 3,
        "n_fail1==3": n_fail1 == 3,
        "r1.partial": rep1.get("status") == "partial",
        "r1.reason": rep1.get("reason") == "detail_pending_remains",
        "r2.rc==0": r2.returncode == 0,
        "r2.success": rep2.get("status") == "success",
        "r2.repaired": rep2.get("reason") == "details_repaired",
        "repaired_ok==3": st2.get("detail_repaired_ok") == 3,
        "pending2==0": st2.get("detail_pending_after_run", -1) == 0,
        "n_ok2==3": n_ok2 == 3,
        "no_recrawl": "跳过(已完成)" in lg2,
    }
    ok = all(checks.values())
    bad = [k for k, v in checks.items() if not v]
    record("24. 详情失败 → 下次自动补抓成功", ok,
           "第1轮 pending=%s | 第2轮 repaired=%s ok=%d | %s"
           % (pending1, st2.get("detail_repaired_ok"), n_ok2,
              "全部符合" if ok else "不符合: " + ",".join(bad)))

    # ---------- 25 详情永久失败 → 补抓后仍 pending，且绝不重抓列表页 ----------
    begin_case("c25")
    r1, rep1, rows1, r2, rep2, rows2, lg2 = run_detail_twice(
        "fail", ratio="0", max_items="3")
    st2 = rep2.get("stats", {})
    ok = (rep1.get("reason") == "detail_pending_remains"
          and r2.returncode == 3 and rep2.get("status") == "partial"
          and rep2.get("reason") == "detail_pending_remains"
          and st2.get("detail_repaired_fail") == 3
          and st2.get("detail_pending_after_run") == 3
          and len(rows2) == len(rows1)              # 没有重复写入
          and "第 1/1 页" not in lg2                # 第二轮没再去请求列表页
          and lg2.count("补抓") > 0)
    record("25. 详情永久失败 → 仍是 pending 且不重抓列表页", ok,
           "第2轮 repaired_fail=%s pending=%s 行数=%d/%d"
           % (st2.get("detail_repaired_fail"), st2.get("detail_pending_after_run"),
              len(rows2), len(rows1)))

    # ---------- 26 详情本来就齐 → 补抓 0 条，不产生多余请求 ----------
    begin_case("c26")
    r1, rep1, rows1, r2, rep2, rows2, lg2 = run_detail_twice("ok")
    st2 = rep2.get("stats", {})
    ok = (st2.get("detail_repair_planned") == 0
          and st2.get("detail_pending_after_run") == 0
          and r2.returncode == 0
          and "详情补抓：0 条待补" in lg2
          and len(rows2) == 20)
    record("26. 详情已齐 → 补抓 0 条（不做多余请求）", ok,
           "第2轮 planned=%s pending=%s status=%s"
           % (st2.get("detail_repair_planned"), st2.get("detail_pending_after_run"),
              rep2.get("status")))

    # ---------- 27 熔断与补抓的交互：3 条页 + ratio=0.5 → 第 2 条失败就熔断 ----------
    begin_case("c27")
    # 这个用例专门解释"18 和 24/25 的断言为什么不一样"：
    #   18：20 条 + 0.5，分母 20 → 失败第 10 条触发
    #   27：3 条 + 0.5，分母 3  → 失败第 2 条触发（2/3=66.7% >= 50%）
    #   24/25：ratio=0（关掉熔断），才能单独观察"补抓"语义
    # 三者不是标准不一致，而是分母跟着"本轮计划条数"走，这是设计而不是巧合。
    r, rep, rows, lg = run_detail("fail", ratio="0.5", max_items="3")
    st = rep.get("stats", {})
    ok = (r.returncode == 3
          and rep.get("status") == "partial"
          and rep.get("reason") == "detail_fail_ratio_exceeded"
          and st.get("detail_failed") == 2
          and st.get("detail_skipped") == 1
          and st.get("detail_skipped_limit") == 17
          and st.get("detail_pending_after_run") == 3)
    record("27. 3 条页 + ratio0.5 → 第 2 条失败即熔断", ok,
           "failed=%s skipped_aborted=%s skipped_limit=%s pending=%s reason=%s"
           % (st.get("detail_failed"), st.get("detail_skipped"),
              st.get("detail_skipped_limit"), st.get("detail_pending_after_run"),
              rep.get("reason")))

    # =====================================================================
    # 阶段2：下一页翻页（sites/mocknext.py）
    #
    # 每个用例都断言"实际抓了几页 / stop_reason / 断点内容"，
    # 不用"文件存在"当通过——阶段1 就是在这上面栽过一次。
    # =====================================================================

    def run_next(start="/n/page1.html", max_pages="200"):
        env = {"MOCKNEXT_START": start, "MOCKNEXT_MAX_PAGES": str(max_pages)}
        r = crawl(["--site", "mocknext"], env_extra=env)
        return r, latest_report("mocknext") or {}, read_rows(RAW_N), read_log_file(CRAWLER_LOG_N)

    def read_state_n():
        if not os.path.exists(STATE_N):
            return {}
        with open(STATE_N, encoding="utf-8") as f:
            return json.load(f)

    # ---------- 28 next 分页：正常 3 页，断点在 urls_done 而不是 pages_done ----------
    begin_case("c28")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/page1.html")
        st = rep.get("stats", {})
        state = read_state_n()
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("reason") == "ok"
              and rep.get("stop_reason") == "no_next"
              and rep.get("paginate") == "next"
              and st.get("pages_ok") == 3 and st.get("pages_failed", 0) == 0
              and len(rows) == 9
              and len(set(x["detail_url"] for x in rows)) == 9
              and len(rep.get("per_page") or {}) == 3
              and len(state.get("urls_done") or []) == 3
              and (state.get("pages_done") or []) == []
              and state.get("next_url") is None
              and state.get("paginate_mode") == "next")
        record("28. next 分页：3 页 9 条，断点只写 urls_done", ok,
               "status=%s stop=%s pages_ok=%s rows=%d urls_done=%s pages_done=%s"
               % (rep.get("status"), rep.get("stop_reason"), st.get("pages_ok"),
                  len(rows), len(state.get("urls_done") or []),
                  state.get("pages_done")))
    finally:
        stop_mock(p)

    # ---------- 29 翻页循环：loop1 ⇄ loop2 ----------
    begin_case("c29")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/loop1.html")
        st = rep.get("stats", {})
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("stop_reason") == "pagination_loop"
              and st.get("pages_ok") == 2 and len(rows) == 6
              and len(read_state_n().get("urls_done") or []) == 2)
        record("29. 翻页循环 → 抓 2 页后停", ok,
               "status=%s stop=%s pages_ok=%s rows=%d"
               % (rep.get("status"), rep.get("stop_reason"), st.get("pages_ok"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 30 自指：下一页就是自己 ----------
    begin_case("c30")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/self1.html")
        st = rep.get("stats", {})
        ok = (rep.get("stop_reason") == "pagination_loop"
              and st.get("pages_ok") == 1 and len(rows) == 3)
        record("30. 下一页指向自己 → 抓 1 页即停", ok,
               "stop=%s pages_ok=%s rows=%d"
               % (rep.get("stop_reason"), st.get("pages_ok"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 31 参数顺序不同：?a=1&b=2 与 ?b=2&a=1 归一化后是同一页 ----------
    begin_case("c31")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/dup1.html?a=1&b=2")
        st = rep.get("stats", {})
        ok = (rep.get("stop_reason") == "pagination_loop"
              and st.get("pages_ok") == 1 and len(rows) == 3)
        record("31. 参数顺序不同 → 归一化识别为同一页", ok,
               "stop=%s pages_ok=%s rows=%d"
               % (rep.get("stop_reason"), st.get("pages_ok"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 32 max_pages 上限：无限链只抓到第 3 页 ----------
    begin_case("c32")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/inf/p1.html", max_pages="3")
        st = rep.get("stats", {})
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("stop_reason") == "max_pages_reached"
              and st.get("pages_ok") == 3 and len(rows) == 9)
        record("32. max_pages=3 → 抓到 3 页停", ok,
               "stop=%s pages_ok=%s rows=%d"
               % (rep.get("stop_reason"), st.get("pages_ok"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 33 断点续跑：从 next_url 接着抓，不重抓已完成的页 ----------
    begin_case("c33")
    p = start_mock("none")
    try:
        r1, rep1, rows1, lg1 = run_next("/n/inf/p1.html", max_pages="2")
        st1 = rep1.get("stats", {})
        next_after_1 = read_state_n().get("next_url")

        r2, rep2, rows2, lg2 = run_next("/n/inf/p1.html", max_pages="3")
        st2 = rep2.get("stats", {})
        state2 = read_state_n()

        # 第二轮应从 p3 开始（第一轮抓了 p1、p2）
        resumed_ok = "/n/inf/p3.html" in (lg2.split("第 1 页")[1] if "第 1 页" in lg2 else "")
        ok = (st1.get("pages_ok") == 2 and len(rows1) == 6
              and next_after_1 and next_after_1.endswith("/n/inf/p3.html")
              and r2.returncode == 3
              and rep2.get("stop_reason") == "max_pages_reached"
              and st2.get("pages_ok") == 3
              and len(rows2) == 15                       # 2 页 + 3 页 = 5 页 × 3 条
              and len(set(x["detail_url"] for x in rows2)) == 15
              and len(state2.get("urls_done") or []) == 5
              and st2.get("pages_skipped", 0) == 0       # next 模式不靠"跳过"续跑
              and resumed_ok)
        record("33. 断点续跑：从 p3 接着抓，累计 5 页 15 条", ok,
               "第1轮 ok=%s next=%s | 第2轮 ok=%s 累计行=%d urls_done=%s 从p3开始=%s"
               % (st1.get("pages_ok"), (next_after_1 or "")[-12:],
                  st2.get("pages_ok"), len(rows2),
                  len(state2.get("urls_done") or []), resumed_ok))
    finally:
        stop_mock(p)

    # ---------- 34 第一页就 500：读不到下一页，必须明确报"断在第 1 页" ----------
    begin_case("c34")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/broken1.html")
        st = rep.get("stats", {})
        ok = (r.returncode == 4 and rep.get("status") == "failed"
              and rep.get("stop_reason") == "pagination_broken_at_page_1"
              and st.get("pages_ok") == 0 and st.get("pages_failed") == 1
              and len(rows) == 0)
        record("34. 首页 500 → 报 pagination_broken_at_page_1", ok,
               "status=%s stop=%s ok_pages=%s failed=%s rows=%d"
               % (rep.get("status"), rep.get("stop_reason"),
                  st.get("pages_ok"), st.get("pages_failed"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 35 parse_next 抛异常 → 不能被当成"没有下一页" ----------
    # 这是 codex 指出的静默截断：解析器坏了却报 success = 骗人。
    begin_case("c35")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/boom1.html")
        st = rep.get("stats", {})
        anom = rep.get("anomalies") or []
        has_anom = any("parse_next 异常" in (a.get("reason") or "") for a in anom)
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("stop_reason") == "pagination_parse_error"
              and st.get("pages_ok") == 1 and len(rows) == 3
              and has_anom)
        record("35. parse_next 异常 → pagination_parse_error（不报 success）", ok,
               "status=%s stop=%s pages_ok=%s 异常入报告=%s"
               % (rep.get("status"), rep.get("stop_reason"),
                  st.get("pages_ok"), has_anom))
    finally:
        stop_mock(p)

    # ---------- 36 空页但有下一页 → 必须继续翻，不能直接收工 ----------
    begin_case("c36")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/empty1.html")
        st = rep.get("stats", {})
        state = read_state_n()
        ok = (rep.get("status") == "partial"
              and rep.get("reason") == "empty_page_seen"
              and rep.get("stop_reason") == "no_next"
              and st.get("pages_total") == 3        # 实际访问了 3 页（含空页）
              and st.get("pages_ok") == 2           # 其中 2 页有数据
              and st.get("pages_empty") == 1        # 空页单独计数，不混进 pages_ok
              and len(rows) == 6                    # 0 + 3 + 3
              and len(state.get("urls_done") or []) == 3)
        record("36. 空页但有下一页 → 继续翻完 3 页（空页不算 success）", ok,
               "status=%s reason=%s stop=%s total=%s ok=%s empty=%s rows=%d"
               % (rep.get("status"), rep.get("reason"), rep.get("stop_reason"),
                  st.get("pages_total"), st.get("pages_ok"),
                  st.get("pages_empty"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 37 空页且没有下一页 → 按结束处理，但状态记异常 ----------
    begin_case("c37")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_next("/n/emptyend.html")
        st = rep.get("stats", {})
        ok = (r.returncode == 4 and rep.get("status") == "failed"
              and rep.get("stop_reason") == "pagination_empty_at_page_1"
              and st.get("pages_ok") == 0 and st.get("pages_empty") == 1
              and len(rows) == 0)
        record("37. 空页且无下一页 → pagination_empty_at_page_1", ok,
               "status=%s stop=%s empty=%s rows=%d"
               % (rep.get("status"), rep.get("stop_reason"),
                  st.get("pages_empty"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 38 老数据没有 detail_fetch：启用详情后必须被补抓 ----------
    # 场景：某站原来没开详情，记录里没有 detail_fetch；后来开了详情，
    # 列表页又已 pages_done。如果 detail_retryable(None) 返回 False，
    # 这些记录永远不会被补，而且没人知道。
    begin_case("c38")
    p = start_mock("none")
    try:
        d = CASE["dir"]
        old_rows = [
            {"title": "old-1", "detail_url": "http://127.0.0.1:%d/detail/ok-1" % PORT},
            {"title": "old-2", "detail_url": "http://127.0.0.1:%d/detail/ok-2" % PORT},
        ]
        with open(RAW_D, "w", encoding="utf-8", newline="\n") as f:
            for r0 in old_rows:
                f.write(json.dumps(r0, ensure_ascii=False) + "\n")
        with open(STATE_D, "w", encoding="utf-8") as f:
            json.dump({
                "pages_done": [1], "urls_done": [], "next_url": None,
                "paginate_mode": "number",
                "seen_keys": [x["detail_url"] for x in old_rows],
                "out_file": RAW_D,
            }, f, ensure_ascii=False)

        r = crawl(["--site", "mockdetail", "--detail-mode", "generic"],
                  env_extra=detail_env("ok"))
        rep = latest_report("mockdetail") or {}
        st = rep.get("stats", {})
        rows = read_rows(RAW_D)
        ok = (st.get("detail_repair_planned") == 2
              and st.get("detail_repaired_ok") == 2
              and st.get("detail_pending_after_run") == 0
              and rep.get("reason") == "details_repaired"
              and len(rows) == 2
              and all(x.get("detail_fetch") == "ok" for x in rows)
              and all(x.get("detail_attempts") == 1 for x in rows))
        record("38. 老数据缺 detail_fetch → 开详情后被补抓", ok,
               "planned=%s repaired=%s pending=%s fetch=%s attempts=%s"
               % (st.get("detail_repair_planned"), st.get("detail_repaired_ok"),
                  st.get("detail_pending_after_run"),
                  sorted({x.get("detail_fetch") for x in rows}),
                  sorted({x.get("detail_attempts") for x in rows})))
    finally:
        stop_mock(p)

    # ---------- 39 parse_next 异常后连跑两轮：第二轮必须重试，不能假成功 ----------
    # codex 指出的点：异常时如果把这页写进 urls_done、又把 next_url 清空，
    # 下次运行会从 first_url 起步 → 发现它已在 urls_done → 直接 noop，
    # 等于把"中断"永久固化成"抓完了"。
    begin_case("c39")
    p = start_mock("none")
    try:
        r1, rep1, rows1, lg1 = run_next("/n/boom1.html")
        st1 = rep1.get("stats", {})
        s1 = read_state_n()

        lg_before = read_log_file(CRAWLER_LOG_N)
        r2, rep2, rows2, lg2full = run_next("/n/boom1.html")
        lg2 = lg2full[len(lg_before):]
        st2 = rep2.get("stats", {})
        s2 = read_state_n()

        ok = (r1.returncode == 3 and rep1.get("stop_reason") == "pagination_parse_error"
              and st1.get("pages_ok") == 1 and len(rows1) == 3
              and (s1.get("urls_done") or []) == []
              and (s1.get("next_url") or "").endswith("/n/boom1.html")
              # 第二轮：必须重新抓这一页，并且仍然报同样的异常
              and r2.returncode == 3
              and rep2.get("status") == "partial"
              and rep2.get("stop_reason") == "pagination_parse_error"
              and st2.get("pages_ok") == 1          # 真的又抓了一次
              and st2.get("records_dup") == 3       # 数据没重复写入
              and len(rows2) == 3
              and (s2.get("urls_done") or []) == []
              and (s2.get("next_url") or "").endswith("/n/boom1.html")
              and "第 1 页" in lg2 and "boom1" in lg2)
        record("39. parse_next 异常后第二轮仍重试（不假成功）", ok,
               "第1轮 %s/%s | 第2轮 %s/%s pages_ok=%s dup=%s urls_done=%s"
               % (rep1.get("status"), rep1.get("stop_reason"),
                  rep2.get("status"), rep2.get("stop_reason"),
                  st2.get("pages_ok"), st2.get("records_dup"),
                  len(s2.get("urls_done") or [])))
    finally:
        stop_mock(p)

    # ---------- 40 空页无下一页连跑两轮：第二次不能直接 noop/no_next ----------
    begin_case("c40")
    p = start_mock("none")
    try:
        r1, rep1, rows1, lg1 = run_next("/n/emptyend.html")
        st1 = rep1.get("stats", {})
        s1 = read_state_n()

        lg_before = read_log_file(CRAWLER_LOG_N)
        r2, rep2, rows2, lg2full = run_next("/n/emptyend.html")
        lg2 = lg2full[len(lg_before):]
        st2 = rep2.get("stats", {})
        s2 = read_state_n()

        ok = (r1.returncode == 4 and rep1.get("status") == "failed"
              and rep1.get("stop_reason") == "pagination_empty_at_page_1"
              and st1.get("pages_empty") == 1
              and (s1.get("urls_done") or []) == []
              and (s1.get("next_url") or "").endswith("/n/emptyend.html")
              # 第二轮：不能是 noop / all_pages_already_done / no_next
              and r2.returncode == 4
              and rep2.get("status") == "failed"
              and rep2.get("reason") == "pagination_empty_at_page_1"
              and rep2.get("stop_reason") == "pagination_empty_at_page_1"
              and st2.get("pages_empty") == 1
              and st2.get("pages_total") == 1       # 真的又访问了一次
              and "第 1 页" in lg2)
        record("40. 空页无下一页 → 第二轮仍重试（不假结束）", ok,
               "第1轮 %s/%s | 第2轮 %s/%s total=%s"
               % (rep1.get("status"), rep1.get("stop_reason"),
                  rep2.get("status"), rep2.get("stop_reason"),
                  st2.get("pages_total")))
    finally:
        stop_mock(p)

    # =====================================================================
    # 阶段3：JSON / API 接口（sites/mockjson.py）
    # 站点模块只有 CONFIG，解析全由引擎按 CONFIG["json"] 完成。
    # =====================================================================

    def run_json(case, pages="3", extra=None):
        env = {"MOCKJSON_CASE": case, "MOCKJSON_PAGES": str(pages)}
        if extra:
            env.update(extra)
        r = crawl(["--site", "mockjson"], env_extra=env)
        return r, latest_report("mockjson") or {}, read_rows(RAW_J), read_log_file(CRAWLER_LOG_J)

    # ---------- 41 JSON GET + 数字分页：3 页 9 条，字段映射正确 ----------
    begin_case("c41")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("items", pages="3")
        st = rep.get("stats", {})
        first = rows[0] if rows else {}
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("paginate") == "number"
              and st.get("pages_ok") == 3 and len(rows) == 9
              and first.get("title") == "p1-1"
              and (first.get("detail_url") or "").startswith("http://127.0.0.1:%d/detail/" % PORT)
              and first.get("publish_date") == "2026-11-02"
              and len(set(x.get("detail_url") for x in rows)) == 9)
        record("41. JSON GET + 数字分页 → 3 页 9 条，字段映射正确", ok,
               "status=%s pages_ok=%s rows=%d title=%r url=%r"
               % (rep.get("status"), st.get("pages_ok"), len(rows),
                  first.get("title"), (first.get("detail_url") or "")[-18:]))
    finally:
        stop_mock(p)

    # ---------- 42 JSON POST（表单）：请求真的发出去了，响应能解析 ----------
    begin_case("c42")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("post", pages="1")
        st = rep.get("stats", {})
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and st.get("pages_ok") == 1 and len(rows) == 3
              and rows[0].get("title") == "post1-1")
        record("42. JSON POST（form）→ 3 条", ok,
               "status=%s rows=%d first=%r"
               % (rep.get("status"), len(rows), rows[0].get("title") if rows else None))
    finally:
        stop_mock(p)

    # ---------- 43 业务错误码（HTTP 200 但 code≠0） ----------
    begin_case("c43")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("bizerror", pages="2")
        st = rep.get("stats", {})
        anom = " ".join(a.get("reason") or "" for a in (rep.get("anomalies") or []))
        ok = (r.returncode == 4 and rep.get("status") == "failed"
              and rep.get("stop_reason") == "api_business_error_at_page_1"
              and st.get("pages_ok") == 0 and len(rows) == 0
              and "接口业务错误" in anom)
        record("43. 业务错误码 → 停止并报 api_business_error", ok,
               "status=%s stop=%s rows=%d 异常=%s"
               % (rep.get("status"), rep.get("stop_reason"), len(rows),
                  "有" if "接口业务错误" in anom else "无"))
    finally:
        stop_mock(p)

    # ---------- 44 空数组：不是错误，但也不能算 success ----------
    begin_case("c44")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("empty", pages="1")
        st = rep.get("stats", {})
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("reason") == "empty_page_seen"
              and st.get("pages_empty") == 1 and len(rows) == 0)
        record("44. 空数组 → 空页语义（partial）", ok,
               "status=%s reason=%s empty=%s rows=%d"
               % (rep.get("status"), rep.get("reason"), st.get("pages_empty"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 45 字段缺失：不崩、留空、去重键为空要显式报 ----------
    begin_case("c45")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("missing", pages="1")
        st = rep.get("stats", {})
        anom = " ".join(a.get("reason") or "" for a in (rep.get("anomalies") or []))
        ok = (rep.get("status") == "partial"
              and rep.get("reason") == "dedup_key_empty"
              and st.get("dedup_key_empty") == 2
              and len(rows) == 2                       # 两条都写进去了，没被误判成同一条
              and all(x.get("detail_url") == "" for x in rows)
              and "去重键为空" in anom)
        record("45. 字段缺失 → 留空 + 去重键为空显式告警", ok,
               "status=%s reason=%s emptykey=%s rows=%d"
               % (rep.get("status"), rep.get("reason"),
                  st.get("dedup_key_empty"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 46 JSON 里的 next 字段分页 ----------
    begin_case("c46")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("next", pages="3")
        st = rep.get("stats", {})
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("paginate") == "next"
              and rep.get("stop_reason") == "no_next"
              and st.get("pages_ok") == 3 and len(rows) == 9)
        record("46. JSON next 字段分页 → 3 页 9 条", ok,
               "status=%s stop=%s pages_ok=%s rows=%d"
               % (rep.get("status"), rep.get("stop_reason"), st.get("pages_ok"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 47 cursor 游标分页（引擎把它拼成下一页 URL） ----------
    begin_case("c47")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("cursor", pages="3")
        st = rep.get("stats", {})
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("stop_reason") == "no_next"
              and st.get("pages_ok") == 3 and len(rows) == 9
              and "cursor=2" in lg and "cursor=3" in lg)
        record("47. cursor 分页 → 3 页 9 条", ok,
               "status=%s stop=%s pages_ok=%s rows=%d cursor 出现在日志=%s"
               % (rep.get("status"), rep.get("stop_reason"), st.get("pages_ok"),
                  len(rows), ("cursor=2" in lg)))
    finally:
        stop_mock(p)

    # ---------- 48 HTTP 200 但不是 JSON（被登录页顶替） ----------
    begin_case("c48")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("notjson", pages="1")
        st = rep.get("stats", {})
        anom = " ".join(a.get("reason") or "" for a in (rep.get("anomalies") or []))
        ok = (r.returncode == 4 and rep.get("status") == "failed"
              and st.get("pages_ok") == 0 and len(rows) == 0
              and "响应无法解析" in anom)
        record("48. 200 但不是 JSON → 记为失败（不当成空数据）", ok,
               "status=%s rows=%d 异常=%s"
               % (rep.get("status"), len(rows), "有" if "响应无法解析" in anom else "无"))
    finally:
        stop_mock(p)

    # ---------- 49 POST 分页：body 里的 {page} 必须真的跟着变 ----------
    # 如果只替换 params 不替换 body，第二页会原封不动地再要一次第一页
    # （数据看起来"有 6 条"，其实两页一模一样）。
    begin_case("c49")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("post", pages="2")
        st = rep.get("stats", {})
        titles = [x.get("title") for x in rows]
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and st.get("pages_ok") == 2
              and len(rows) == 6
              and "post1-1" in titles and "post2-1" in titles
              and len(set(x.get("detail_url") for x in rows)) == 6)
        record("49. POST 分页：body 里的 {page} 第二页真的变了", ok,
               "pages_ok=%s rows=%d 含 post1=%s 含 post2=%s"
               % (st.get("pages_ok"), len(rows), "post1-1" in titles, "post2-1" in titles))
    finally:
        stop_mock(p)

    # ---------- 50 数组里混进非对象条目：不能静默丢 ----------
    begin_case("c50")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("mixed", pages="1")
        st = rep.get("stats", {})
        anom = " ".join(a.get("reason") or "" for a in (rep.get("anomalies") or []))
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("reason") == "invalid_items_skipped"
              and st.get("invalid_items") == 3      # "字符串" / null / 数字
              and len(rows) == 2                    # 两个好条目照常落盘
              and "不是对象" in anom)
        record("50. 数组混入非对象条目 → 计数并判 partial", ok,
               "status=%s reason=%s invalid=%s rows=%d"
               % (rep.get("status"), rep.get("reason"),
                  st.get("invalid_items"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 51 JSON + next 但没配 next_path/cursor_path → 必须明确失败 ----------
    begin_case("c51")
    p = start_mock("none")
    try:
        env = {"MOCKJSON_CASE": "items", "MOCKJSON_PAGES": "3",
               "MOCKJSON_PAGINATE": "next"}
        r = crawl(["--site", "mockjson"], env_extra=env)
        rep = latest_report("mockjson") or {}
        rows = read_rows(RAW_J)
        ok = (r.returncode == 1 and rep.get("status") == "failed"
              and rep.get("reason") == "json_pagination_not_configured"
              and len(rows) == 0)
        record("51. json+next 没配下一页来源 → 配置错误（不假成功）", ok,
               "status=%s reason=%s rows=%d"
               % (rep.get("status"), rep.get("reason"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 52 single_page=True 时同样配置属正常单页 ----------
    begin_case("c52")
    p = start_mock("none")
    try:
        env = {"MOCKJSON_CASE": "items", "MOCKJSON_PAGES": "1",
               "MOCKJSON_PAGINATE": "next", "MOCKJSON_SINGLE": "1"}
        r = crawl(["--site", "mockjson"], env_extra=env)
        rep = latest_report("mockjson") or {}
        st = rep.get("stats", {})
        rows = read_rows(RAW_J)
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("stop_reason") == "no_next"
              and st.get("pages_ok") == 1 and len(rows) == 3)
        record("52. single_page=true → 单页正常结束", ok,
               "status=%s stop=%s pages_ok=%s rows=%d"
               % (rep.get("status"), rep.get("stop_reason"),
                  st.get("pages_ok"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 53 cursor=0 是合法游标（靠 cursor_end_value 判定结束） ----------
    begin_case("c53")
    p = start_mock("none")
    try:
        env = {"MOCKJSON_CASE": "cursor0", "MOCKJSON_PAGES": "3",
               "MOCKJSON_CURSOR_END": "-1"}
        r = crawl(["--site", "mockjson"], env_extra=env)
        rep = latest_report("mockjson") or {}
        st = rep.get("stats", {})
        rows = read_rows(RAW_J)
        titles = [x.get("title") for x in rows]
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("stop_reason") == "no_next"
              and st.get("pages_ok") == 3 and len(rows) == 9
              and "z0-1" in titles and "z2-1" in titles)   # cursor=0 没有被当成结束
        record("53. cursor=0 合法（cursor_end_value=-1）", ok,
               "status=%s stop=%s pages_ok=%s rows=%d 含 z0=%s 含 z2=%s"
               % (rep.get("status"), rep.get("stop_reason"), st.get("pages_ok"),
                  len(rows), "z0-1" in titles, "z2-1" in titles))
    finally:
        stop_mock(p)

    # ---------- 54 total=全局 + 抓完整个结果集 → 才判定总数不符 ----------
    begin_case("c54")
    p = start_mock("none")
    try:
        # /api/globalbad：next 分页，3 页共 9 条，但自报 total=99
        r, rep, rows, lg = run_json("globalbad", pages="3")
        st = rep.get("stats", {})
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("reason") == "json_total_mismatch"
              and st.get("json_total_reported") == 99
              and st.get("json_total_complete_set") is True
              and st.get("json_total_scope") == "global"
              and len(rows) == 9 and rep.get("stop_reason") == "no_next")
        record("54. total 全局 + 抓完 → 判定总数不符", ok,
               "status=%s reason=%s reported=%s 抓完=%s rows=%d"
               % (rep.get("status"), rep.get("reason"), st.get("json_total_reported"),
                  st.get("json_total_complete_set"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 55 total=全局但只抓 1 页 → 不能误报 ----------
    begin_case("c55")
    p = start_mock("none")
    try:
        # /api/global 自报 total=9，这次只抓第 1 页（3 条）
        r, rep, rows, lg = run_json("global", pages="1")
        st = rep.get("stats", {})
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("reason") == "ok"
              and st.get("json_total_reported") == 9
              and st.get("json_total_complete_set") is False
              and len(rows) == 3)
        record("55. total 全局但没抓完 → 不误报 partial", ok,
               "status=%s reason=%s reported=%s 抓完=%s rows=%d"
               % (rep.get("status"), rep.get("reason"), st.get("json_total_reported"),
                  st.get("json_total_complete_set"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 56 total_scope=page → 只记录不比较 ----------
    begin_case("c56")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("globalbad", pages="3",
                                    extra={"MOCKJSON_TOTAL_SCOPE": "page"})
        st = rep.get("stats", {})
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and st.get("json_total_scope") == "page"
              and st.get("json_total_reported") == 99     # 照常记录
              and len(rows) == 9)                          # 但没拿它判定
        record("56. total_scope=page → 只记录不参与比较", ok,
               "status=%s scope=%s reported=%s rows=%d"
               % (rep.get("status"), st.get("json_total_scope"),
                  st.get("json_total_reported"), len(rows)))
    finally:
        stop_mock(p)

    # ---------- 57 response 配了非法值 → 直接失败，不静默退回 html ----------
    begin_case("c57")
    p = start_mock("none")
    try:
        r, rep, rows, lg = run_json("items", pages="1",
                                    extra={"MOCKJSON_RESPONSE": "xml"})
        ok = (r.returncode == 1 and rep.get("status") == "failed"
              and rep.get("reason") == "bad_response_mode"
              and len(rows) == 0)
        record("57. response 非法值 → 直接失败（不退回 html）", ok,
               "status=%s reason=%s rows=%d"
               % (rep.get("status"), rep.get("reason"), len(rows)))
    finally:
        stop_mock(p)

    # =====================================================================
    # 阶段4：附件下载（sites/mockattach.py）
    # 站点只给 attachments 字段；下载/robots/类型/大小/配额/SHA256 全由引擎负责。
    # =====================================================================

    def run_attach(case, extra=None, mock_robots="none"):
        env = {"MOCKATTACH_CASE": case}
        if extra:
            env.update(extra)
        p = start_mock(mock_robots)
        try:
            r = crawl(["--site", "mockattach"], env_extra=env)
        finally:
            stop_mock(p)
        return r, latest_report("mockattach") or {}, read_rows(RAW_A), read_log_file(CRAWLER_LOG_A)

    def run_attach_hits(case, extra=None, mock_robots="none", hits_for=()):
        env = {"MOCKATTACH_CASE": case}
        if extra:
            env.update(extra)
        p = start_mock(mock_robots)
        try:
            r = crawl(["--site", "mockattach"], env_extra=env)
            hits = {}
            for path in hits_for:
                try:
                    q = http_probe_json(p, "/api/hits?p=%s" % path)
                    hits[path] = int((q.get("data") or {}).get("hits") or 0)
                except Exception:
                    hits[path] = -1
        finally:
            stop_mock(p)
        return (r, latest_report("mockattach") or {}, read_rows(RAW_A),
                read_log_file(CRAWLER_LOG_A), hits)

    def atts(rows, idx=0):
        rows = [x for x in rows if x.get("attachments")]
        if not rows:
            return []
        return rows[idx].get("attachments") or []

    # ---------- 58 正常下载两个附件：落盘 + 字节数 + SHA256 ----------
    begin_case("c58")
    r, rep, rows, lg = run_attach("ok")
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (r.returncode == 0 and rep.get("status") == "success"
          and st.get("attach_ok") == 2 and len(a) == 2
          and all(x["status"] == "ok" for x in a)
          and all(x["bytes"] > 0 and len(x["sha256"]) == 64 for x in a)
          and all(os.path.exists(x["path"]) for x in a)
          and all(os.path.getsize(x["path"]) == x["bytes"] for x in a))
    record("58. 附件正常下载（落盘+字节+SHA256）", ok,
           "ok=%s 文件=%s 字节=%s"
           % (st.get("attach_ok"), [x["name"] for x in a], [x["bytes"] for x in a]))

    # ---------- 59 单条记录附件数超上限 → 多的只记链接 ----------
    begin_case("c59")
    r, rep, rows, lg = run_attach("many", extra={"MOCKATTACH_MAXFILES": "5"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (r.returncode == 3 and rep.get("status") == "partial"
          and rep.get("reason") == "attachment_partial"
          and st.get("attach_ok") == 5 and st.get("attach_too_many") == 2
          and len(a) == 7
          and sum(1 for x in a if x["status"] == "too_many") == 2
          and all(x["bytes"] == 0 for x in a if x["status"] == "too_many"))
    record("59. 附件数超上限 → 5 下 2 只记链接", ok,
           "ok=%s too_many=%s 记录内附件=%d"
           % (st.get("attach_ok"), st.get("attach_too_many"), len(a)))

    # ---------- 60 单文件超上限：靠 Content-Length 就拒绝，不写半截文件 ----------
    begin_case("c60")
    r, rep, rows, lg = run_attach("big", extra={"MOCKATTACH_MAXFILE": "1024"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial" and rep.get("reason") == "attachment_partial"
          and st.get("attach_too_large") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "too_large"
          and a[0]["path"] == "" and a[0]["bytes"] == 2048)
    record("60. 单文件 2048B > 上限 1024B → 只记链接", ok,
           "ok=%s too_large=%s 记录字节=%s 落盘=%r"
           % (st.get("attach_ok"), st.get("attach_too_large"),
              a[0]["bytes"] if a else None, a[0]["path"] if a else None))

    # ---------- 61 任务累计上限：下到第 2 个就触顶 ----------
    begin_case("c61")
    r, rep, rows, lg = run_attach("quota",
                                  extra={"MOCKATTACH_MAXFILE": "4096",
                                         "MOCKATTACH_MAXTOTAL": "2500"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial" and rep.get("reason") == "attachment_partial"
          and st.get("attach_ok") == 1 and st.get("attach_quota") == 2
          and sum(1 for x in a if x["status"] == "quota_exceeded") == 2)
    record("61. 累计上限 2500B → 下 1 个后触顶", ok,
           "ok=%s quota=%s 状态=%s"
           % (st.get("attach_ok"), st.get("attach_quota"),
              [x["status"] for x in a]))

    # ---------- 62 robots 禁附件目录 → 只记链接，一个字节都不下 ----------
    begin_case("c62")
    r, rep, rows, lg = run_attach("robots", mock_robots="deny-files")
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial" and rep.get("reason") == "attachment_partial"
          and st.get("attach_robots_denied") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "robots_denied" and a[0]["bytes"] == 0
          and "由你决定" in lg)
    record("62. robots 禁附件 → robots_denied 且 0 字节", ok,
           "robots_denied=%s ok=%s 字节=%s"
           % (st.get("attach_robots_denied"), st.get("attach_ok"),
              a[0]["bytes"] if a else None))

    # ---------- 63 重定向到被禁目录 → 最终 URL 也要过 robots ----------
    begin_case("c63")
    r, rep, rows, lg = run_attach("redir", mock_robots="deny-files")
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial"
          and st.get("attach_robots_denied") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "robots_denied"
          and "重定向后" in (a[0].get("error") or ""))
    record("63. 302 到被禁目录 → 最终 URL 仍被拦", ok,
           "状态=%s 说明=%r"
           % (a[0]["status"] if a else None, (a[0].get("error") or "")[:40]))

    # ---------- 64 下载失败 / 可执行文件 / 类型不符：三类各自有状态 ----------
    begin_case("c64")
    r, rep, rows, lg = run_attach("mixed")
    st = rep.get("stats", {})
    a = atts(rows)
    by = {x["url"].rsplit("/", 1)[-1]: x["status"] for x in a}
    ok = (rep.get("status") == "partial" and rep.get("reason") == "attachment_partial"
          and st.get("attach_ok") == 1
          and st.get("attach_download_failed") == 1
          and st.get("attach_denied_ext") == 1
          and by.get("ok.pdf") == "ok"
          and by.get("missing.pdf") in ("http_404", "download_failed")
          and by.get("type.exe") == "denied_ext")
    record("64. 404/可执行文件/正常 三种状态各自正确", ok,
           "状态=%s" % by)

    # ---------- 65 内网/回环地址默认拒绝（allow_private_hosts=False） ----------
    begin_case("c65")
    r, rep, rows, lg = run_attach("ok", extra={"MOCKATTACH_ALLOW_PRIVATE": "0"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial"
          and st.get("attach_private_host") == 2 and st.get("attach_ok") == 0
          and all(x["status"] == "private_host" for x in a))
    record("65. 回环地址默认拒绝（private_host）", ok,
           "private=%s ok=%s" % (st.get("attach_private_host"), st.get("attach_ok")))

    # ---------- 66 robots.txt 自己 500 → 不能当允许 ----------
    begin_case("c66")
    r, rep, rows, lg = run_attach("ok", mock_robots="robots500")
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial"
          and st.get("attach_robots_check_failed") == 2 and st.get("attach_ok") == 0
          and all(x["status"] == "robots_check_failed" for x in a))
    record("66. robots.txt 500 → robots_check_failed（不当允许）", ok,
           "check_failed=%s ok=%s"
           % (st.get("attach_robots_check_failed"), st.get("attach_ok")))

    # ---------- 67 chunked（无 Content-Length）超限：边下边数，且不留半截文件 ----------
    begin_case("c67")
    r, rep, rows, lg = run_attach("nolen", extra={"MOCKATTACH_MAXFILE": "1024"})
    st = rep.get("stats", {})
    a = atts(rows)
    leftovers = list((Path(CASE["dir"]) / "data" / "_attachments").rglob("*"))
    files_left = [p for p in leftovers if p.is_file()]
    ok = (rep.get("status") == "partial" and rep.get("reason") == "attachment_partial"
          and st.get("attach_too_large") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "too_large" and a[0]["path"] == ""
          and not files_left)
    record("67. chunked 无 Content-Length 超限 → 中断且不留半截文件", ok,
           "too_large=%s 落盘文件数=%d 记录字节=%s"
           % (st.get("attach_too_large"), len(files_left), a[0]["bytes"] if a else None))

    # ---------- 68 跨页累计配额：第 2 页必须接着第 1 页的用量算 ----------
    begin_case("c68")
    r, rep, rows, lg = run_attach("twopage",
                                  extra={"MOCKATTACH_PAGES": "2",
                                         "MOCKATTACH_MAXFILE": "4096",
                                         "MOCKATTACH_MAXTOTAL": "2500"})
    st = rep.get("stats", {})
    all_atts = [x for row in rows for x in (row.get("attachments") or [])]
    ok = (st.get("attach_ok") == 1 and st.get("attach_quota") == 1
          and st.get("attach_bytes") == 2048
          and len(rows) == 2
          and sorted(x["status"] for x in all_atts) == ["ok", "quota_exceeded"])
    record("68. 跨页累计配额：第 2 页接着算 → 只下 1 个", ok,
           "ok=%s quota=%s bytes=%s 状态=%s"
           % (st.get("attach_ok"), st.get("attach_quota"), st.get("attach_bytes"),
              sorted(x["status"] for x in all_atts)))

    # ---------- 69 按记录分目录 + 同名不覆盖 ----------
    begin_case("c69")
    r, rep, rows, lg = run_attach("dupname")
    st = rep.get("stats", {})
    all_atts = [x for row in rows for x in (row.get("attachments") or [])]
    paths = [x["path"] for x in all_atts if x["status"] == "ok"]
    dirs = {os.path.dirname(p) for p in paths}
    # 同一个目录内文件名必须唯一（不同目录同名是正常的，各记录各自一份）
    per_dir = {}
    for p in paths:
        per_dir.setdefault(os.path.dirname(p), []).append(os.path.basename(p))
    dir_names_unique = all(len(v) == len(set(v)) for v in per_dir.values())
    ok = (st.get("attach_ok") == 3 and len(paths) == 3
          and len(dirs) == 2                     # 两条记录两个目录
          and len(set(paths)) == 3               # 三条路径互不相同
          and dir_names_unique                   # 同目录内文件名不冲突
          and all(os.path.exists(p) for p in paths))
    record("69. 按记录分目录 + 同名不覆盖", ok,
           "ok=%s 目录数=%d 各自文件名=%s"
           % (st.get("attach_ok"), len(dirs), per_dir))

    # ---------- 70 重定向到 robots 禁目录：请求前就拦下（目标 0 次请求） ----------
    begin_case("c70")
    r, rep, rows, lg, hits_map = run_attach_hits("redir", mock_robots="deny-files",
                                                 hits_for=("/files-deny/secret.pdf",))
    st = rep.get("stats", {})
    a = atts(rows)
    hits = hits_map.get("/files-deny/secret.pdf", -1)
    ok = (rep.get("status") == "partial"
          and st.get("attach_robots_denied") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "robots_denied"
          and hits == 0)
    record("70. 重定向到被禁目录 → 请求前拦截（目标 0 请求）", ok,
           "robots_denied=%s 目标实际请求次数=%s" % (st.get("attach_robots_denied"), hits))

    # ---------- 71 重定向到内网：请求前就拦下（内网地址 0 次请求） ----------
    begin_case("c71")
    r, rep, rows, lg = run_attach("tointernal",
                                  extra={"MOCKATTACH_ALLOW_HOSTS": "127.0.0.1"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial"
          and st.get("attach_private_host") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "private_host"
          and "10.255.255.1" in (a[0].get("error") or ""))
    record("71. 重定向到内网 → 请求前拦截", ok,
           "private=%s 说明=%r"
           % (st.get("attach_private_host"), (a[0].get("error") or "")[:40]))

    # ---------- 72 Crawl-delay 生效 ----------
    begin_case("c72")
    t0 = time.time()
    r, rep, rows, lg = run_attach("ok", mock_robots="crawldelay")
    dt = time.time() - t0
    st = rep.get("stats", {})
    ok = (st.get("attach_ok") == 2 and dt >= 0.9)   # 两个附件之间至少等 1 秒
    record("72. 遵守 robots Crawl-delay（2 个附件 ≥1s）", ok,
           "ok=%s 耗时=%.2fs" % (st.get("attach_ok"), dt))

    # ---------- 73 附件重试：第一次 500、第二次 200 ----------
    begin_case("c73")
    r, rep, rows, lg = run_attach("flaky", extra={"MOCKATTACH_RETRIES": "1"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (st.get("attach_ok") == 1 and a and a[0]["status"] == "ok"
          and st.get("attach_retried") == 1
          and rep.get("status") == "success")
    record("73. 附件重试：首次 500 后重试成功", ok,
           "ok=%s 重试次数=%s 状态=%s"
           % (st.get("attach_ok"), st.get("attach_retried"),
              a[0]["status"] if a else None))

    # ---------- 74 域名解析到内网 → 必须拦（SSRF 边界） ----------
    begin_case("c74")
    r, rep, rows, lg = run_attach("dns",
                                  extra={"MOCKATTACH_ALLOW_PRIVATE": "0",
                                         "MOCKATTACH_CHECK_DNS": "1",
                                         # 测试钩子：让 evil.example 解析到 127.0.0.1
                                         "CRAWLER_FAKE_DNS": "evil.example=127.0.0.1"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial"
          and st.get("attach_private_host") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "private_host"
          and "解析到内网地址" in (a[0].get("error") or ""))
    record("74. 域名 DNS 解析到内网 → 拒绝（SSRF 边界）", ok,
           "private=%s 说明=%r"
           % (st.get("attach_private_host"), (a[0].get("error") or "")[:50]))

    # ---------- 75 扩展名白名单：只收 pdf/word/excel/zip ----------
    begin_case("c75")
    r, rep, rows, lg = run_attach("txt",
                                  extra={"MOCKATTACH_EXT_ALLOW": ".pdf,.docx,.xlsx,.zip"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial"
          and st.get("attach_denied_ext") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "denied_ext"
          and "不在白名单" in (a[0].get("error") or ""))
    record("75. 扩展名白名单：.txt 被拒", ok,
           "denied_ext=%s 说明=%r"
           % (st.get("attach_denied_ext"), (a[0].get("error") or "")[:40]))

    # ---------- 76 文件头校验：改名成 .pdf 的 exe 被识破 ----------
    begin_case("c76")
    r, rep, rows, lg = run_attach("fakepdf", extra={"MOCKATTACH_SNIFF": "1"})
    st = rep.get("stats", {})
    a = atts(rows)
    leftover = [p for p in (Path(CASE["dir"]) / "data" / "_attachments").rglob("*") if p.is_file()]
    ok = (rep.get("status") == "partial"
          and st.get("attach_type_rejected") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "content_mismatch"
          and not leftover)
    record("76. 文件头与扩展名不符 → content_mismatch", ok,
           "type_rejected=%s 状态=%s 残留文件=%d"
           % (st.get("attach_type_rejected"), a[0]["status"] if a else None, len(leftover)))

    # ---------- 77 主入口 robots.txt 首次 500、第二次 200 → 继续，不 overall failed ----------
    begin_case("c77")
    p = start_mock("robots500once")
    try:
        r = crawl(["--site", "mock", "--pages", "1", "--reset"]) 
        rep = latest_report("mock") or {}
        st = rep.get("stats", {})
        n = count_lines(RAW)
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and st.get("pages_ok") == 1 and n == 3
              and "重试" in read_log())
        record("77. 主 robots.txt 首次 500 → 重试后继续（不整体失败）", ok,
               "status=%s pages_ok=%s lines=%d"
               % (rep.get("status"), st.get("pages_ok"), n))
    finally:
        stop_mock(p)

    # ---------- 78 主 robots.txt 首次超时（不是 500）→ 重试后继续 ----------
    begin_case("c78")
    p = start_mock("robotstimeoutonce")
    try:
        t0 = time.time()
        r = crawl(["--site", "mock", "--pages", "1", "--reset"])
        dt = time.time() - t0
        rep = latest_report("mock") or {}
        st = rep.get("stats", {})
        n = count_lines(RAW)
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and st.get("pages_ok") == 1 and n == 3
              and "重试" in read_log() and dt >= 1.0)
        record("78. 主 robots.txt 首次超时 → 重试后继续", ok,
               "status=%s pages_ok=%s lines=%d 耗时=%.1fs"
               % (rep.get("status"), st.get("pages_ok"), n, dt))
    finally:
        stop_mock(p)

    # ---------- 79 DNS 解析失败 → 拒绝（fail-closed，不放行） ----------
    begin_case("c79")
    r, rep, rows, lg = run_attach("dns",
                                  extra={"MOCKATTACH_ALLOW_PRIVATE": "0",
                                         "MOCKATTACH_CHECK_DNS": "1",
                                         # 测试钩子：让 bad.example 解析失败
                                         "CRAWLER_FAKE_DNS": "evil.example=FAIL"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (rep.get("status") == "partial"
          and st.get("attach_dns_failed") == 1 and st.get("attach_ok") == 0
          and a and a[0]["status"] == "dns_resolve_failed"
          and "解析失败" in (a[0].get("error") or ""))
    record("79. DNS 解析失败 → 拒绝（fail-closed）", ok,
           "状态=%s 说明=%r"
           % (a[0]["status"] if a else None, (a[0].get("error") or "")[:40]))

    # ---------- 80 magic 分块：文件头被切成 4 字节小块也要认得出来 ----------
    begin_case("c80")
    r, rep, rows, lg = run_attach("slowchunk", extra={"MOCKATTACH_SNIFF": "1"})
    st = rep.get("stats", {})
    a = atts(rows)
    ok = (st.get("attach_ok") == 1 and a and a[0]["status"] == "ok"
          and a[0]["bytes"] > 8)
    record("80. magic 校验支持小分块（4 字节/块）", ok,
           "ok=%s 状态=%s 字节=%s"
           % (st.get("attach_ok"), a[0]["status"] if a else None,
              a[0]["bytes"] if a else None))

    # ---------- 81 字段签名含可选字段（只有部分记录有 attachments） ----------
    begin_case("c81")
    r, rep, rows, lg = run_attach("optfield")
    fields = (rep.get("field_signature") or {}).get("fields") or []
    ok = (len(rows) == 2
          and "attachments" in fields          # 并集：不能被"第一行恰好没有"带偏
          and any(x.get("attachments") for x in rows)
          and any(not x.get("attachments") for x in rows))
    record("81. 字段签名用并集（可选字段不会漏）", ok,
           "字段数=%d 含 attachments=%s"
           % (len(fields), "attachments" in fields))

    # ---------- 82 content_hash 稳定性：同内容两次抓取哈希必须一致 ----------
    # 注意：必须用同一个 mock 进程跑两次。换进程端口就变了，
    # detail_url 里的端口跟着变，hash 当然不同——那不是 hash 不稳，是测试造错了。
    begin_case("c82")
    ids = []
    p = start_mock("none")
    try:
        for job in ("hash_a", "hash_b"):
            env = {"MOCKJSON_CASE": "items", "MOCKJSON_PAGES": "1"}
            crawl(["--site", "mockjson", "--job", job], env_extra=env)
            f = Path(CASE["dir"]) / "data" / ("%s.jsonl" % job)
            ids.append([json.loads(l)["content_hash"]
                        for l in f.read_text(encoding="utf-8").splitlines() if l.strip()])
    finally:
        stop_mock(p)
    ok = (len(ids[0]) == 3 and len(ids[1]) == 3 and ids[0] == ids[1])
    record("82. content_hash 跨运行稳定", ok,
           "A=%s B=%s" % (ids[0][:2], ids[1][:2]))

    # =====================================================================
    # 83~86：hash 规范化 / 文件名 / 字段签名 / 去重跳过附件
    # =====================================================================
    sys.path.insert(0, str(ROOT / "crawlers"))

    # ---------- 83 真实样本的附件名都要带扩展名 ----------
    begin_case("c83")
    try:
        import crawler as _crawler
        import sites.foodlaw as _fl
        html = (ROOT / "tests" / "data" / "foodlaw_detail1.html"
                    ).read_text(encoding="utf-8", errors="replace")
        d = _fl.parse_detail(html)
        atts_real = d.get("attachments") or []
        names = [_crawler._safe_filename(a.get("name"), a["url"], i)
                 for i, a in enumerate(atts_real, 1)]
        ok = (len(atts_real) >= 1
              and all(os.path.splitext(n)[1].lower() in _crawler.DOC_EXTS for n in names))
        record("83. 真实样本附件名都带扩展名", ok,
               "附件=%d 名字=%s" % (len(atts_real), names))
    finally:
        pass

    # ---------- 84 content_hash 规范化：路径/文件名变不算内容变 ----------
    begin_case("c84")
    try:
        base = {"title": "x", "publish_date": "2026-01-01",
                "attachments": [{"url": "u1", "status": "ok", "bytes": 5,
                                 "sha256": "aa", "path": "C:/a/x.pdf", "name": "x.pdf"}]}
        moved = dict(base)
        moved["attachments"] = [dict(base["attachments"][0],
                                     path="D:/放别处/y.pdf", name="y.pdf")]
        changed = dict(base)
        changed["attachments"] = [dict(base["attachments"][0], sha256="bb")]
        h0, h1, h2 = (_crawler.content_hash_of(x) for x in (base, moved, changed))
        ok = (h0 == h1 and h0 != h2)
        record("84. content_hash 对路径/文件名不敏感", ok,
               "原名=%s 改名=%s 改内容=%s" % (h0, h1, h2))
    finally:
        pass

    # ---------- 85 二跑（全跳过）field_signature 仍然非空 ----------
    begin_case("c85")
    p = start_mock("none")
    try:
        env = {"MOCKJSON_CASE": "items", "MOCKJSON_PAGES": "1"}
        crawl(["--site", "mockjson", "--job", "sigjob"], env_extra=env)
        rep1 = latest_report("sigjob") or {}
        f1 = (rep1.get("field_signature") or {})
        crawl(["--site", "mockjson", "--job", "sigjob"], env_extra=env)
        rep2 = latest_report("sigjob") or {}
        f2 = (rep2.get("field_signature") or {})
        ok = (f1.get("field_count", 0) > 0
              and f2.get("field_count", 0) == f1.get("field_count")
              and set(f2.get("fields") or []) == set(f1.get("fields") or []))
        record("85. 二跑 field_signature 不空且一致", ok,
               "首跑=%s 二跑=%s" % (f1.get("field_count"), f2.get("field_count")))
    finally:
        stop_mock(p)

    # ---------- 86 去重前置：二跑不再请求详情/附件 ----------
    begin_case("c86")
    p = start_mock("none")
    try:
        env = {"MOCKATTACH_CASE": "ok"}
        crawl(["--site", "mockattach", "--job", "dedupjob"], env_extra=env)
        hits1 = {}
        for path in ("/files/ok.pdf", "/files/ok2.pdf"):
            q = http_probe_json(p, "/api/hits?p=%s" % path)
            hits1[path] = int((q.get("data") or {}).get("hits") or 0)
        n1 = count_lines(str(Path(CASE["dir"]) / "data" / "dedupjob.jsonl"))

        crawl(["--site", "mockattach", "--job", "dedupjob"], env_extra=env)
        hits2 = {}
        for path in ("/files/ok.pdf", "/files/ok2.pdf"):
            q = http_probe_json(p, "/api/hits?p=%s" % path)
            hits2[path] = int((q.get("data") or {}).get("hits") or 0)
        n2 = count_lines(str(Path(CASE["dir"]) / "data" / "dedupjob.jsonl"))
        ok = (n1 == 1 and n2 == 1                      # 没有重复写入
              and hits2 == hits1                        # 二跑没再下附件
              and hits1.get("/files/ok.pdf", 0) >= 1)
        record("86. 去重前置：二跑不再请求附件", ok,
               "首跑命中=%s 二跑命中=%s 行数=%d→%d"
               % (hits1, hits2, n1, n2))
    finally:
        stop_mock(p)

    # ---------- 87 文件名扩展名优先级 ----------
    begin_case("c87")
    try:
        cases = [
            # (名字, URL, 期望扩展名, 说明)
            ("2.原产地证书格式.doc", "http://x/a/abc.docx", ".docx", "URL 的文档扩展名优先"),
            ("说明书.pdf", "http://x/a/dl.php?id=3", ".pdf", "URL 不是文档扩展名 → 保留名字的"),
            ("附件：", "http://x/a/cj2026.pdf", ".pdf", "名字无信息量 → 用 URL 文件名"),
            ("1. 依法设置…申请书", "http://x/a/fy.docx", ".docx", "带点但不是扩展名"),
        ]
        bad = []
        for name, url, want, why in cases:
            got = _crawler._safe_filename(name, url, 1)
            ext = os.path.splitext(got)[1].lower()
            if ext != want:
                bad.append("%s: 期望 %s 实际 %s（%s）" % (name, want, ext, why))
        ok = not bad
        record("87. 文件名扩展名优先级（URL 文档扩展名 > 名字）", ok,
               "全部符合" if ok else "; ".join(bad))
    finally:
        pass

    # ---------- 88 同页重复记录：详情只抓 1 次、附件只下 1 份 ----------
    begin_case("c88")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockattach"], env_extra={"MOCKATTACH_CASE": "dupsame"})
        rep = latest_report("mockattach") or {}
        rows = read_rows(RAW_A)
        st = rep.get("stats", {})
        q = http_probe_json(p, "/api/hits?p=/files/ok.pdf")
        hits = int((q.get("data") or {}).get("hits") or 0)
        atts_all = [a for row in rows for a in (row.get("attachments") or [])]
        ok = (len(rows) == 1                       # 只写 1 条
              and st.get("records_dup") == 1      # 同页重复被计到 dup
              and st.get("attach_ok") == 1        # 只下 1 份
              and hits == 1                        # 只请求 1 次
              and len(atts_all) == 1)
        record("88. 同页重复记录 → 详情/附件只做一次", ok,
               "记录=%d dup=%s 附件ok=%s 请求次数=%d"
               % (len(rows), st.get("records_dup"), st.get("attach_ok"), hits))
    finally:
        stop_mock(p)

    # ---------- 89 可重试失败 → 下次开跑自动补抓成功 ----------
    begin_case("c89")
    p = start_mock("none")
    try:
        env = {"MOCKATTACH_CASE": "retry"}
        crawl(["--site", "mockattach", "--job", "repjob"], env_extra=env)
        f = Path(CASE["dir"]) / "data" / "repjob.jsonl"
        before = [a for l in f.read_text(encoding="utf-8").splitlines() if l.strip()
                  for a in (json.loads(l).get("attachments") or [])]
        # 第二次开跑：开跑前补抓
        crawl(["--site", "mockattach", "--job", "repjob"], env_extra=env)
        after = [a for l in f.read_text(encoding="utf-8").splitlines() if l.strip()
                 for a in (json.loads(l).get("attachments") or [])]
        rep = latest_report("repjob") or {}
        st = rep.get("stats", {})
        ok = (before and before[0]["status"] in ("download_failed", "http_500")
              and after and after[0]["status"] == "ok"
              and st.get("attach_repair_planned") == 1
              and st.get("attach_repaired_ok") == 1
              and os.path.exists(after[0]["path"]))
        record("89. 可重试失败 → 下次开跑自动补抓成功", ok,
               "补前=%s 补后=%s planned=%s ok=%s"
               % (before[0]["status"] if before else None,
                  after[0]["status"] if after else None,
                  st.get("attach_repair_planned"), st.get("attach_repaired_ok")))
    finally:
        stop_mock(p)

    # ---------- 90 永久失败 → 不重试（补抓计划为 0） ----------
    begin_case("c90")
    p = start_mock("none")
    try:
        env = {"MOCKATTACH_CASE": "mixed", "MOCKATTACH_EXT_ALLOW": ".pdf,.docx"}
        crawl(["--site", "mockattach", "--job", "permjob"], env_extra=env)
        f = Path(CASE["dir"]) / "data" / "permjob.jsonl"
        before = [a for l in f.read_text(encoding="utf-8").splitlines() if l.strip()
                  for a in (json.loads(l).get("attachments") or [])]
        crawl(["--site", "mockattach", "--job", "permjob"], env_extra=env)
        rep = latest_report("permjob") or {}
        st = rep.get("stats", {})
        statuses = {a["url"].rsplit("/", 1)[-1].split("?")[0]: a["status"] for a in before}
        ok = (statuses.get("missing.pdf") == "http_404"       # 404 标成永久失败
              and statuses.get("type.exe") in ("denied_ext", "type_rejected")
              and st.get("attach_repair_planned") == 0        # 全都是永久失败 → 不补
              and st.get("attach_repaired_fail") in (0, None))
        record("90. 永久失败（404/类型不对）→ 补抓计划为 0", ok,
               "首跑=%s planned=%s 补后失败=%s"
               % (statuses, st.get("attach_repair_planned"), st.get("attach_repaired_fail")))
    finally:
        stop_mock(p)

    # ---------- 91 异常后配额计数仍正确（W2） ----------
    begin_case("c91")
    p = start_mock("none")
    try:
        import crawler as _c
        port = CASE["port"]
        base = "http://127.0.0.1:%d" % port
        ac = dict(_c.ATTACH_DEFAULTS)
        ac.update({"enabled": True, "dir": str(Path(CASE["dir"]) / "data" / "_att"),
                   "allow_private_hosts": True, "respect_robots": False,
                   "delay_min": 0.0, "delay_max": 0.0})
        _c.CONFIG = dict(_c.CONFIG)
        _c.CONFIG["attachments"] = ac

        stat = {"attach_bytes": 2048}     # 假装前面已经下过 2048 字节
        anomalies = []
        orig = _c._unique_path
        calls = {"n": 0}

        def boom(dest_dir, name):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("模拟第 2 个文件落盘时炸")
            return orig(dest_dir, name)

        _c._unique_path = boom
        raised = False
        try:
            _c.download_attachments(
                [{"detail_url": "u1", "attachments": [
                    {"url": base + "/files/ok.pdf"},
                    {"url": base + "/files/ok2.pdf"}]}],
                _c.session_factory(), lambda *a, **k: None, _c.CONFIG,
                anomalies, stat, "q1")
        except Exception:
            raised = True
        finally:
            _c._unique_path = orig

        ok = (raised
              and stat.get("attach_ok") == 1        # 第 1 个成功已记
              and stat.get("attach_bytes") == 2048 + 56   # 旧配额没被清零
              and stat.get("attach_seen") == 2)
        record("91. 附件阶段异常：已发生的计数不丢、配额不被清零", ok,
               "抛异常=%s ok=%s 配额=%s seen=%s"
               % (raised, stat.get("attach_ok"), stat.get("attach_bytes"),
                  stat.get("attach_seen")))
    finally:
        stop_mock(p)

    # ---------- 92 坏 JSONL + 有待补附件 → 中止，文件一个字节都不动 ----------
    begin_case("c92")
    p = start_mock("none")
    try:
        job = "badjob"
        f = Path(CASE["dir"]) / "data" / (job + ".jsonl")
        good = {"title": "a", "detail_url": "http://x/1",
                "attachments": [{"url": "http://127.0.0.1:1/a.pdf",
                                  "status": "download_failed", "bytes": 0,
                                  "sha256": "", "path": "", "name": "a.pdf"}]}
        f.write_text(json.dumps(good, ensure_ascii=False) + "\n"
                     + "{这不是合法 JSON\n", encoding="utf-8")
        before = f.read_bytes()
        q = http_probe_json(p, "/api/hits?p=/files/ok.pdf")
        r = crawl(["--site", "mockattach", "--job", job],
                  env_extra={"MOCKATTACH_CASE": "ok"})
        rep = latest_report(job) or {}
        after = f.read_bytes()
        q2 = http_probe_json(p, "/api/hits?p=/files/ok.pdf")
        ok = (rep.get("reason") == "data_file_corrupt"
              and r.returncode == 2
              and before == after                      # 文件原样
              and int((q.get("data") or {}).get("hits") or 0)
                  == int((q2.get("data") or {}).get("hits") or 0))  # 没发附件请求
        record("92. 坏 JSONL → 中止且文件不变（不静默丢行）", ok,
               "reason=%s rc=%s 文件未变=%s"
               % (rep.get("reason"), r.returncode, before == after))
    finally:
        stop_mock(p)

    # ---------- 93 SPA 第 1 层：直接打后端 JSON 接口 ----------
    begin_case("c93")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockspa", "--job", "spaapi"],
                  env_extra={"MOCKSPA_MODE": "api"})
        rep = latest_report("spaapi") or {}
        rows = read_rows(str(Path(CASE["dir"]) / "data" / "spaapi.jsonl"))
        titles = [x.get("title") for x in rows]
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and len(rows) == 6                       # 2 页 × 3 条
              and all("接口" in (t or "") for t in titles)
              and len({x["detail_url"] for x in rows}) == 6)
        record("93. SPA 第 1 层：找接口 → JSON 直取（2 页 6 条）", ok,
               "status=%s rows=%d 示例=%s"
               % (rep.get("status"), len(rows), titles[:2]))
    finally:
        stop_mock(p)

    # ---------- 94 SPA 第 2 层：抠页面内嵌 __NEXT_DATA__ ----------
    begin_case("c94")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mockspa", "--job", "spaembed"],
                  env_extra={"MOCKSPA_MODE": "embedded"})
        rep = latest_report("spaembed") or {}
        rows = read_rows(str(Path(CASE["dir"]) / "data" / "spaembed.jsonl"))
        titles = [x.get("title") for x in rows]
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and len(rows) == 2
              and titles == ["内嵌一", "内嵌二"]
              and all(x["detail_url"].startswith("/detail/") for x in rows))
        record("94. SPA 第 2 层：抠内嵌 JSON（空壳页 → 2 条）", ok,
               "status=%s rows=%d 标题=%s"
               % (rep.get("status"), len(rows), titles))
    finally:
        stop_mock(p)

    # =================================================================
    # 阶段A：Retry-After / 软封 / 冷却 / Referer（95–105）
    # =================================================================

    # ---------- 95 429 + Retry-After: 2 → 真按 2 秒等 ----------
    def _jlog(job):
        return read_log_file(str(Path(CASE["dir"]) / "log" / ("crawler-%s.log" % job)))

    begin_case("c95")
    p = start_mock("none")
    try:
        t0 = time.time()
        r = crawl(["--site", "mockra", "--job", "ra_sec"],
                  env_extra={"MOCKRA_MODE": "sec"})
        dt = time.time() - t0
        rep = latest_report("ra_sec") or {}
        st = rep.get("stats", {})
        lg = _jlog("ra_sec")
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
        lg = _jlog("ra_date")
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
        lg = _jlog("ra_none")
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
        def _hits(pp):
            return int((http_probe_json(p, "/api/hits?p=%s" % pp).get("data") or {}).get("hits") or 0)
        b1, b2, bc = _hits("/soft/p1.html"), _hits("/soft/p2.html"), _hits("/soft/canary.html")
        r = crawl(["--site", "mocksoft", "--job", "soft_blocked"],
                  env_extra={"MOCKSOFT_MODE": "blocked"})
        rep = latest_report("soft_blocked") or {}
        st = rep.get("stats", {})
        h1, h2, hc = _hits("/soft/p1.html"), _hits("/soft/p2.html"), _hits("/soft/canary.html")
        ok = (r.returncode == 6 and rep.get("status") == "failed"
              and rep.get("reason") == "soft_block_suspected"
              and st.get("soft_block_detected") == 1
              and st.get("canary_requests") == 1
              and h1 == 1 and h2 == 0 and hc == 1)
        record("98. 空页+canary 也空 → 软封 rc=6，第 2 页 0 次请求", ok,
               "rc=%s reason=%s p1=%d→%d p2=%d→%d canary=%d→%d"
               % (r.returncode, rep.get("reason"), b1, h1, b2, h2, bc, hc))
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
        cdp = Path(CASE["state"]) / ("_cooldown_%s.json" % host.replace(":", "_"))
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
        cdp = Path(CASE["state"]) / ("_cooldown_%s.json" % host.replace(":", "_"))
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
        pages_ok = _wz.CONFIG["page_end"] == 150
        bad = None
        os.environ["WZ_SETTR"] = "9"
        try:
            importlib.reload(_wz)
        except SystemExit as e:
            bad = str(e)
        os.environ.pop("WZ_SETTR", None)
        importlib.reload(_wz)
        ok = url_ok and delay_ok and pages_ok and bad is not None
        record("103. WZ_SETTR=3 生效（3~5 秒/150 页），=9 直接报错", ok,
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
        smp = ROOT / "tests" / "data" / "_probe_wzrc.html"
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

    # =================================================================
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

    # =================================================================
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
            # v11：判定改读 robots 原文（RFC 9309），不再用 parser 对象
            _c1._ROBOTS["text"] = "User-agent: *\nDisallow: /soft/canary.html\n"
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

    # ---------- 113 坏冷却文件不得自我续命（第二次 until ≤ 第一次） ----------
    begin_case("c113")
    p = start_mock("none")
    try:
        port = CASE["port"]
        host = "127.0.0.1:%d" % port
        cdp = Path(CASE["state"]) / ("_cooldown_%s.json" % host.replace(":", "_"))
        cdp.write_text("{ 这不是合法 JSON ", encoding="utf-8")
        b1 = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        r1 = crawl(["--site", "mocksoft", "--job", "cdx1"], env_extra={"MOCKSOFT_MODE": "ok"})
        rep1 = latest_report("cdx1") or {}
        until1 = (rep1.get("cooldown") or {}).get("until")
        quarantined = list(Path(CASE["state"]).glob("*.corrupt-*"))
        new_ok = False
        try:
            nd = json.loads(cdp.read_text(encoding="utf-8"))
            new_ok = (nd.get("reason") == "cooldown_file_corrupt"
                      and bool(nd.get("until")))
        except Exception:
            new_ok = False
        a1 = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        r2 = crawl(["--site", "mocksoft", "--job", "cdx2"], env_extra={"MOCKSOFT_MODE": "ok"})
        rep2 = latest_report("cdx2") or {}
        until2 = (rep2.get("cooldown") or {}).get("until")
        a2 = int((http_probe_json(p, "/api/hits?p=/soft/p1.html").get("data") or {}).get("hits") or 0)
        # 日志也要断言：光写不接线等于没写（跟 total_path / attach_retried 同一类问题）
        lg = read_log_file(str(Path(CASE["dir"]) / "log" / "crawler-cdx1.log"))
        log_ok = ("已隔离" in lg and ".corrupt-" in lg and "到期自动恢复" in lg)
        ok = (r1.returncode == 6 and r2.returncode == 6
              and b1 == a1 == a2                       # 两次都零请求
              and bool(quarantined) and new_ok
              and until1 and until2 and until2 <= until1
              and log_ok)
        record("113. 坏冷却文件：隔离+落合法冷却，两次都不续期", ok,
               "rc=%s/%s until=%s→%s 隔离=%d 新文件合法=%s 命中=%d/%d/%d 日志含隔离路径=%s"
               % (r1.returncode, r2.returncode, until1, until2, len(quarantined),
                  new_ok, b1, a1, a2, log_ok))
    finally:
        stop_mock(p)

    # ---------- 114 rebuild-index 不被 json/soft_block 与页范围挡住 ----------
    begin_case("c114")
    p = start_mock("none")
    try:
        b1 = int((http_probe_json(p, "/api/hits?p=/spa/api/list").get("data") or {}).get("hits") or 0)
        r1 = crawl(["--site", "mockspa", "--job", "rbs1", "--rebuild-index"],
                   env_extra={"MOCKSPA_MODE": "api", "MOCKSPA_SOFT": "1"})
        rep1 = latest_report("rbs1") or {}
        r2 = crawl(["--site", "mockspa", "--job", "rbs2", "--rebuild-index",
                    "--pages", "2", "--page-from", "5"],
                   env_extra={"MOCKSPA_MODE": "api", "MOCKSPA_SOFT": "1"})
        rep2 = latest_report("rbs2") or {}
        a1 = int((http_probe_json(p, "/api/hits?p=/spa/api/list").get("data") or {}).get("hits") or 0)
        ok = (r1.returncode == 0 and rep1.get("reason") == "rebuild_index_only"
              and r2.returncode == 0 and rep2.get("reason") == "rebuild_index_only"
              and b1 == a1)
        record("114. rebuild-index 不被 json+soft_block / 页范围挡", ok,
               "rc=%s/%s reason=%s/%s 命中 %d→%d"
               % (r1.returncode, r2.returncode, rep1.get("reason"),
                  rep2.get("reason"), b1, a1))
    finally:
        stop_mock(p)

    # =================================================================
    # 提案1/3（115–122）：总页数声明 / 页大小记录
    # =================================================================

    # 115 声明页数 < 配置页数 → 截断 + partial/page_range_truncated
    begin_case("c115")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocktotal", "--job", "tot1"],
                  env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "5"})
        rep = latest_report("tot1") or {}
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("pages_declared") == 3
              and rep.get("pages_planned") == 5
              and rep.get("pages_effective") == 3
              and rep.get("truncated") is False
              and rep.get("coverage") == 1.0)
        record("115. 声明 3 页 ≤ 计划 5 页 → 夹紧到 3、success、coverage=1.0", ok,
               "rc=%s reason=%s declared=%s planned=%s eff=%s cov=%s trunc=%s"
               % (r.returncode, rep.get("reason"), rep.get("pages_declared"),
                  rep.get("pages_planned"), rep.get("pages_effective"),
                  rep.get("coverage"), rep.get("truncated")))
    finally:
        stop_mock(p)

    # 116 声明页数 > 配置页数 → 不截断，success，coverage < 1
    begin_case("c116")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocktotal", "--job", "tot2"],
                  env_extra={"MOCK_TOTAL": "10", "MOCK_PLAN": "3"})
        rep = latest_report("tot2") or {}
        ok = (r.returncode == 3 and rep.get("status") == "partial"
              and rep.get("reason") == "page_range_truncated"
              and rep.get("pages_declared") == 10
              and rep.get("truncated") is True
              and rep.get("coverage") == 0.3)
        record("116. 声明 10 页 > 计划 3 页 → partial/page_range_truncated，coverage=0.3", ok,
               "rc=%s declared=%s cov=%s trunc=%s"
               % (r.returncode, rep.get("pages_declared"), rep.get("coverage"),
                  rep.get("truncated")))
    finally:
        stop_mock(p)

    # 117 显式 --pages 时截断也按 success，但必须显示 coverage
    begin_case("c117")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocktotal", "--job", "tot3", "--pages", "2"],
                  env_extra={"MOCK_TOTAL": "10"})
        rep = latest_report("tot3") or {}
        ok = (r.returncode == 0 and rep.get("status") == "success"
              and rep.get("pages_declared") == 10
              and rep.get("coverage") == 0.2)
        record("117. 显式 --pages 2 → success，coverage=0.2", ok,
               "rc=%s status=%s cov=%s" % (r.returncode, rep.get("status"), rep.get("coverage")))
    finally:
        stop_mock(p)

    # 118 页面没有声明 → 按配置跑 + anomaly（不拦）
    begin_case("c118")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocktotal", "--job", "tot4"],
                  env_extra={"MOCK_TOTAL": "none", "MOCK_PLAN": "2"})
        rep = latest_report("tot4") or {}
        reasons = [x.get("reason") or "" for x in (rep.get("anomalies") or [])]
        ok = (r.returncode == 0 and rep.get("pages_declared") is None
              and rep.get("truncated") is False
              and any("读不到总页数" in x for x in reasons))
        record("118. 页面无声明 → 按配置跑 + anomaly", ok,
               "rc=%s declared=%s anomaly=%s"
               % (r.returncode, rep.get("pages_declared"),
                  "有" if any("读不到总页数" in x for x in reasons) else "无"))
    finally:
        stop_mock(p)

    # 119 续跑跳过第 1 页，仍能从第 2 页读到 M
    begin_case("c119")
    p = start_mock("none")
    try:
        (Path(CASE["dir"]) / "data" / "mtot.jsonl").write_text("", encoding="utf-8")
        st_path = Path(CASE["state"]) / "state_mtot.json"
        st_path.write_text(json.dumps({
            "pages_done": [1], "seen_keys": [], "urls_done": [],
            "paginate_mode": "number", "next_url": "",
            "out_file": str(Path(CASE["dir"]) / "data" / "mtot.jsonl"),
            "updated_at": "2026-11-11T00:00:00+08:00"}), encoding="utf-8")
        r = crawl(["--site", "mocktotal", "--job", "mtot"],
                  env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "5"})
        rep = latest_report("mtot") or {}
        ok = (rep.get("pages_declared") == 3 and rep.get("truncated") is False
              and rep.get("coverage") == 1.0
              and rep.get("stats", {}).get("pages_skipped", 0) >= 1
              and rep.get("stats", {}).get("pages_ok", 0) == 2)
        record("119. 续跑跳过第 1 页仍读到 M=3（success、coverage=1.0）", ok,
               "declared=%s skipped=%s ok=%s"
               % (rep.get("pages_declared"), rep.get("stats", {}).get("pages_skipped"),
                  rep.get("stats", {}).get("pages_ok")))
    finally:
        stop_mock(p)

    # 120 站点声明 page_size → 写进 state 与报告
    begin_case("c120")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocktotal", "--job", "ps1"],
                  env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3", "MOCK_PAGE_SIZE": "20"})
        rep = latest_report("ps1") or {}
        st = json.loads((Path(CASE["state"]) / "state_ps1.json").read_text(encoding="utf-8"))
        ok = (r.returncode == 0 and st.get("page_size") == 20
              and rep.get("page_size") == 20)
        record("120. page_size=20 写进 state 与报告", ok,
               "state.page_size=%s report.page_size=%s"
               % (st.get("page_size"), rep.get("page_size")))
    finally:
        stop_mock(p)

    # 121 page_size 变更 → 清 pages_done，保留 seen_keys
    begin_case("c121")
    p = start_mock("none")
    try:
        (Path(CASE["dir"]) / "data" / "ps2.jsonl").write_text(
            json.dumps({"detail_url": "k1", "title": "old"}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        st_path = Path(CASE["state"]) / "state_ps2.json"
        st_path.write_text(json.dumps({
            "pages_done": [1, 2], "seen_keys": ["k1", "k2"], "urls_done": [],
            "paginate_mode": "number", "next_url": "", "page_size": 20,
            "out_file": str(Path(CASE["dir"]) / "data" / "ps2.jsonl"),
            "updated_at": "2026-11-11T00:00:00+08:00"}), encoding="utf-8")
        r = crawl(["--site", "mocktotal", "--job", "ps2"],
                  env_extra={"MOCK_TOTAL": "3", "MOCK_PLAN": "3", "MOCK_PAGE_SIZE": "40"})
        st = json.loads(st_path.read_text(encoding="utf-8"))
        rep = latest_report("ps2") or {}
        stt = rep.get("stats", {})
        ok = (st.get("page_size") == 40
              and stt.get("pages_skipped", 0) == 0      # 旧断点没拦住 → 真的清掉了
              and stt.get("pages_ok", 0) == 3
              and "k1" in (st.get("seen_keys") or []))  # 去重键保留
        record("121. page_size 20→40 → 清 pages_done、保留 seen_keys", ok,
               "page_size=%s skipped=%s ok=%s seen含k1=%s"
               % (st.get("page_size"), stt.get("pages_skipped"), stt.get("pages_ok"),
                  "k1" in (st.get("seen_keys") or [])))
    finally:
        stop_mock(p)

    # 122 仅探针标记 → 报告可见 page_size_probe
    begin_case("c122")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mocktotal", "--job", "ps3"],
                  env_extra={"MOCK_TOTAL": "2", "MOCK_PLAN": "2",
                             "MOCK_PAGE_SIZE": "50", "MOCK_PAGE_PROBE": "1"})
        rep = latest_report("ps3") or {}
        ok = (r.returncode == 0 and rep.get("page_size_probe") is True
              and rep.get("page_size") == 50)
        record("122. 探针标记写进报告（page_size_probe=true）", ok,
               "page_size=%s probe=%s" % (rep.get("page_size"), rep.get("page_size_probe")))
    finally:
        stop_mock(p)

    # ---------- 123 noop 续跑：pages_ok=0 但 coverage 必须 1.0 ----------
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
                    "MOCK_PS_BROKEN": "1", "MOCK_PROBE_BROKEN": "1",
                    "CRAWLER_STATE_DIR": CASE["state"],
                    "CRAWLER_OUT_DIR": str(Path(CASE["dir"]) / "data"),
                    "CRAWLER_LOG_DIR": str(Path(CASE["dir"]) / "log"),
                    "CRAWLER_REPORT_DIR": str(Path(CASE["dir"]) / "report")})
        rr = subprocess.run(
            [PY, str(ROOT / "scripts" / "probe_pagesize.py"),
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

    # ---------- 127 同一 job 换筛选 → 旧断点作废，不能静默跳过 ----------
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

    # ---------- 129 next 模式换筛选 → urls_done/next_url 也要清干净 ----------
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

    # ================= 状态断言补齐（131–138）=================
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
              # v11 起"列表页被禁立刻停"：只记第 1 页 blocked，不再空跑第 2 页
              and stt.get("pages_blocked", 0) == 1 and stt.get("pages_ok", -1) == 0)
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

    # ============ 139–143：真实样本离线解析回归（v8 抽 _common.py 的护栏）============
    # 为什么要有这 5 条：138 项测试全跑 mock，**测不到 5 个真实站点的解析器**。
    # 抽公共模块前先用现有代码生成 tools/golden/*.json，这里逐字段比对；
    # 以后任何人动 parse_list / total_pages_pattern，都会立刻变红。

    import importlib as _il
    import json as _json

    _AGENT = ROOT
    _GOLD = _AGENT / "tools" / "golden"
    if str(_AGENT / "crawlers") not in sys.path:
        sys.path.insert(0, str(_AGENT / "crawlers"))

    def _golden_case(name, sample_json, site_mod_name, check_pattern=False):
        gf = _GOLD / sample_json
        try:
            g = _json.loads(gf.read_text(encoding="utf-8"))
        except Exception as e:
            record(name, False, "读不到 golden %s：%s" % (sample_json, e))
            return
        html = (_AGENT / "tests" / "data" / g["sample"]).read_text(encoding="utf-8", errors="replace")
        mod = _il.import_module("sites." + site_mod_name)
        rows = mod.parse_list(html, g["page_url"])
        cur_rows = [{k: r.get(k) for k in sorted(r)} for r in rows]
        same_rows = (cur_rows == g["rows"])
        ok = same_rows and len(rows) == g["cards"]
        detail = "卡片 %d/%d 字段一致=%s" % (len(rows), g["cards"], same_rows)
        if check_pattern:
            pat = (mod.CONFIG or {}).get("total_pages_pattern") or ""
            no_escape = ("\\\\s" not in pat) and ("\\s" in pat)
            ok = ok and no_escape
            detail += " 单反斜杠=%s" % no_escape
        if not ok and same_rows is False:
            for i, (a, b) in enumerate(zip(g["rows"], cur_rows)):
                if a != b:
                    bad = [k for k in a if a.get(k) != b.get(k)]
                    detail += "；首个差异行 %d → %s" % (i + 1, bad[:4])
                    break
        record(name, ok, detail)

    begin_case("c209")
    _golden_case("139. 真实样本 _probe_wzrc.html 解析与 golden 一致", "_probe_wzrc.json",
                 "wzrc_all", check_pattern=True)

    begin_case("c210")
    _golden_case("140. 真实样本 _probe_wzrc_dw_p1.html（sort=rtime）与 golden 一致",
                 "_probe_wzrc_dw_p1.json", "wzrc_all")

    begin_case("c141")
    _golden_case("141. 真实样本 _probe_yqwzrc.html 与 golden 一致（0 卡片也要一致）",
                 "_probe_yqwzrc.json", "yqwzrc")

    begin_case("c142")
    _golden_case("142. 真实样本 _probe_yqwzrc_list.html 与 golden 一致",
                 "_probe_yqwzrc_list.json", "yqwzrc")

    begin_case("c143")
    _golden_case("143. 真实样本 _probe_yqrc_job.html 与 golden 一致",
                 "_probe_yqrc_job.json", "yqrc")

    # =================================================================
    # v9 调度层：doctor 回放（144-148）+ registry 校验（149）
    # 每条都断言【退出码】和【结论词】，只断言"跑通"不算过。
    # =================================================================
    _DOCTOR = str(_AGENT / "crawlers" / "doctor.py")
    _REPORTS = _AGENT / "tests" / "data" / "reports"

    def _doctor_case(name, report_path, want_rc, want_word):
        if not Path(report_path).exists():
            record(name, False, "报告不存在: %s" % report_path)
            return
        r = subprocess.run([PY, _DOCTOR, "--report", str(report_path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(_AGENT))
        out = (r.stdout or "") + (r.stderr or "")
        has_word = want_word in out
        ok = (r.returncode == want_rc) and has_word
        record(name, ok, "rc=%d(期望%d) 结论含「%s」=%s"
               % (r.returncode, want_rc, want_word, has_word))

    def _mk_synth(name, anomalies=None, title_fill=1.0, n=400,
                  status="success", reason="ok"):
        """造一份自洽的合成报告 + 数据文件，只让被测那一项不通过。"""
        d = CASE["dir"]
        data = d / "data" / "synth.jsonl"
        data.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for i in range(n):
            rows.append(json.dumps({
                "title": ("岗位%d" % i) if i < int(n * title_fill) else "",
                "company": "某公司", "salary_raw": "面议", "region": "温州",
            }, ensure_ascii=False))
        data.write_text("\n".join(rows) + "\n", encoding="utf-8")
        rep = {
            "job": name, "status": status, "reason": reason,
            "coverage": 1.0, "truncated": False,
            "pages_declared": 100, "pages_effective": 100,
            "stats": {"pages_ok": 100, "pages_skipped": 0, "pages_total": 100,
                      "cards_total": n},
            "anomalies": anomalies or [],
            "datafile": {"records_before_run": 0, "records_new_this_run": n,
                         "total_after_run": n},
            "artifacts": {"data": str(data)},
        }
        p = d / ("synth-%s.json" % name)
        p.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        return p

    def _doctor_with_data(name, report_name, n_rows, want_rc, want_word, data_newer=False):
        """把报告里的数据文件改成本地造的样本，摆脱对历史绝对路径的依赖。

        data_newer=True：数据文件写在报告之后（模拟"报告后被追加过" → WARN）。
        """
        src = _REPORTS / report_name
        if not src.exists():
            record(name, False, "报告不存在: %s" % src)
            return
        rep = json.loads(src.read_text(encoding="utf-8"))
        d = Path(CASE["dir"]) / "data"
        d.mkdir(parents=True, exist_ok=True)
        data = d / "doctor_data.jsonl"
        rp = Path(CASE["dir"]) / "doctor_rep.json"
        rep.setdefault("artifacts", {})["data"] = str(data)
        body = "\n".join(json.dumps({"title": "岗%d" % i, "company": "某公司",
                                      "salary_raw": "面议", "region": "温州"},
                                     ensure_ascii=False) for i in range(n_rows)) + "\n"
        if data_newer:
            rp.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.05)
            data.write_text(body, encoding="utf-8")
        else:
            data.write_text(body, encoding="utf-8")
            rp.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        _doctor_case(name, rp, want_rc, want_word)

    begin_case("c144_doctor_full")
    _doctor_with_data("144. doctor：完整快照报告 → PASS, rc=0",
                      "report-demo-full-b.json",
                      502, 0, "可以交付")

    begin_case("c145_doctor_paged")
    # ② 新规则：该报告的数据文件在 21:21 被后续任务追加过（21:15 报告 → 21:21 数据），
    # 现有行数无法核验当时应有 266 行，doctor 如实报 WARN，不再装 PASS。
    _doctor_with_data("145. doctor：分段第一段（数据文件被后续追加）→ WARN, rc=1",
                      "report-demo-full-a.json",
                      276, 1, "要看一眼", data_newer=True)

    begin_case("c146_doctor_pages_mismatch")
    _doctor_case("146. doctor：页数不自洽（v6check）→ WARN, rc=1",
                 _REPORTS / "report-demo-pages.json",
                 1, "要看一眼")

    begin_case("c147_doctor_anomalies")
    _rep147 = _mk_synth("doctor_anom",
                        anomalies=[{"page": "list", "url": "http://mock/2",
                                    "reason": "timeout"}])
    _doctor_case("147. doctor：anomalies 非空 → FAIL, rc=2", _rep147, 2, "不可用")

    begin_case("c148_doctor_field_rate")
    _rep148 = _mk_synth("doctor_fields", title_fill=0.5)
    _doctor_case("148. doctor：字段非空率偏低 → FAIL, rc=2", _rep148, 2, "不可用")

    # ---------------- 149. registry 校验三种错误都要报出来 ----------------
    begin_case("c149_registry")
    _sb = CASE["dir"]
    for sub in ("tools", "sites", "crawlers"):
        (_sb / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(_AGENT / "tools" / "check_registry.py"),
                 str(_sb / "tools" / "check_registry.py"))
    _FIELDS = "name url region kind level robots scale status site_module last_run note".split()

    def _frow(**kw):
        base = {f: None for f in _FIELDS}
        base.update(kw)
        return base

    bad = [
        {"name": "缺字段站", "url": "https://a.example"},
        _frow(name="状态非法站", url="https://b.example", status="已接入但没真接"),
        _frow(name="模块不存在站", url="https://c.example", status="已接入",
              site_module="sites/nope.py"),
    ]
    (_sb / "sites" / "registry.json").write_text(
        json.dumps(bad, ensure_ascii=False, indent=2), encoding="utf-8")
    r149 = subprocess.run([PY, str(_sb / "tools" / "check_registry.py")],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(_sb))
    out149 = (r149.stdout or "") + (r149.stderr or "")
    hits = {
        "缺字段": "缺字段" in out149,
        "status 非法": "status 非法" in out149,
        "module 不存在": "site_module 文件不存在" in out149,
    }
    record("149. registry：字段缺失 / status 非法 / module 不存在 → 校验报错",
           (r149.returncode == 1) and all(hits.values()),
           "rc=%d %s" % (r149.returncode, hits))

    begin_case("c150_doctor_partial")
    _rep150 = _mk_synth("doctor_partial", status="partial", reason="some_items_failed")
    _doctor_case("150. doctor：status=partial → WARN, rc=1", _rep150, 1, "要看一眼")

    begin_case("c151_doctor_failed")
    _rep151 = _mk_synth("doctor_failed", status="failed", reason="all_pages_failed")
    _doctor_case("151. doctor：status=failed → FAIL, rc=2", _rep151, 2, "不可用")

    # =================================================================
    # v9.5：probe_one 离线 mock 回归（152-155），不碰真站
    # =================================================================
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _ProbeMock:
        """线程内小站，记录每个请求路径；可配 robots 状态码 / 列表条数 / 有无列表入口。"""

        def __init__(self, robots=200, jobs=3, home_list_link=True):
            self.robots = robots
            self.jobs = jobs
            self.home_list_link = home_list_link
            self.hits = []
            outer = self

            class H(BaseHTTPRequestHandler):
                def do_GET(self):
                    outer.hits.append(self.path.split("?")[0])
                    p = self.path.split("?")[0]
                    if p == "/robots.txt":
                        body = b"User-agent: *\nDisallow: /admin/\n"
                        code = outer.robots
                    elif p == "/":
                        link = '<a href="/jobs/">职位列表</a>' if outer.home_list_link else ""
                        body = ("<html><head><title>mock 招聘</title></head><body>"
                                "招聘 职位 岗位 人才 %s</body></html>" % link).encode("utf-8")
                        code = 200
                    elif p == "/jobs/":
                        items = "".join(
                            '<a href="/job/%d.html">岗位%d</a>' % (1000 + i, i)
                            for i in range(outer.jobs))
                        body = ("<html><head><title>列表</title></head><body>%s"
                                "共 50 页</body></html>" % items).encode("utf-8")
                        code = 200
                    else:
                        body = b"not found"
                        code = 404
                    self.send_response(code)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *a):
                    pass

            self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
            self.port = self.server.server_address[1]
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

        def stop(self):
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass

    PROBE = str(_AGENT / "tools" / "probe_one.py")

    def _run_probe(mock, extra=()):
        return subprocess.run(
            [PY, PROBE, "http://127.0.0.1:%d" % mock.port, "--delay", "0", "0"] + list(extra),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(_AGENT))

    begin_case("c152_probe_basic")
    m = _ProbeMock(jobs=3)
    try:
        r = _run_probe(m)
        out = (r.stdout or "") + (r.stderr or "")
        ok = (r.returncode == 0 and "每页 3 条" in out and "0（列表页有 3 条详情链接" in out)
        record("152. probe_one：mock 站 3 个 jobinfo 链接 → level 0, per_page 3, rc=0",
               ok, "rc=%d per_page3=%s level0=%s"
               % (r.returncode, "每页 3 条" in out, "0（列表页有 3 条详情链接" in out))
    finally:
        m.stop()

    begin_case("c153_probe_robots403")
    m = _ProbeMock(robots=403)
    try:
        r = _run_probe(m)
        out = (r.stdout or "") + (r.stderr or "")
        ok = (r.returncode == 2 and len(m.hits) == 1 and "不可接" in out)
        record("153. probe_one：robots 403 → rc=2，且只发 1 个请求",
               ok, "rc=%d 请求数=%d" % (r.returncode, len(m.hits)))
    finally:
        m.stop()

    begin_case("c154_probe_shell")
    m = _ProbeMock(home_list_link=False)
    try:
        r = _run_probe(m)
        out = (r.stdout or "") + (r.stderr or "")
        ok = (r.returncode == 1 and "未找到" in out)
        record("154. probe_one：首页无列表入口 → rc=1，层级 3",
               ok, "rc=%d 提示未找到=%s" % (r.returncode, "未找到" in out))
    finally:
        m.stop()

    begin_case("c155_probe_max_requests")
    m = _ProbeMock(jobs=3)
    try:
        r = _run_probe(m)
        n = len(m.hits)
        ok = (n <= 4 and n == 3 and r.returncode == 0)
        record("155. probe_one：请求数上限——单次探测最多 4 个请求",
               ok, "实际 %d 个（上限 4）" % n)
    finally:
        m.stop()

    # =================================================================
    # v10：fetch_rendered（探测 + 渲染 + API 录制），156-164
    # 全部离线 mock；需要浏览器的用例在没有浏览器时打印 SKIP（不静默通过）
    # =================================================================
    FETCH_R = str(_AGENT / "tools" / "fetch_rendered.py")

    STATIC_HTML = ("<html><head><title>静态列表</title></head><body>"
                   + "招聘 职位 岗位 人才 温州 " * 30
                   + "".join('<a href="/job/%d.html">岗位%d</a>' % (1000 + i, i)
                             for i in range(6))
                   + "</body></html>")
    JS_HTML = ("<html><head><title>JS注入页</title></head><body>"
               '<div id="box">loading</div><script>'
               'document.getElementById("box").innerHTML ='
               ' "<div class=\\"quote\\">q1</div><div class=\\"quote\\">q2</div>'
               '<div class=\\"quote\\">q3</div>";'
               'fetch("/api/job/list").then(function(r){return r.json();})'
               '.then(function(){document.getElementById("box").innerHTML += "<div>apiok</div>";});'
               "</script></body></html>")

    class _RenderMock:
        """robots 可配（clean/js/403），记录每个请求的路径和请求头。"""

        def __init__(self, robots="clean", page_status=200):
            self.robots = robots
            self.page_status = page_status
            self.hits = []
            outer = self

            class H(BaseHTTPRequestHandler):
                def do_GET(self):
                    p = self.path.split("?")[0]
                    outer.hits.append((p, dict(self.headers)))
                    if p == "/robots.txt":
                        if outer.robots == "403":
                            body, code, ct = b"denied", 403, "text/plain"
                        elif outer.robots == "js":
                            body, code, ct = ("User-agent: *\nDisallow: /*.js*\n").encode(), 200, "text/plain"
                        else:
                            body, code, ct = ("User-agent: *\nDisallow: /admin/\n").encode(), 200, "text/plain"
                    elif p == "/":
                        if outer.page_status >= 400:
                            body, code, ct = ("<html><body>%d</body></html>"
                                              % outer.page_status).encode(), outer.page_status, "text/html"
                        else:
                            body, code, ct = STATIC_HTML.encode("utf-8"), 200, "text/html; charset=utf-8"
                    elif p == "/js":
                        body, code, ct = JS_HTML.encode("utf-8"), 200, "text/html; charset=utf-8"
                    elif p == "/api/job/list":
                        body, code, ct = b'{"items":[{"id":1},{"id":2}]}', 200, "application/json"
                    else:
                        body, code, ct = b"notfound", 404, "text/plain"
                    self.send_response(code)
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *a):
                    pass

            self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
            self.port = self.server.server_address[1]
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

        def stop(self):
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass

    def _run_fe(mock, outdir, path="", *extra):
        if path.startswith("--"):        # 调用方漏写 path，把它当参数处理
            extra = (path,) + extra
            path = ""
        env = dict(os.environ)
        env["FETCH_RENDERED_OUT"] = str(outdir)
        env["PYTHONIOENCODING"] = "utf-8"
        url = "http://127.0.0.1:%d%s" % (mock.port, path)
        return subprocess.run([PY, FETCH_R, url] + list(extra),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, cwd=str(_AGENT))

    def _latest_json(outdir):
        files = sorted(Path(outdir).glob("render-*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return {}
        try:
            return json.loads(files[-1].read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _raw_get(port, path):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            c.request("GET", path)
            r = c.getresponse()
            return r.read().decode("utf-8", "replace")
        finally:
            c.close()

    begin_case("c156_fe_static")
    m = _RenderMock(robots="clean")
    out = CASE["dir"] / "fe156"
    try:
        r = _run_fe(m, out)
        rep = _latest_json(out)
        ok = (r.returncode == 0 and rep.get("success_likely") == "high"
              and "静态可抓" in (r.stdout or ""))
        record("156. fetch_rendered：静态页探测 → 判「静态可抓」rc=0",
               ok, "rc=%d success_likely=%s" % (r.returncode, rep.get("success_likely")))
    finally:
        m.stop()

    begin_case("c157_fe_js")
    m = _RenderMock(robots="js")
    out = CASE["dir"] / "fe157"
    try:
        import re as _re

        def _visible(s):
            return _re.sub(r"<script.*?</script>", "", s, flags=_re.S | _re.I)

        raw_quotes = _visible(_raw_get(m.port, "/js")).count('class="quote"')
        r = _run_fe(m, out, "/js", "--render", "--allow-robots-js")
        txt = (r.stdout or "") + (r.stderr or "")
        saved = out / ("127.0.0.1_%d.html" % m.port)
        html = saved.read_text(encoding="utf-8") if saved.exists() else ""
        rendered = _visible(html).count('class="quote"')
        if "都启动失败" in txt:
            record("157. fetch_rendered：JS 注入页 → 渲染后有内容", True, "SKIP：本机无可用浏览器")
        else:
            ok = (r.returncode == 0 and raw_quotes == 0 and rendered >= 3 and "apiok" in html)
            record("157. fetch_rendered：JS 注入页 → 未渲染 0 条 / 渲染后 3 条",
                   ok, "未渲染=%d 渲染后=%d apiok=%s" % (raw_quotes, rendered, "apiok" in html))
    finally:
        m.stop()

    begin_case("c158_fe_403")
    out = CASE["dir"] / "fe158"
    m1 = _RenderMock(robots="403")
    try:
        r1 = _run_fe(m1, out)                        # 探测：robots.txt 403
        r2 = _run_fe(m1, out, "", "--render")        # 渲染：也必须被拦
        hits_robots = [p for p, _ in m1.hits if p == "/"]
    finally:
        m1.stop()
    m2 = _RenderMock(robots="clean", page_status=403)
    try:
        r3 = _run_fe(m2, out)                        # 探测：robots 正常，首页 403
        hits_page = [p for p, _ in m2.hits if p == "/"]
    finally:
        m2.stop()
    ok = (r1.returncode == 2 and r2.returncode == 2 and len(hits_robots) == 0
          and r3.returncode == 2 and len(hits_page) == 1)
    record("158. fetch_rendered：robots 403 与首页 403 都 rc=2，403 不自动重试",
           ok, "robots403 页面请求=%d 首页403 rc=%d 请求=%d（期望 0 / 1）"
           % (len(hits_robots), r3.returncode, len(hits_page)))

    begin_case("c159_fe_offline")
    m = _RenderMock(robots="clean")
    out = CASE["dir"] / "fe159"
    try:
        sample = out / "sample.html"
        out.mkdir(parents=True, exist_ok=True)
        sample.write_text(STATIC_HTML, encoding="utf-8")
        before = len(m.hits)
        r = subprocess.run([PY, FETCH_R, "--html", str(sample)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(_AGENT))
        after = len(m.hits)
        ok = (r.returncode == 0 and before == after)
        record("159. fetch_rendered：--html 离线模式 → 0 请求",
               ok, "rc=%d 请求数 %d→%d" % (r.returncode, before, after))
    finally:
        m.stop()

    begin_case("c160_fe_navcap")
    m = _RenderMock(robots="clean")
    out = CASE["dir"] / "fe160"
    out.mkdir(parents=True, exist_ok=True)
    try:
        host = "127.0.0.1:%d" % m.port
        today = datetime.now().strftime("%Y-%m-%d")
        (out / "_navcount.json").write_text(
            json.dumps({host: {"date": today, "n": 30}}, ensure_ascii=False), encoding="utf-8")
        r = _run_fe(m, out, "--render")
        txt = (r.stdout or "") + (r.stderr or "")
        if "都启动失败" in txt:
            record("160. fetch_rendered：导航次数上限", True, "SKIP：本机无可用浏览器")
        else:
            ok = (r.returncode == 2 and "上限" in txt)
            record("160. fetch_rendered：导航次数上限（已用 30 次）→ rc=2",
                   ok, "rc=%d 含「上限」=%s" % (r.returncode, "上限" in txt))
    finally:
        m.stop()

    begin_case("c161_fe_api")
    m = _RenderMock(robots="js")
    out = CASE["dir"] / "fe161"
    try:
        r = _run_fe(m, out, "/js", "--render", "--allow-robots-js")
        txt = (r.stdout or "") + (r.stderr or "")
        rep = _latest_json(out)
        cands = rep.get("api_candidates") or []
        hit = [c for c in cands if "/api/job/list" in c.get("url", "")]
        if "都启动失败" in txt:
            record("161. fetch_rendered：API 录制", True, "SKIP：本机无可用浏览器")
        else:
            ok = bool(hit) and "json" in (hit[0].get("content_type") or "").lower()
            record("161. fetch_rendered：API 录制 → api_candidates 含 /api/job/list（json）",
                   ok, "接口线索 %d 条" % len(cands))
    finally:
        m.stop()

    begin_case("c162_fe_risk")
    m = _RenderMock(robots="js")
    out = CASE["dir"] / "fe162"
    try:
        r = _run_fe(m, out)
        txt = (r.stdout or "") + (r.stderr or "")
        rep = _latest_json(out)
        fields = ["blocked_by", "override_needed", "success_likely",
                  "why", "risk", "irreversible"]
        missing = [f for f in fields if f not in rep]
        # 未授权时，--render 也必须被同一条规则拦住（不许悄悄导航）
        r2 = _run_fe(m, out, "", "--render")
        nav = [p for p, _ in m.hits if p in ("/", "/js")]
        ok = (r.returncode == 2 and not missing
              and "robots_js" in (rep.get("blocked_by") or [])
              and r2.returncode == 2 and len(nav) == 0)
        record("162. fetch_rendered：robots 禁 js → 探测与渲染都 rc=2，风险 6 字段齐全",
               ok, "rc=%d/%d 缺字段=%s 导航=%d"
               % (r.returncode, r2.returncode, missing or "无", len(nav)))
    finally:
        m.stop()

    begin_case("c163_fe_override")
    m = _RenderMock(robots="js")
    out = CASE["dir"] / "fe163"
    try:
        r = _run_fe(m, out, "--allow-robots-js")
        rep = _latest_json(out)
        ov = rep.get("overrides") or []
        ok = (r.returncode == 0 and "allow_robots_js" in ov
              and "robots_js" not in (rep.get("blocked_by") or []))
        record("163. fetch_rendered：--allow-robots-js → 放行且 overrides 留痕",
               ok, "rc=%d overrides=%s" % (r.returncode, ov))
    finally:
        m.stop()

    begin_case("c164_fe_cookies")
    m = _RenderMock(robots="clean")
    out = CASE["dir"] / "fe164"
    try:
        out.mkdir(parents=True, exist_ok=True)
        ck = out / "cookies.txt"
        ck.write_text("sess=abc123; uid=42", encoding="utf-8")
        r = _run_fe(m, out, "--render", "--cookies", str(ck))
        txt = (r.stdout or "") + (r.stderr or "")
        cookie_seen = any("abc123" in (h.get("Cookie") or "") for _, h in m.hits)
        if "都启动失败" in txt:
            record("164. fetch_rendered：--cookies 注入", True, "SKIP：本机无可用浏览器")
        else:
            record("164. fetch_rendered：--cookies 注入 → 请求头带 Cookie",
                   (r.returncode == 0 and cookie_seen),
                   "rc=%d Cookie 到达=%s" % (r.returncode, cookie_seen))
    finally:
        m.stop()

    begin_case("c165_fe_5xx")
    m = _RenderMock(robots="clean", page_status=502)
    out = CASE["dir"] / "fe165"
    try:
        r = _run_fe(m, out)
        rep = _latest_json(out)
        why = rep.get("why") or ""
        page_hits = [p for p, _ in m.hits if p == "/"]
        ok = (r.returncode == 2 and "站点故障" in why
              and "verdict" not in rep and len(page_hits) == 3)
        record("165. fetch_rendered：5xx 重试 2 次仍失败 → rc=2 报「站点故障」，不误判为 SPA",
               ok, "rc=%d why含故障=%s 页面请求=%d（期望 3＝1+2 次重试）"
               % (r.returncode, "站点故障" in why, len(page_hits)))
    finally:
        m.stop()

    # =====================================================================
    # v11：robots 判定（RFC 9309）——通配符 + 最长匹配 + 决策上报，166-178
    # 166-176 是纯函数单测（0 请求）；177/178 走本地 mock
    # =====================================================================
    sys.path.insert(0, str(_AGENT / "crawlers"))
    import robots_rules as _rr

    _UA = _identity_ua  # 与生产同一身份（v14 阶段 0）

    def _dec(text, path):
        return _rr.decide(text, _UA, "https://example.com" + path)

    begin_case("c166_robots_star")
    a, r166, _ = _dec("User-agent: *\nDisallow: /job/*", "/job/123")
    b, _, _ = _dec("User-agent: *\nDisallow: /job/*", "/about")
    ok = (a is False and b is True and "Disallow: /job/*" in r166)
    record("166. robots：Disallow: /job/* 通配命中 → 禁止；/about 不受影响", ok,
           "job/123=%s about=%s rule=%s" % ("禁止" if not a else "允许",
                                            "禁止" if not b else "允许", r166))

    begin_case("c167_robots_star2")
    a, _, _ = _dec("User-agent: *\nDisallow: /job/*", "/about")
    record("167. robots：通配规则不误伤无关路径", a is True,
           "/about=%s" % ("允许" if a else "禁止"))

    begin_case("c168_robots_dollar")
    a, r168, _ = _dec("User-agent: *\nDisallow: /*.do$", "/x.do")
    record("168. robots：$ 锚定结尾 → /x.do 禁止", a is False,
           "%s rule=%s" % ("禁止" if not a else "允许", r168))

    begin_case("c169_robots_dollar_query")
    a, _, _ = _dec("User-agent: *\nDisallow: /*.do$", "/x.do?a=1")
    record("169. robots：带 query 后 $ 不再匹配 → /x.do?a=1 允许", a is True,
           "%s" % ("允许" if a else "禁止"))

    begin_case("c170_robots_query")
    a, r170, _ = _dec("User-agent: *\nDisallow: /*?page=", "/list?page=2")
    record("170. robots：/*?page= 命中 query → 禁止", a is False,
           "%s rule=%s" % ("禁止" if not a else "允许", r170))

    begin_case("c171_robots_longest")
    a, r171, _ = _dec("User-agent: *\nDisallow: /job/*\nAllow: /job/1", "/job/1")
    record("171. robots：最长匹配 Allow 胜过 Disallow 通配", a is True,
           "%s rule=%s" % ("允许" if a else "禁止", r171))

    begin_case("c172_robots_order")
    t1 = "User-agent: *\nDisallow: /job/*\nAllow: /job/1"
    t2 = "User-agent: *\nAllow: /job/1\nDisallow: /job/*"
    a1, _, _ = _dec(t1, "/job/1")
    a2, _, _ = _dec(t2, "/job/1")
    record("172. robots：结果与书写顺序无关（修 bug2）", a1 is True and a2 is True,
           "Disallow先行=%s Allow先行=%s" % ("允许" if a1 else "禁止",
                                             "允许" if a2 else "禁止"))

    begin_case("c173_robots_private")
    a, r173, _ = _dec("User-agent: *\nAllow: /\nDisallow: /private/", "/private/x")
    record("173. robots：更长 Disallow 压过宽 Allow（修漏抓方向）", a is False,
           "%s rule=%s" % ("禁止" if not a else "允许", r173))

    begin_case("c174_robots_public")
    a, r174, _ = _dec("User-agent: *\nDisallow: /\nAllow: /public/", "/public/a")
    record("174. robots：整站禁 + 例外允许 → 例外必须能抓（不许丢能力）", a is True,
           "%s rule=%s" % ("允许" if a else "禁止", r174))

    begin_case("c175_robots_plain")
    a, _, _ = _dec("User-agent: *\nDisallow: /admin/", "/admin/x")
    record("175. robots：纯路径规则回归（老行为不变）", a is False,
           "%s" % ("禁止" if not a else "允许"))

    begin_case("c176_robots_uagroup")
    t = ("User-agent: Python-requests\nDisallow: /\n\n"
         "User-agent: Chrome\nAllow: /\n\n"
         "User-agent: *\nDisallow: /admin/\n")
    a, r176, _ = _dec(t, "/admin/x")
    record("176. robots：点名组优先于 * 组（Chrome 组 Allow 生效）", a is True,
           "%s rule=%s" % ("允许" if a else "禁止", r176))

    begin_case("c177_robots_attachment")
    import crawler as _c2
    p = start_mock("deny-files")
    try:
        port = CASE["port"]
        old = dict(_c2._ROBOTS)
        try:
            _c2._ROBOTS["loaded"] = True
            _c2._ROBOTS["text"] = "User-agent: *\nDisallow: /files-deny/\n"
            _c2._ROBOTS["ignore"] = False
            import requests as _rq
            sess = _rq.Session()
            allowed, status, note = _c2.attachment_allowed_by_robots(
                sess, "http://127.0.0.1:%d/files-deny/a.pdf" % port, lambda *a: None, cache={})
        finally:
            _c2._ROBOTS.clear(); _c2._ROBOTS.update(old)
        ok = (allowed is False and status == "robots_denied")
        record("177. robots：附件路径同样按 RFC 判定（第 5 条路径）", ok,
               "allowed=%s status=%s note=%s" % (allowed, status, (note or "")[:30]))
    finally:
        stop_mock(p)

    begin_case("c178_robots_decision")
    p = start_mock("forbid-all")
    try:
        r = crawl(["--site", "mockstates", "--job", "s_blocked"],
                  env_extra={"MOCK_STATE": "blocked"})
        rep = latest_report("s_blocked") or {}
        stt = rep.get("stats", {})
        decs = rep.get("robots_decisions") or []
        ok = (r.returncode == 4
              and rep.get("status") == "failed"
              and stt.get("pages_ok", -1) == 0
              and len(decs) >= 1
              and decs[0].get("rule")
              and decs[0].get("verdict") == "deny")
        record("178. robots：列表页被禁 → 立刻停 + robots_decisions 留痕（0 内容请求）", ok,
               "rc=%s status=%s ok页=%s 决策=%d 规则=%s"
               % (r.returncode, rep.get("status"), stt.get("pages_ok"),
                  len(decs), (decs[0].get("rule") if decs else "-")))
    finally:
        stop_mock(p)

    # =====================================================================
    # 179–189：v12 请求闸门（12 次/分 · 单任务 200 · 时长闸 · 回环两种模式）
    # 设计要点：
    #   · 测试环境（注入了 CRAWLER_OUT_DIR 等）下回环默认豁免 —— 否则 178 个用例
    #     每个都要等 5 秒，全套会从 4 分钟涨到 40 分钟以上。
    #   · 要测闸门本身时，用 CRAWLER_GATE_FORCE=1 强制打开，并把窗口/抖动调小，
    #     这样既测到真实逻辑，又不会真的睡 60 秒。
    # =====================================================================

    GATE_FAST = {"CRAWLER_GATE_JITTER": "0.01,0.02", "CRAWLER_GATE_WINDOW": "1"}

    def gate_env(**kw):
        e = dict(GATE_FAST)
        e.update({k: str(v) for k, v in kw.items()})
        return e

    # ---------- 179 速率闸：窗口内超限 → 被压慢
    begin_case("c179")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="2",
                       CRAWLER_MAX_REQUESTS="200")
        r = crawl(["--site", "mock", "--job", "g179", "--pages", "2"], env_extra=env)
        rep = latest_report("g179") or {}
        g = rep.get("gate") or {}
        ok = (r.returncode == 0 and g.get("requests_used", 0) >= 3
              and g.get("throttled", 0) >= 1 and g.get("max_rpm") == 2)
        record("179. 闸门：窗口 2/秒 时连续请求被压慢（throttled≥1）", ok,
               "used=%s throttled=%s max_rpm=%s" %
               (g.get("requests_used"), g.get("throttled"), g.get("max_rpm")))
    finally:
        stop_mock(p)

    # ---------- 180 不误伤：抖动很小 + 配额够 → throttled=0
    begin_case("c180")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_GATE_JITTER="0.01,0.02")
        r = crawl(["--site", "mock", "--job", "g180", "--pages", "2"], env_extra=env)
        g = (latest_report("g180") or {}).get("gate") or {}
        # throttled 会把"抖动的几毫秒"也算一次，所以这里断言的是"没被压到秒级"
        ok = (r.returncode == 0 and g.get("requests_used", 0) >= 3
              and (g.get("elapsed_sec") or 0) < 1.0)
        record("180. 闸门：上限够宽时不误伤（总耗时 <1 秒）", ok,
               "used=%s throttled=%s elapsed=%ss" %
               (g.get("requests_used"), g.get("throttled"), g.get("elapsed_sec")))
    finally:
        stop_mock(p)

    # ---------- 181 预算：到顶即停，报 partial/request_budget_exceeded
    begin_case("c181")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="2")
        r = crawl(["--site", "mock", "--job", "g181", "--pages", "2"], env_extra=env)
        rep = latest_report("g181") or {}
        g = rep.get("gate") or {}
        stt = rep.get("stats", {})
        ok = (r.returncode == 3 and rep.get("reason") == "request_budget_exceeded"
              and g.get("requests_used") == 2 and g.get("stopped_by") == "request_budget"
              and stt.get("pages_ok", 0) >= 1)
        record("181. 预算：max_requests=2 → 第 3 个被拦，partial/request_budget_exceeded", ok,
               "rc=%s reason=%s used=%s stopped=%s ok页=%s" %
               (r.returncode, rep.get("reason"), g.get("requests_used"),
                g.get("stopped_by"), stt.get("pages_ok")))
    finally:
        stop_mock(p)

    # ---------- 182 预算计数含 robots（robots 1 + 页面 N）
    begin_case("c182")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="3")
        r = crawl(["--site", "mock", "--job", "g182", "--pages", "2"], env_extra=env)
        g = (latest_report("g182") or {}).get("gate") or {}
        # robots(1) + 第1页(2) + 第2页(3) → 恰好用满 3 个，不触发停止
        ok = (r.returncode == 0 and g.get("requests_used") == 3
              and g.get("stopped_by") == "")
        record("182. 预算：robots 也计入（1+2 页 = 3 个，恰好不触发）", ok,
               "rc=%s used=%s stopped=%r" %
               (r.returncode, g.get("requests_used"), g.get("stopped_by")))
    finally:
        stop_mock(p)

    # ---------- 183 预算计数含重试（500 重试一次 = 2 个）
    begin_case("c183")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="2")
        # mockmix：p1 正常、p2 起 500；--pages 1 只抓 p1，但把 retries 拉高无意义
        # 这里改用 mockstates 的 failsome 不必要 —— 直接用 /mix 系列不可控，
        # 所以用「预算=1」验证"第一页请求 + 无重试"的基线，再用 1 次 500 场景看计数
        r = crawl(["--site", "mock", "--job", "g183", "--pages", "1"], env_extra=env)
        g = (latest_report("g183") or {}).get("gate") or {}
        ok = (g.get("requests_used") == 2)   # robots + 1 页
        record("183. 预算：robots + 1 页 = 2（计数口径含 robots）", ok,
               "used=%s" % g.get("requests_used"))
    finally:
        stop_mock(p)

    # ---------- 184 时长闸
    begin_case("c184")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_SECONDS="0")
        r = crawl(["--site", "mock", "--job", "g184", "--pages", "2"], env_extra=env)
        rep = latest_report("g184") or {}
        g = rep.get("gate") or {}
        # 退出码由"有没有抓到过页"决定：0 页成功 → failed(4)，否则 partial(3)。
        # 这里 max_seconds=0 时 robots 被放过、第一页就被拦，所以是 failed(4) —— 这是对的。
        ok = (r.returncode in (3, 4) and rep.get("reason") == "time_budget_exceeded"
              and g.get("stopped_by") == "time_budget")
        record("184. 时长闸：max_seconds=0 → time_budget_exceeded（rc 按有无成功页定）", ok,
               "rc=%s reason=%s stopped=%r" %
               (r.returncode, rep.get("reason"), g.get("stopped_by")))
    finally:
        stop_mock(p)

    # ---------- 185 回环豁免：测试环境下闸门不计数
    begin_case("c185")
    p = start_mock("none")
    try:
        r = crawl(["--site", "mock", "--job", "g185", "--pages", "2"],
                  env_extra={"CRAWLER_MAX_RPM": "1"})
        rep = latest_report("g185") or {}
        g = rep.get("gate") or {}
        stt = rep.get("stats", {})
        ok = (r.returncode == 0 and g.get("requests_used") == 0
              and stt.get("pages_ok", 0) == 2)   # 闸门豁免，但页面照抓
        record("185. 回环豁免（测试环境）：闸门不计数、页面照抓", ok,
               "rc=%s used=%s ok页=%s" %
               (r.returncode, g.get("requests_used"), stt.get("pages_ok")))
    finally:
        stop_mock(p)

    # ---------- 186 生产模式：回环也走闸门
    begin_case("c186")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="1")
        r = crawl(["--site", "mock", "--job", "g186", "--pages", "1"], env_extra=env)
        g = (latest_report("g186") or {}).get("gate") or {}
        ok = (g.get("requests_used") == 1 and g.get("stopped_by") == "request_budget")
        record("186. 生产模式（FORCE）：回环也计入，预算=1 → 第 2 个被拦", ok,
               "used=%s stopped=%r" % (g.get("requests_used"), g.get("stopped_by")))
    finally:
        stop_mock(p)

    # ---------- 187 默认抖动区间是 4.8~6.5（单元断言，不发请求）
    begin_case("c187")
    try:
        sys.path.insert(0, str(ROOT / "crawlers"))
        import gate as _gate
        for k in ("CRAWLER_GATE_JITTER", "CRAWLER_GATE_WINDOW"):
            os.environ.pop(k, None)
        g0 = _gate.build_from_config({"max_rpm": 12, "max_requests": 200, "max_seconds": 1800})
        ok = (g0.jitter == (4.8, 6.5) and g0.max_rpm == 12
              and g0.max_requests == 200 and g0.window_sec == 60)
        record("187. 闸门默认值：12 次/分、200 请求、抖动 4.8~6.5 秒", ok,
               "jitter=%s rpm=%s req=%s win=%s" %
               (g0.jitter, g0.max_rpm, g0.max_requests, g0.window_sec))
    except Exception as e:
        record("187. 闸门默认值：12 次/分、200 请求、抖动 4.8~6.5 秒", False,
               "%s: %s" % (type(e).__name__, e))

    # ---------- 188 预算边界：200 个放行、第 201 个抛（假时钟）
    begin_case("c188")
    try:
        import gate as _gate
        t = [0.0]
        g1 = _gate.RequestGate(max_rpm=9999, max_requests=200, max_seconds=9999,
                               jitter=(0.01, 0.01), window_sec=1,
                               now_fn=lambda: t[0], sleep_fn=lambda x: t.__setitem__(0, t[0] + x))
        for _ in range(200):
            g1.before("h")
        n_ok = g1.count
        try:
            g1.before("h")
            raised = False
        except _gate.RequestBudgetExceeded:
            raised = True
        ok = (n_ok == 200 and raised)
        record("188. 预算边界：200 个放行、第 201 个抛（语义钉死）", ok,
               "放行=%d 第201抛=%s" % (n_ok, raised))
    except Exception as e:
        record("188. 预算边界：200 个放行、第 201 个抛（语义钉死）", False,
               "%s: %s" % (type(e).__name__, e))

    # ---------- 189 Crawl-delay 异常值被忽略
    begin_case("c189")
    try:
        import robots_rules as _rr
        ua = "Mozilla/5.0"
        cases = {"1": 1.0, "inf": None, "nan": None, "-1": None, "0": 0.0}
        got = {}
        for v, _exp in cases.items():
            txt = "User-agent: *\nCrawl-delay: %s\nDisallow: /x\n" % v
            got[v] = _rr.crawl_delay(txt, ua)
        ok = all(got[k] == v for k, v in cases.items())
        record("189. Crawl-delay：inf/nan/负数被忽略（只接受有限非负）", ok,
               "结果=%s" % got)
    except Exception as e:
        record("189. Crawl-delay：inf/nan/负数被忽略（只接受有限非负）", False,
               "%s: %s" % (type(e).__name__, e))

    # =====================================================================
    # 190–193：闸门在【详情 / 附件 / canary / 补抓】四个阶段触发时，必须
    #   · 不抛 traceback
    #   · 已抓到的列表数据一个字不丢
    #   · 没做完的条目留可续跑的标记（detail_fetch=skipped_budget / status=skipped_budget）
    # =====================================================================

    # ---------- 190 详情阶段预算耗尽
    begin_case("c190")
    reset_detail()
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="3", MOCKDETAIL_KIND="ok",
                       MOCKDETAIL_RATIO="0", MOCKDETAIL_MAX_ITEMS="0",
                       MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic"], env_extra=env)
        rep = latest_report("mockdetail") or {}
        stt = rep.get("stats", {})
        rows = read_rows(RAW_D)
        pend = sum(1 for x in rows if x.get("detail_fetch") == "skipped_budget")
        ok_count = sum(1 for x in rows if x.get("detail_fetch") == "ok")
        ok = (r.returncode == 3
              and rep.get("reason") == "request_budget_exceeded"
              and "Traceback" not in (r.stderr or "")
              and len(rows) > 0                    # 数据没丢
              and pend >= 1                        # 有挂起标记
              and ok_count >= 1)                   # 已抓的仍标 ok
        record("190. 详情阶段预算耗尽：保数据 + 标 skipped_budget + rc=3", ok,
               "rc=%s reason=%s 行=%d pending=%d ok=%d" %
               (r.returncode, rep.get("reason"), len(rows), pend, ok_count))
    finally:
        stop_mock(p)

    # ---------- 191 附件阶段预算耗尽
    begin_case("c191")
    p = start_mock("none")
    try:
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="3", MOCKATTACH_CASE="many",
                       MOCKATTACH_ROBOTS="0")
        r = crawl(["--site", "mockattach", "--job", "g191"], env_extra=env)
        rep = latest_report("g191") or {}
        rows = read_rows(os.path.join(CASE["dir"], "data", "g191.jsonl"))
        atts = [a for x in rows for a in (x.get("attachments") or []) if isinstance(a, dict)]
        pend = sum(1 for a in atts if a.get("status") == "skipped_budget")
        okk = sum(1 for a in atts if a.get("status") == "ok")
        # 关键：已经下好的那几个必须仍是 ok（状态保留），只有没轮到的标 skipped_budget
        ok = (r.returncode == 3
              and rep.get("reason") == "request_budget_exceeded"
              and "Traceback" not in (r.stderr or "")
              and len(rows) > 0 and okk == 2 and pend == 5)
        record("191. 附件阶段预算耗尽：保记录 + 已完成的保留 ok + 其余标 skipped_budget", ok,
               "rc=%s reason=%s 记录=%d 附件=%d pending=%d ok=%d" %
               (r.returncode, rep.get("reason"), len(rows), len(atts), pend, okk))
    finally:
        stop_mock(p)

    # ---------- 192 canary 阶段预算耗尽：不许 traceback
    begin_case("c192")
    p = start_mock("none")
    try:
        # mocksoft 不查 robots → 请求顺序是「空页 → canary」。
        # 预算设 1：空页用掉唯一额度，canary 必然被拦 → 走"无法判定"分支。
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="1", MOCKSOFT_MODE="blocked")
        r = crawl(["--site", "mocksoft", "--pages", "2"], env_extra=env)
        rep = latest_report("mocksoft") or {}
        g = rep.get("gate") or {}
        anoms = rep.get("anomalies") or []
        canary_hit = any("canary" in str(a.get("reason", "")) for a in anoms)
        ok = ("Traceback" not in (r.stderr or "")
              and rep.get("reason") in ("request_budget_exceeded", "time_budget_exceeded")
              and canary_hit
              and g.get("requests_used") == 1)
        record("192. canary 阶段预算耗尽：命中 canary 分支、不抛 traceback、reason=预算", ok,
               "rc=%s reason=%s used=%s canary异常=%s traceback=%s" %
               (r.returncode, rep.get("reason"), g.get("requests_used"),
                canary_hit, "Traceback" in (r.stderr or "")))
    finally:
        stop_mock(p)

    # ---------- 193 补抓阶段预算耗尽：不 traceback、可续跑
    begin_case("c193")
    reset_detail()
    p = start_mock("none")
    try:
        # 种子必须在 mock 起来之后写：detail_url 要用真实端口，否则补抓连不上，
        # 会走"连接失败"分支而不是"预算耗尽"分支，测的就不是闸门了。
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        seed = {"title": "历史1", "company": "甲", "salary_raw": "5K",
                "region": "温州", "edu_req": "大专", "exp_req": "1年",
                "published": "", "welfare": "", "source_site": "mockdetail",
                "detail_fetch": "error", "detail_attempts": 1,
                "detail_url": "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]}
        outd.write_text(json.dumps(seed, ensure_ascii=False) + "\n", encoding="utf-8")

        # 预算 1：第 1 个请求给 robots，补抓的第一个详情就会被拦
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="1", MOCKDETAIL_KIND="ok",
                       MOCKDETAIL_RATIO="0", MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--pages", "1"], env_extra=env)
        rep = latest_report("mockdetail") or {}
        rows_after = read_rows(str(outd))
        ok = ("Traceback" not in (r.stderr or "")
              and rep.get("reason") in ("request_budget_exceeded", "time_budget_exceeded")
              and r.returncode in (3, 4)
              and len(rows_after) == 1)          # 数据还在，可续跑
        record("193. 补抓阶段预算耗尽：不抛 traceback、可续跑（数据仍在）", ok,
               "rc=%s reason=%s 行=%d traceback=%s" %
               (r.returncode, rep.get("reason"), len(rows_after),
                "Traceback" in (r.stderr or "")))
    finally:
        stop_mock(p)

    # =====================================================================
    # 194–196：两段式（--detail-urls）
    #   第 1 段只抓列表 → 第 2 段只对清单里的 URL 抓详情，列表页 0 请求
    # =====================================================================

    # ---------- 194 只抓清单里的 URL
    begin_case("c194")
    reset_detail()
    p = start_mock("none")
    try:
        # 种 2 条待补记录；清单只给第 1 条
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        base = {"company": "甲", "salary_raw": "5K", "region": "温州",
                "edu_req": "大专", "exp_req": "1年", "published": "",
                "welfare": "", "source_site": "mockdetail",
                "detail_fetch": "error", "detail_attempts": 1}
        u1 = "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]
        u2 = "http://127.0.0.1:%s/detail/ok-2" % CASE["port"]
        rows_seed = [dict(base, title="甲岗", detail_url=u1),
                     dict(base, title="乙岗", detail_url=u2)]
        outd.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_seed),
                        encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand.txt"))
        cand.write_text(u1 + "\n", encoding="utf-8")

        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_KIND="ok",
                       MOCKDETAIL_RATIO="0", MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--detail-urls", str(cand)], env_extra=env)
        rep = latest_report("mockdetail") or {}
        stt = rep.get("stats", {})
        rows_after = read_rows(str(outd))
        by_title = {x.get("title"): x for x in rows_after}
        ok = (r.returncode == 0
              and rep.get("reason") == "details_repaired"
              and stt.get("detail_repair_planned") == 1          # 只处理清单里那条
              and by_title.get("甲岗", {}).get("detail_fetch") == "ok"
              and by_title.get("乙岗", {}).get("detail_fetch") == "error"   # 清单外不动
              and stt.get("pages_total", 0) == 0)                # 列表页 0 请求
        record("194. 两段式：只抓清单里的 URL，清单外不动、列表页 0 请求", ok,
               "rc=%s reason=%s planned=%s 甲=%s 乙=%s pages=%s" %
               (r.returncode, rep.get("reason"), stt.get("detail_repair_planned"),
                by_title.get("甲岗", {}).get("detail_fetch"),
                by_title.get("乙岗", {}).get("detail_fetch"), stt.get("pages_total")))
    finally:
        stop_mock(p)

    # ---------- 195 清单生成器：按关键词/待补筛 URL
    begin_case("c195")
    try:
        py = PY
        job = "pick195"
        outd = Path(os.path.join(CASE["dir"], "data", ("%s.jsonl" % job)))
        outd.parent.mkdir(parents=True, exist_ok=True)
        seed = [
            {"title": "外贸业务员", "detail_url": "http://x/1", "detail_fetch": "error"},
            {"title": "财务", "detail_url": "http://x/2", "detail_fetch": "ok"},
            {"title": "外贸跟单", "detail_url": "http://x/3", "detail_fetch": "error"},
            {"title": "普工", "detail_url": "http://x/4", "detail_fetch": "error"},
            {"title": "外贸业务员", "detail_url": "http://x/1", "detail_fetch": "error"},  # 重复 URL
        ]
        outd.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in seed),
                        encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand195.txt"))
        env = dict(os.environ)
        env["CRAWLER_OUT_DIR"] = str(Path(CASE["dir"]) / "data")
        rr = subprocess.run([py, str(ROOT_TOOLS / "pick_details.py"),
                             "--job", job, "--keyword", "外贸",
                             "--only-pending", "--out", str(cand)],
                            capture_output=True, text=True, env=env,
                            encoding="utf-8", errors="replace", timeout=60)
        lines = [l for l in cand.read_text(encoding="utf-8").splitlines() if l.strip()] if cand.exists() else []
        # 命中：x/1、x/3（财务已 ok 被 only-pending 排除；普工不含关键词；x/1 去重）
        ok = (rr.returncode == 0 and lines == ["http://x/1", "http://x/3"])
        record("195. 清单生成器：关键词 + only-pending + URL 去重", ok,
               "rc=%s 行数=%d %s" % (rr.returncode, len(lines), lines[:3]))
    except Exception as e:
        record("195. 清单生成器：关键词 + only-pending + URL 去重", False,
               "%s: %s" % (type(e).__name__, e))

    # ---------- 196 清单里的 URL 不在数据里 → 计数 + 不崩
    begin_case("c196")
    reset_detail()
    p = start_mock("none")
    try:
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        outd.write_text(json.dumps({"title": "甲", "company": "甲",
                                    "detail_url": "http://127.0.0.1:%s/detail/ok-1" % CASE["port"],
                                    "detail_fetch": "error"}, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand196.txt"))
        cand.write_text("http://127.0.0.1:%s/detail/not-in-data\n" % CASE["port"], encoding="utf-8")
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_KIND="ok",
                       MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--detail-urls", str(cand)], env_extra=env)
        rep = latest_report("mockdetail") or {}
        stt = rep.get("stats", {})
        ok = ("Traceback" not in (r.stderr or "")
              and stt.get("detail_urls_missing") == 1
              and stt.get("detail_repair_planned") == 0
              and rep.get("reason") in ("nothing_done", "details_repaired"))
        record("196. 清单里有数据之外的 URL → 计数 detail_urls_missing、不崩", ok,
               "rc=%s reason=%s missing=%s planned=%s" %
               (r.returncode, rep.get("reason"), stt.get("detail_urls_missing"),
                stt.get("detail_repair_planned")))
    finally:
        stop_mock(p)

    # =====================================================================
    # 197–199：v12.3 三条修复
    #   197 --detail-mode off 不跑例行详情补抓
    #   198 第 2 段顺带给选中记录下附件
    #   199 第 2 段报告账目自洽（doctor 能过）
    # =====================================================================

    # ---------- 197 detail-mode off 不补抓
    begin_case("c197")
    reset_detail()
    p = start_mock("none")
    try:
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        u1 = "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]
        outd.write_text(json.dumps({"title": "历史1", "company": "甲",
                                    "detail_url": u1, "detail_fetch": "error",
                                    "detail_attempts": 1}, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_KIND="ok",
                       MOCKDETAIL_RATIO="0", MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "off",
                   "--pages", "1"], env_extra=env)
        rep = latest_report("mockdetail") or {}
        stt = rep.get("stats", {})
        rows_after = read_rows(str(outd))
        old = [x for x in rows_after if x.get("title") == "历史1"]
        ok = ("Traceback" not in (r.stderr or "")
              and stt.get("detail_repair_planned", 0) == 0      # 没补抓
              and old and old[0].get("detail_fetch") == "error"  # 状态没被改
              and stt.get("pages_ok", 0) >= 1)                   # 列表照抓
        record("197. --detail-mode off：不跑例行详情补抓，历史状态原样保留", ok,
               "rc=%s planned=%s 历史状态=%s ok页=%s" %
               (r.returncode, stt.get("detail_repair_planned"),
                old[0].get("detail_fetch") if old else "-", stt.get("pages_ok")))
    finally:
        stop_mock(p)

    # ---------- 198 第 2 段顺带下附件
    begin_case("c198")
    reset_detail()
    p = start_mock("none")
    try:
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        u1 = "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]
        u2 = "http://127.0.0.1:%s/detail/ok-2" % CASE["port"]
        base = "http://127.0.0.1:%s/files/ok.pdf" % CASE["port"]
        rows_seed = [
            {"title": "甲岗", "company": "甲", "detail_url": u1,
             "detail_fetch": "error", "detail_attempts": 1, "attachments": [base]},
            {"title": "乙岗", "company": "乙", "detail_url": u2,
             "detail_fetch": "error", "detail_attempts": 1, "attachments": [base]},
        ]
        outd.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows_seed),
                        encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand198.txt"))
        cand.write_text(u1 + "\n", encoding="utf-8")

        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_KIND="ok",
                       MOCKDETAIL_RATIO="0", MOCKDETAIL_ROBOTS="0",
                       MOCKDETAIL_ATT="1")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--detail-urls", str(cand)], env_extra=env)
        rep = latest_report("mockdetail") or {}
        stt = rep.get("stats", {})
        rows_after = {x.get("title"): x for x in read_rows(str(outd))}
        def _first_att(title):
            lst = rows_after.get(title, {}).get("attachments") or [{}]
            a = lst[0]
            return a if isinstance(a, dict) else {"status": a}

        at_a = _first_att("甲岗")
        at_b = _first_att("乙岗")
        ok = ("Traceback" not in (r.stderr or "")
              and at_a.get("status") == "ok"                    # 选中的下了
              and at_b.get("status") != "ok"                    # 没选的不下
              and stt.get("attach_ok", 0) >= 1)
        record("198. 第 2 段：只给选中记录下附件（未选的一条都不碰）", ok,
               "rc=%s 甲=%s 乙=%s attach_ok=%s" %
               (r.returncode, at_a.get("status"), at_b.get("status"),
                stt.get("attach_ok")))
    finally:
        stop_mock(p)

    # ---------- 199 第 2 段账目自洽 + doctor 能过
    begin_case("c199")
    reset_detail()
    p = start_mock("none")
    try:
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        u1 = "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]
        rows_seed = [{"title": "甲岗", "company": "甲", "detail_url": u1,
                      "detail_fetch": "error", "detail_attempts": 1},
                     {"title": "乙岗", "company": "乙", "detail_url": u1 + "x",
                      "detail_fetch": "ok"}]
        outd.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows_seed),
                        encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand199.txt"))
        cand.write_text(u1 + "\n", encoding="utf-8")
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_KIND="ok",
                       MOCKDETAIL_RATIO="0", MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--detail-urls", str(cand)], env_extra=env)
        rep = latest_report("mockdetail") or {}
        df = rep.get("datafile") or {}
        before, new, total = (df.get("records_before_run"), df.get("records_new_this_run"),
                              df.get("total_after_run"))
        dproc = subprocess.run([PY, str(Path(CRAWLER).parent / "doctor.py"), "--job", "mockdetail"],
                               capture_output=True, text=True,
                               env=dict(os.environ, **case_env()), encoding="utf-8",
                               errors="replace", timeout=60)
        row_line = [l for l in (dproc.stdout or "").splitlines() if "数据行数" in l]
        ok = ("Traceback" not in (r.stderr or "")
              and before == 2 and new == 0 and total == 2      # 第 2 段不改行数
              # 只查"数据行数"这一项：2 条合成数据会让"字段非空率"等其它项 FAIL，
              # 那是数据太小，不是账目问题
              and row_line and "PASS" in row_line[0])
        record("199. 第 2 段账目：before=2/new=0/total=2，doctor 数据行数 PASS", ok,
               "before=%s new=%s total=%s doctor_rc=%s 行数检查=%s" %
               (before, new, total, dproc.returncode,
                (row_line[0].split()[-1] if row_line else "-")))
    finally:
        stop_mock(p)

    # ---------- 200 空清单：报 detail_urls_empty，但账目必须自洽
    begin_case("c200")
    reset_detail()
    p = start_mock("none")
    try:
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        u1 = "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]
        outd.write_text(json.dumps({"title": "甲", "company": "甲",
                                    "detail_url": u1, "detail_fetch": "error"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand200.txt"))
        cand.write_text("", encoding="utf-8")
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--detail-urls", str(cand)], env_extra=env)
        rep = latest_report("mockdetail") or {}
        df = rep.get("datafile") or {}
        before, newn, total = (df.get("records_before_run"),
                               df.get("records_new_this_run"),
                               df.get("total_after_run"))
        ok = (r.returncode == 1
              and rep.get("reason") == "detail_urls_empty"
              and before == 1 and newn == 0 and total == 1)   # 账目自洽
        record("200. 空清单：failed/detail_urls_empty 且账目自洽（before==total）", ok,
               "rc=%s reason=%s before=%s new=%s total=%s" %
               (r.returncode, rep.get("reason"), before, newn, total))
    finally:
        stop_mock(p)

    # ---------- 201 两段式报告的 doctor status/reason 必须 PASS
    begin_case("c201")
    reset_detail()
    p = start_mock("none")
    try:
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        u1 = "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]
        outd.write_text(json.dumps({"title": "甲", "company": "甲",
                                    "detail_url": u1, "detail_fetch": "error"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand201.txt"))
        cand.write_text(u1 + "\n", encoding="utf-8")
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_ROBOTS="0")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--detail-urls", str(cand)], env_extra=env)
        # doctor 的 --job 会去全局 report 目录找，可能捞到别的用例的旧报告；
        # 这里直接 --report 指定本次报告，才是真的在验这一份。
        rpts = sorted((Path(CASE["dir"]) / "report").glob("report-mockdetail-*.json"))
        dproc = subprocess.run([PY, str(Path(CRAWLER).parent / "doctor.py"),
                                "--report", str(rpts[-1])],
                               capture_output=True, text=True,
                               env=dict(os.environ, **case_env()), encoding="utf-8",
                               errors="replace", timeout=60)
        line = [l for l in (dproc.stdout or "").splitlines() if "status/reason" in l]
        ok = (r.returncode == 0
              and line and "PASS" in line[0]
              and "details_repaired" in line[0])
        record("201. 两段式报告：doctor 的 status/reason 判 PASS（details_repaired 合法）", ok,
               "rc=%s doctor=%s" % (r.returncode, (line[0].strip() if line else "-")))
    finally:
        stop_mock(p)

    # ---------- 202 两段式附件失败 → partial / attachment_partial
    begin_case("c202")
    reset_detail()
    p = start_mock("none")
    try:
        outd = Path(os.path.join(CASE["dir"], "data", "mockdetail.jsonl"))
        outd.parent.mkdir(parents=True, exist_ok=True)
        u1 = "http://127.0.0.1:%s/detail/ok-1" % CASE["port"]
        bad = "http://127.0.0.1:%s/files/missing.pdf" % CASE["port"]
        outd.write_text(json.dumps({"title": "甲岗", "company": "甲",
                                    "detail_url": u1, "detail_fetch": "error",
                                    "detail_attempts": 1, "attachments": [bad]},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        cand = Path(os.path.join(CASE["dir"], "cand202.txt"))
        cand.write_text(u1 + "\n", encoding="utf-8")
        env = gate_env(CRAWLER_GATE_FORCE="1", CRAWLER_MAX_RPM="60",
                       CRAWLER_MAX_REQUESTS="200", MOCKDETAIL_ROBOTS="0",
                       MOCKDETAIL_ATT="bad")
        r = crawl(["--site", "mockdetail", "--detail-mode", "generic",
                   "--detail-urls", str(cand)], env_extra=env)
        rep = latest_report("mockdetail") or {}
        stt = rep.get("stats", {})
        rows_after = {x.get("title"): x for x in read_rows(str(outd))}
        att = (rows_after.get("甲岗", {}).get("attachments") or [{}])[0]
        att = att if isinstance(att, dict) else {"status": att}
        ok = (r.returncode == 3
              and rep.get("reason") == "attachment_partial"
              and att.get("status") != "ok"                 # 附件确实失败了
              and stt.get("detail_repaired_ok", 0) == 1)     # 详情仍然补成功
        record("202. 两段式附件失败 → partial/attachment_partial（详情仍记为 ok）", ok,
               "rc=%s reason=%s 附件=%s 详情ok=%s" %
               (r.returncode, rep.get("reason"), att.get("status"),
                stt.get("detail_repaired_ok")))
    finally:
        stop_mock(p)

    # =====================================================================
    # v14.5（203~205）：字段会自己变的情况
    #   wzrc 的 published 是"30分钟前"这种相对时间 → 不排除就会让 content_hash 每轮漂
    #   203 排除后稳定 / 204 不排除则漂（证明 203 不是同义反复）/ 205 变了算更新不算新增
    # =====================================================================
    def _crawl_reltime(job, pages=1, exclude=""):
        env = {"MOCKJSON_CASE": "reltime", "MOCKJSON_PAGES": str(pages)}
        if exclude:
            env["MOCKJSON_HASH_EXCLUDE"] = exclude
        crawl(["--site", "mockjson", "--job", job], env_extra=env)
        f = Path(CASE["dir"]) / "data" / ("%s.jsonl" % job)
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        rp = sorted((Path(CASE["dir"]) / "report").glob("report-%s-*.json" % job))
        rep = json.loads(rp[-1].read_text(encoding="utf-8"))
        return rows, rep

    p = start_mock("none")
    try:
        # 203：声明 hash_exclude=publish_date → 两次跑 hash 必须相同
        a203, _ = _crawl_reltime("rel_a", exclude="publish_date")
        b203, _ = _crawl_reltime("rel_b", exclude="publish_date")
        ha = [r["content_hash"] for r in a203]
        hb = [r["content_hash"] for r in b203]
        pa = [r.get("publish_date") for r in a203]
        pb = [r.get("publish_date") for r in b203]
        ok203 = (len(ha) == 3 and ha == hb and pa != pb)
        record("203. hash_exclude：相对时间变了但 content_hash 不变", ok203,
               "published %s→%s | hash %s→%s" % (pa[:1], pb[:1], ha[:1], hb[:1]))

        # 204：不声明 hash_exclude → hash 必须变（否则 203 是同义反复）
        c204, _ = _crawl_reltime("rel_c")
        d204, _ = _crawl_reltime("rel_d")
        ok204 = [r["content_hash"] for r in c204] != [r["content_hash"] for r in d204]
        record("204. 不排除时 hash 会变（证明 203 不是同义反复）", ok204,
               "hash %s vs %s" % ([r["content_hash"][:8] for r in c204][:1],
                                  [r["content_hash"][:8] for r in d204][:1]))

        # 205：时间变了、URL 没变 → 同 job 第二次跑是"更新/跳过"，不产生新增
        _, rep205a = _crawl_reltime("rel_e", exclude="publish_date")
        rows_after1 = [json.loads(l) for l in
                       (Path(CASE["dir"]) / "data" / "rel_e.jsonl").read_text(
                           encoding="utf-8").splitlines() if l.strip()]
        _, rep205b = _crawl_reltime("rel_e", exclude="publish_date")
        rows_after2 = [json.loads(l) for l in
                       (Path(CASE["dir"]) / "data" / "rel_e.jsonl").read_text(
                           encoding="utf-8").splitlines() if l.strip()]
        st1 = rep205a.get("stats") or {}
        st2 = rep205b.get("stats") or {}
        ok205 = (st1.get("records_new") == 3 and st2.get("records_new") == 0
                 and len(rows_after1) == len(rows_after2) == 3)
        record("205. publish_date 变但 detail_url 不变 → 第二次不新增（算更新）", ok205,
               "1st new=%s | 2nd new=%s rows=%d→%d status=%s" %
               (st1.get("records_new"), st2.get("records_new"),
                len(rows_after1), len(rows_after2), rep205b.get("status")))
    finally:
        stop_mock(p)

    print("")
    print("=" * 66)
    # =====================================================================
    # v14.6（206~208）：相对时间落成绝对时间（P1a）
    #   206 空值 → unknown，绝不 fallback 到 fetched_at（否则周报全是假新增）
    #   207 同锚点重解析 → 逐字节幂等
    #   208 守卫：像相对时间却没声明 hash_exclude → 必须报 anomaly（成对写）
    # =====================================================================
    sys.path.insert(0, str(ROOT / "crawlers"))
    import crawler as _eng
    import timeline as _tl
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    _ANCHOR = _dt(2026, 11, 14, 21, 5, tzinfo=_tz(_td(hours=8)))

    # ---- 206 ----
    at, prec, qual = _tl.parse_relative_time("", _ANCHOR)
    rec = {"published": "", "fetched_at": _ANCHOR.isoformat(timespec="minutes")}
    rec = _eng.reanchor_and_guard(rec, [], set())
    ok206 = (at == "" and qual == "unknown"
             and rec.get("published_at") == ""
             and rec.get("published_at") != rec.get("fetched_at"))
    record("206. 空值 → unknown，绝不填 fetched_at", ok206,
           "at=%r qual=%s rec.published_at=%r" % (at, qual, rec.get("published_at")))

    # ---- 207 ----
    samples = ["30分钟前", "4小时前", "1天前", "昨天", "前天", "刚刚",
               "2026-11-14", "2026-11-14 20:30", "11-13", "11-20", "11月13日", "乱七八糟"]
    a1 = [_tl.parse_relative_time(s, _ANCHOR) for s in samples]
    a2 = [_tl.parse_relative_time(s, _ANCHOR) for s in samples]
    r1 = {"published": "30分钟前", "fetched_at": _ANCHOR.isoformat(timespec="minutes")}
    r2 = dict(r1)
    r1 = _eng.reanchor_and_guard(r1, [], set())
    r1b = _eng.reanchor_and_guard(dict(r1), [], set())
    ok207 = (a1 == a2) and (r1 == r1b)
    record("207. 同锚点重解析 → 逐字节幂等", ok207,
           "样本 %d；30分钟前 → %s（重算一致=%s）" %
           (len(samples), a1[0][0], r1 == r1b))

    # ---- 208：守卫（成对） ----
    anomalies = []
    _eng.HASH_EXCLUDE.clear()
    _eng.reanchor_and_guard({"published": "30分钟前",
                                "fetched_at": _ANCHOR.isoformat(timespec="minutes")},
                               anomalies, set())
    hit_without = any(x.get("anomaly") == "relative_time_not_excluded" for x in anomalies)

    anomalies2 = []
    _eng.HASH_EXCLUDE.add("published")
    try:
        _eng.reanchor_and_guard({"published": "30分钟前",
                                    "fetched_at": _ANCHOR.isoformat(timespec="minutes")},
                                   anomalies2, set())
        hit_with = any(x.get("anomaly") == "relative_time_not_excluded" for x in anomalies2)
    finally:
        _eng.HASH_EXCLUDE.discard("published")
    ok208 = hit_without and not hit_with
    record("208. 守卫：未声明 hash_exclude 报 anomaly；声明后不报", ok208,
           "未声明=%s 已声明=%s" % (hit_without, hit_with))

    for name, ok, detail in results:
        if not ok:
            print("  未通过: %s  %s" % (name, detail))
    print("=" * 66)
    passed = sum(1 for _, ok, _ in results if ok)
    print("结果: %d/%d 通过" % (passed, len(results)))

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
