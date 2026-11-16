# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""测试用站点：总页数声明 / page_size 记录。

环境变量：
    MOCK_TOTAL     页面里声明的总页数（默认 3；填 none 表示页面不带这个标记）
    MOCK_PLAN      page_end（默认 5）
    MOCK_PAGE_SIZE 站点真实使用的每页条数（默认空 = 不设）
    MOCK_PAGE_PROBE "1" = 仅探针标记
"""
import os

from bs4 import BeautifulSoup

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT
TOTAL = os.environ.get("MOCK_TOTAL", "3")
PLAN = int(os.environ.get("MOCK_PLAN", "5"))
PAGE_SIZE = os.environ.get("MOCK_PAGE_SIZE", "")
PROBE = os.environ.get("MOCK_PAGE_PROBE", "")
CMODE = os.environ.get("MOCK_COVERAGE_MODE", "")   # "window" = 只抓窗口
FILTER = os.environ.get("MOCK_FILTER", "")          # 模拟筛选条件（换值 = 换条件）

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mocktotal",
    "url_template": BASE + "/tot/p{page}.html?t=" + TOTAL + ("&f=" + FILTER if FILTER else ""),
    "paginate": "number",
    "page_start": 1,
    "page_end": PLAN,
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 5,
    "retries": 1,
    "backoff": 2.0,
    "respect_robots": False,
    "dedup_key": "detail_url",
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    "total_pages_pattern": r"</span>\s*/\s*(\d+)\s*页",
    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}

if CMODE:
    CONFIG["coverage_mode"] = CMODE

if PAGE_SIZE:
    CONFIG["page_size"] = int(PAGE_SIZE)
    CONFIG["page_size_probe"] = (PROBE == "1")


def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for a in soup.select("div.item a"):
        rows.append({"title": a.get_text(strip=True),
                     "detail_url": page_url + "#" + a.get_text(strip=True)})
    return rows