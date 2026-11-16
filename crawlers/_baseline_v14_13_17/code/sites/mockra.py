# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""阶段A 测试用站点：Retry-After / Referer 回显。

MOCKRA_MODE：sec（Retry-After: 2）| date（HTTP-date）| none（不给头）
backoff 设 0.1，让"退避=0.3s"小于 Retry-After，才能证明引擎真的读了头。
"""
import os

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT
MODE = os.environ.get("MOCKRA_MODE", "sec")

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockra",
    "response": "html",
    "url_template": BASE + "/ra/retry?mode=%s&page={page}" % MODE,
    "paginate": "number",
    "page_start": 1,
    "page_end": 1,
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 5,
    "retries": 2,
    "backoff": 0.1,          # 退避 0.1*3=0.3s ＜ Retry-After，用来区分谁生效
    "respect_robots": False,
    "dedup_key": "detail_url",
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


def parse_list(html, page_url):
    # 走 _fetch_core（HTML 路径）才能验证 Retry-After 的读取
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    return [{"title": d.get_text(strip=True),
             "detail_url": page_url + "#" + d.get_text(strip=True)}
            for d in soup.select("div.item")]