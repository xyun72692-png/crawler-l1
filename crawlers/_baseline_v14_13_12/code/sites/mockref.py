# -*- coding: utf-8 -*-
"""阶段A 测试用站点：Referer 回显（JSON）。"""
import os

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockref",
    "response": "json",
    "url_template": BASE + "/echo/ref?page={page}",
    "paginate": "number",
    "page_start": 1,
    "page_end": 2,
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 5,
    "retries": 1,
    "backoff": 1.0,
    "respect_robots": False,
    "dedup_key": "detail_url",
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    # 服务器把 Referer 塞进 name 字段，我们把它当 title 存下来
    "json": {"list_path": "data.items",
             "field_map": {"title": "name", "detail_url": "link"}},
    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def parse_list(html, page_url):
    raise RuntimeError("mockref 是 JSON 站点，不该调用 parse_list")