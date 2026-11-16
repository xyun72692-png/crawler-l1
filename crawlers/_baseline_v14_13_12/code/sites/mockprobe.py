# -*- coding: utf-8 -*-
"""测试用站点：页大小探测样本（/ps/p{n}.html?size=N）。"""
import os

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockprobe",
    "url_template": BASE + ("/psb/p{page}.html" if os.environ.get("MOCK_PROBE_BROKEN") == "1" else "/ps/p{page}.html"),
    "paginate": "number",
    "page_start": 1,
    "page_end": 3,
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 5,
    "retries": 1,
    "backoff": 2.0,
    "respect_robots": False,
    "dedup_key": "detail_url",
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": os.environ.get("CRAWLER_STATE_DIR") or r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def parse_list(html, page_url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for a in soup.select("div.item a"):
        rows.append({"title": a.get_text(strip=True), "detail_url": page_url + "#" + a.get_text(strip=True)})
    return rows