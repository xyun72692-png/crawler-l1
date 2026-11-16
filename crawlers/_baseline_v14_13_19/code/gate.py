# -*- coding: utf-8 -*-
"""
请求闸门（v12）：把"≤12 次/分钟、单任务 ≤200 请求、≤30 分钟"从纪律变成引擎保证。

设计要点（都在方案 B 里论证过）：
  1. 钩子挂在 `Session.send()`，不是 `request()` —— requests 跟重定向走的是 send，
     挂错地方会漏计每一跳。
  2. 主节流 + 主抖动都在闸门里：最小间隔 = uniform(4.8, 6.5) 秒，
     再叠一道"滑动窗口 ≤ max_rpm"的天花板。
     只做滑窗会让节奏变成"6 秒发 12 个 + 停 54 秒"，那比均匀更像机器。
  3. 预算按"最多成功发出 N 个请求"语义：先判后加，第 N 个放行，第 N+1 个抛。
  4. 时间源可注入（now_fn / sleep_fn），测试用假时钟，不 sleep。

环境变量（只给测试用，生产不设）：
  CRAWLER_GATE_WINDOW     窗口秒数，默认 60
  CRAWLER_GATE_JITTER     "min,max"，默认 "4.8,6.5"
  CRAWLER_MAX_RPM         默认取 CONFIG["max_rpm"]（12）
  CRAWLER_MAX_REQUESTS    默认取 CONFIG["max_requests"]（200）
  CRAWLER_MAX_SECONDS     默认取 CONFIG["max_seconds"]（1800）
  CRAWLER_GATE_FORCE=1    强制对回环地址也生效（生产模式的行为）
"""

import math
import os
import random
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


class RequestBudgetExceeded(RuntimeError):
    """本轮请求数已达上限。"""


class TimeBudgetExceeded(RuntimeError):
    """本轮运行时长已达上限。"""


def _env_float(name, default):
    v = os.environ.get(name)
    if not v:
        return float(default)
    try:
        return float(v)
    except ValueError:
        return float(default)


def _env_int(name, default):
    return int(_env_float(name, default))


def _jitter_range(default=(4.8, 6.5)):
    v = os.environ.get("CRAWLER_GATE_JITTER")
    if not v:
        return default
    try:
        a, b = [float(x) for x in v.split(",")]
        if a < 0 or b < a:
            return default
        return (a, b)
    except Exception:
        return default


def is_test_env():
    """测试环境判定：只有显式设置了测试变量才算。

    为什么不用"目标是回环就豁免"：哪天真在本机部署跑，127.0.0.1 就不受限速了。
    """
    # 测试套件会给子进程注入 CRAWLER_OUT_DIR / CRAWLER_LOG_DIR 等目录变量，
    # 生产运行这些值来自 CONFIG 而不是环境变量 —— 所以拿它们当"测试环境"的判据是安全的。
    return any(os.environ.get(k) for k in (
        "CRAWLER_TEST_TMP", "CRAWLER_TEST_MODE",
        "CRAWLER_OUT_DIR", "CRAWLER_LOG_DIR",
        "CRAWLER_STATE_DIR", "CRAWLER_REPORT_DIR"))


def host_exempt(host):
    """该主机是否可以跳过闸门（仅测试环境下的回环地址）。"""
    h = (host or "").lower()
    if h.startswith("["):               # [::1]:8080 这种
        h = h[1:h.find("]")] if "]" in h else h
    h = h.split(":")[0]                 # 去掉 :port
    if h not in LOOPBACK:
        return False
    if os.environ.get("CRAWLER_GATE_FORCE"):
        return False
    return is_test_env()


class RequestGate:
    def __init__(self, max_rpm=12, max_requests=200, max_seconds=1800,
                 jitter=(4.8, 6.5), window_sec=60.0,
                 now_fn=None, sleep_fn=None, log=None):
        # 参数边界（fail-closed）：0 或负数会让 before() 里的 win[0] 直接 IndexError，
        # 与其在第一次请求时炸，不如在构造时就拒绝。
        if int(max_rpm) <= 0:
            raise ValueError("max_rpm 必须 > 0（现在是 %r）" % (max_rpm,))
        # requests/seconds 的 0 是合法语义："立刻到预算"（fail-closed），不是非法值
        if int(max_requests) < 0:
            raise ValueError("max_requests 不能为负（现在是 %r）" % (max_requests,))
        if not (float(max_seconds) >= 0) or not math.isfinite(float(max_seconds)):
            raise ValueError("max_seconds 必须是有限非负数（现在是 %r）" % (max_seconds,))
        if not (float(window_sec) > 0) or not math.isfinite(float(window_sec)):
            raise ValueError("window_sec 必须是有限正数（现在是 %r）" % (window_sec,))
        if not isinstance(jitter, (tuple, list)) or len(jitter) != 2:
            raise ValueError("jitter 必须是 (min, max)（现在是 %r）" % (jitter,))
        _j0, _j1 = float(jitter[0]), float(jitter[1])
        if not (math.isfinite(_j0) and math.isfinite(_j1)) or _j0 < 0 or _j1 < _j0:
            raise ValueError("jitter 必须有限、非负且 min<=max（现在是 %r）" % (jitter,))
        self.max_rpm = int(max_rpm)
        self.max_requests = int(max_requests)
        self.max_seconds = float(max_seconds)
        self.jitter = tuple(jitter)
        self.window_sec = float(window_sec)
        self.now_fn = now_fn or time.monotonic
        self.sleep_fn = sleep_fn or time.sleep
        self.log = log

        self.t0 = self.now_fn()
        self.count = 0
        self.last = None
        self.win = deque()
        self.host_win = defaultdict(deque)
        self.host_count = defaultdict(int)
        self.throttled = 0
        self.stopped_by = ""

    # ---------------- 核心：发请求前必须调用
    def before(self, host=""):
        if self.count >= self.max_requests:
            self.stopped_by = "request_budget"
            raise RequestBudgetExceeded(
                "已达单任务请求上限 %d（第 %d 个被拦）" % (self.max_requests, self.count + 1))

        now = self.now_fn()
        # 至少放过第 1 个请求（robots）：否则 max_seconds 很小时连 robots 都被拦，
        # 会被上层误判成 robots_denied，报错方向就错了。
        if self.count >= 1 and now - self.t0 >= self.max_seconds:
            self.stopped_by = "time_budget"
            raise TimeBudgetExceeded(
                "已达单次运行时长上限 %.0f 秒" % self.max_seconds)

        # ① 滑动窗口：丢掉窗口外的旧时间戳
        while self.win and now - self.win[0] >= self.window_sec:
            self.win.popleft()

        # ② 最小间隔（带抖动）—— 主节流在这里
        target = now
        if self.last is not None:
            target = self.last + random.uniform(*self.jitter)
        # ③ 窗口天花板
        if len(self.win) >= self.max_rpm:
            target = max(target, self.win[0] + self.window_sec + 0.001)

        if target > now:
            self.throttled += 1
            self.sleep_fn(target - now)
            now = self.now_fn()

        self.last = now
        self.win.append(now)
        self.host_win[host].append(now)
        self.host_count[host] += 1
        self.count += 1

    # ---------------- 报告
    def elapsed(self):
        return max(0.0, self.now_fn() - self.t0)

    def actual_rpm(self):
        el = self.elapsed()
        return round(60.0 * self.count / el, 1) if el > 0 else 0.0

    def summary(self):
        by_host = {}
        for h, n in self.host_count.items():
            w = self.host_win.get(h) or deque()
            el = (w[-1] - w[0]) if len(w) >= 2 else 0.0
            by_host[h] = {
                "requests": n,
                "rpm": round(60.0 * (n - 1) / el, 1) if el > 0 else 0.0,
            }
        return {
            "max_rpm": self.max_rpm,
            "max_requests": self.max_requests,
            "max_seconds": int(self.max_seconds),
            "jitter_sec": list(self.jitter),
            "window_sec": self.window_sec,
            "requests_used": self.count,
            "elapsed_sec": round(self.elapsed(), 1),
            "actual_rpm": self.actual_rpm(),
            "throttled": self.throttled,
            "stopped_by": self.stopped_by,
            "by_host": by_host,
        }


# ---------------------------------------------------------------- 全局实例
_GATE = None


def build_from_config(cfg, log=None):
    """按 CONFIG + 环境变量造闸门（每次运行一个）。"""
    return RequestGate(
        max_rpm=_env_int("CRAWLER_MAX_RPM", cfg.get("max_rpm", 12)),
        max_requests=_env_int("CRAWLER_MAX_REQUESTS", cfg.get("max_requests", 200)),
        max_seconds=_env_float("CRAWLER_MAX_SECONDS", cfg.get("max_seconds", 1800)),
        jitter=_jitter_range(tuple(cfg.get("gate_jitter") or (4.8, 6.5))),
        window_sec=_env_float("CRAWLER_GATE_WINDOW", cfg.get("gate_window_sec", 60)),
        log=log,
    )


def set_gate(g):
    global _GATE
    _GATE = g
    return g


def current_gate():
    return _GATE