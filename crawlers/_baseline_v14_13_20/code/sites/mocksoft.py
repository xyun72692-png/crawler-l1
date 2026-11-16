# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""阶段A 测试用站点：软封对照（空页 + canary）。

环境变量 MOCKSOFT_MODE：
    blocked  → 列表页和 canary 都是 0 卡片（模拟"HTTP 200 + 假页面"）
    ok       → 列表页 0 卡片、canary 2 卡片（说明是关键词真空，不是被封）
"""
import os

from bs4 import BeautifulSoup

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT
MODE = os.environ.get("MOCKSOFT_MODE", "blocked")   # blocked | ok
GROUP = os.environ.get("MOCKSOFT_GROUP", "")        # 冷却分组（测试跨 host 共用）

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mocksoft",
    "url_template": BASE + "/soft/p{page}.html?m=" + MODE,
    "paginate": "number",
    "page_start": 1,
    "page_end": 3,
    # 测试里把间隔压到 0，别把测试拖慢
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 5,
    "retries": 1,
    "backoff": 2.0,
    "respect_robots": False,
    "dedup_key": "detail_url",
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    "soft_block": {
        "enabled": True,
        "canary_url": BASE + "/soft/canary.html?m=" + MODE,
        "cooldown_sec": [7200, 21600, 86400],
        "group": GROUP,
    },
    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for d in soup.select("div.card"):
        rows.append({"title": d.get_text(strip=True),
                     "detail_url": page_url + "#" + d.get_text(strip=True)})
    return rows