# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""
站点配置：本地 mock 的"下一页翻页"测试站（只给 tests/test_crawler.py 用，不出网）。

验证 crawler.py 的 paginate="next" 模式：
    * 从当前页 HTML 里读 <a class="next"> 得到下一页地址
    * urls_done / next_url 断点（与 number 模式的 pages_done 完全分开）
    * 防循环（URL 归一化后比对）、max_pages 上限、断链停止

环境变量：
    MOCK_PORT          mock 服务端口（每个用例独立）
    MOCKNEXT_START     起始路径，默认 /n/page1.html
    MOCKNEXT_MAX_PAGES max_pages 覆盖值，默认 200
"""

import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _port():
    v = (os.environ.get("MOCK_PORT") or os.environ.get("MOCKNEXT_PORT") or "").strip()
    if not v or v.lower() == "none":
        return "8765"
    return v


PORT = _port()
START = os.environ.get("MOCKNEXT_START", "/n/page1.html")
# 模拟筛选条件：不同值 = 不同结果集（用来测"换条件要清断点"）
FILTER = os.environ.get("MOCKNEXT_FILTER", "")
if FILTER:
    START = START + ("&" if "?" in START else "?") + "f=" + FILTER
MAX_PAGES = int(os.environ.get("MOCKNEXT_MAX_PAGES", "200"))
BASE = "http://127.0.0.1:%s" % PORT

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mocknext",
    "paginate": "next",                 # ← 阶段2 的核心开关
    "max_pages": MAX_PAGES,

    # next 模式不用页码模板，但引擎仍需要一个"起始地址"来做 robots 检查
    "url_template": BASE + START,
    "page_start": 1,
    "page_end": 1,

    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 3,
    "retries": 1,
    "backoff": 1.0,

    "respect_robots": False,
    "dedup_key": "detail_url",

    "detail": {"enabled": False},

    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


def parse_list(html, page_url):
    """列表页：每页 3 条 <div class="item"><a class="title" href="/detail/...">。"""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for it in soup.select("div.item"):
        a = it.select_one("a.title")
        if a is None:
            continue
        rows.append({
            "title": a.get_text(strip=True),
            "detail_url": urljoin(page_url, a.get("href", "")),
            "note": (it.select_one("span.note").get_text(strip=True)
                     if it.select_one("span.note") else ""),
        })
    return rows


def parse_next(html, page_url):
    """
    "下一页"地址：页面里 <a class="next" href="...">。
    没有这个节点 → 返回 None（引擎据此判定 no_next，正常收工）。

    特例：页面里有 <div class="boom"> 时故意抛异常，
    用来验证"解析器出错不能被当成没有下一页"（那会把中断报成抓完了）。
    """
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one("div.boom"):
        raise RuntimeError("mocknext: 故意抛出的解析异常")
    a = soup.select_one("a.next")
    if a is None or not a.get("href"):
        return None
    return urljoin(page_url, a["href"])