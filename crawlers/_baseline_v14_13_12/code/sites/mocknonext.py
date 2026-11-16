# -*- coding: utf-8 -*-
"""
状态断言专用假站：paginate=next 但**故意不提供 parse_next**。

用来断言 `failed / missing_parse_next`（引擎在发请求前就该拒绝，rc=1）。
其它站点模块都有 parse_next，所以这个状态之前完全没被覆盖。
"""
import os

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mocknonext",
    "url_template": BASE + "/n/page1.html",
    "paginate": "next",          # ← next 模式
    "page_start": 1,
    "page_end": 1,
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 3,
    "retries": 1,
    "backoff": 0.2,
    "respect_robots": False,
    "dedup_key": "detail_url",
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def parse_list(html, page_url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for it in soup.select("div.item"):
        a = it.select_one("a.title")
        if a is None:
            continue
        href = a.get("href") or ""
        rows.append({
            "title": a.get_text(strip=True),
            "detail_url": href if href.startswith("http") else BASE + href,
        })
    return rows

# 故意不写 parse_next：这正是被断言的行为