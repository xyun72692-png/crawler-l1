# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""温州人才网 · 日常增量任务（提案2）

和 wzrc_all 的区别只有三处，刻意做成**独立 job / 独立断点**：
    1. settr=3      → 只要最近 3 天的
    2. sort=rtime   → 按更新时间倒序（已实测：25分钟前 ×4 → 2小时前，确实递减）
    3. page_end=20  → 安全上限 20 页（不是固定的"只看前 2 页"）

为什么不复用 wzrc_all 的 state：
    两者的"第 1 页"不是同一批数据（一个是全量、一个是近 3 天）。
    共用断点会让 pages_done 互相污染 —— 一方标记完成，另一方就跳过。

冷却锁仍然共用（group=wzrc）：封禁按 IP，不按栏目。

页数口径（**2026-11-15 改判：本站已改用 coverage_mode="window"**）：
    ⚠ 下面这段是 11-11 的 full 模式口径，已被推翻，只留作历史说明 ——
    **当前生效的是 window 模式**：每轮清空页码断点、只重抓前 refresh_pages(3) 页，
    靠 seen_keys 去重；"覆盖不全"是设计如此，要完整快照请用站点 wzrc_all。

    （历史）page_end=20 是**安全上限**，不是目标页数。真实抓取页数 = min(planned, M)：
      · M ≤ 20（比如 git 量少时 M=5）→ 抓满 M 页，truncated=False，coverage=1.0 → success
      · M > 20（比如某天新增职位爆量）→ 只抓 20 页，truncated=True
                                  → partial / page_range_truncated（提醒你"这次没抓全"）
    所以正常情况下是"抓完就收工"，只有真的超过 20 页才会报警。

⚠ 本站点的 M（页面声明总页数）会随筛选变：
   实测 citycategory=wenzhou&jobtag=147&sort=rtime → 109 页（无 settr 时）。
   带 settr=3 时 M 会小很多，具体看每次运行报告里的 pages_declared。
"""
import os
from ._common import TOTAL_PAGES_PATTERN

import sites.wzrc_all as _wz   # 复用同一套 parse_list（选择器只有一份）

BASE = "https://www.wzrc.net"
CITY = os.environ.get("WZ_CITY", "wenzhou")
TAG = os.environ.get("WZ_TAG", "147")
SETTR = os.environ.get("WZ_SETTR", "3").strip() or "3"
if SETTR not in ("3", "7", "15", "30"):
    raise SystemExit("WZ_SETTR=%r 非法：只接受 3/7/15/30（已从站方页面确认）" % SETTR)

_q = ("m=&c=Jobs&a=jobs_list&citycategory=" + CITY
      + ("&jobtag=" + TAG if TAG and TAG != "0" else "")
      + "&settr=" + SETTR
      + "&sort=rtime"
      + "&page={page}")

CONFIG = {
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "wzrc_inc",
    "url_template": BASE + "/index.php?" + _q,
    "paginate": "number",
    "page_start": 1,
    "page_end": 20,         # 安全上限（min(20, M) 生效）；window 模式下实际只看前 3 页
    # ---- A5（2026-11-15 改判，取代 11-11 的"不配 coverage_mode"）----
    # 11-11 的判断是"配 window 会把没抓全静默豁免"，那针对的是**一次性快照**语义。
    # 但本站是滚动时间窗（settr=3 + sort=rtime）：新岗位永远出现在第 1 页顶部，
    # 而 full 模式的页码断点让第 1 页永远"已完成"→ 一个请求都不发、永远抓不到新岗。
    # 所以这里必须走 window：断点只认当天，跨天作废，每轮只重抓前 3 页。
    # 代价说清楚：window 模式下"覆盖不全"是**设计如此**（它只维护最近窗口），
    # 报告不给 coverage=1.0 的假象；要完整快照请用站点 wzrc_all。
    "coverage_mode": "window",
    "refresh_pages": 3,              # 每轮只重抓前 3 页（约 15 条）
    # 连续 15 条都见过就提前停。3 页 × 5 条/页 = 15 条 → 正常配置下**会**在最后一页触发。
    # 为什么是 15 不是 20：20 时 3 页（15 条）永远到不了，等于这个开关从未生效。
    "refresh_stop_after_dups": 15,

    "delay_min": 3.0,
    "delay_max": 5.0,
    "timeout": 25,
    "retries": 1,
    "backoff": 2.0,

    "respect_robots": True,
    # v14.13.1：与 WAF 打交道的站走 cffi（TLS 与 UA / Sec-CH-UA 同源）。
    # 2026-11-15 A/B（同页各 5 条）：字段集/顺序/逐条内容 0 差异，
    # gate.requests_used 两边都 = 2（robots + 1 页），anomalies = 0。
    "transport": "cffi",
    # v14.5：published 常见"30分钟前"这种相对时间，会随抓取时刻变；
    # 它不属于内容变化，排除出 content_hash（P1 会补 published_at 绝对时间）
    "hash_exclude": ["published"],
    "dedup_key": "detail_url",
    "total_pages_pattern": TOTAL_PAGES_PATTERN,   # 唯一副本见 _common.py

    "detail": {"enabled": False},
    "attachments": {"enabled": False},

    "soft_block": {
        "enabled": True,
        "canary_url": (BASE + "/index.php?m=&c=Jobs&a=jobs_list&citycategory=" + CITY
                       + ("&jobtag=" + TAG if TAG and TAG != "0" else "")
                       + "&page=1"),
        "cooldown_sec": [7200, 21600, 86400],
        "group": "wzrc",
    },

    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}

parse_list = _wz.parse_list