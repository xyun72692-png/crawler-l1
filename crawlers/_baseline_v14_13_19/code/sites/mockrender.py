# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""render_batch 的离线测试站点（本地 mock_site 的 JS 渲染页）。

真实对应：jrzp 系列表页——空壳 + JS 拉数据后画 DOM。
这里用 mock 的 /spa/js.html，保证 0 外网。
"""
import os

from bs4 import BeautifulSoup

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT

CONFIG = {
    # Rule 0：本地夹具，不涉及真实条款
    "terms_status": "allowed",
    # 平台标 jrzp：用于验证 --allow-robots-js 的三道闸
    "platform": "jrzp",
    "render_authorized": {"by": "user", "at": "2026-11-14", "max_pages": 20},
    "job": "mockrender",
    "url_template": BASE + "/spa/js.html?page={page}",
    "paginate": "number",
    "page_start": 1,
    "page_end": 2,
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 10,
    # 默认跳过 robots；T-RB-8 需要验证 fail-closed 时用 MOCK_RESPECT_ROBOTS=1 打开
    "respect_robots": (os.environ.get("MOCK_RESPECT_ROBOTS") == "1"),
    "dedup_key": "detail_url",
    # render 专用：等列表渲染出来的选择器 + 稳定等待
    "render_ready_selector": "a.job",
    "render_settle_ms": 300,
    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


def parse_list(html, page_url=None):
    """从**渲染后的 DOM** 取岗位：<a class="job" href=...>标题</a>。

    这就是"最薄一层"——只拿 detail URL 和标题，详情回 plain 通道。
    """
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.select("a.job"):
        href = a.get("href") or ""
        title = a.get_text(" ", strip=True)
        if not href or not title:
            continue
        url = href if href.startswith("http") else BASE + href
        out.append({"title": title, "detail_url": url, "source": "render"})
    return out