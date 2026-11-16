# -*- coding: utf-8 -*-
"""
站点配置：本地 mock 服务器（只用于故障注入测试，不访问外网）

配合同目录上一层的 tests/mock_site.py 使用。默认地址 127.0.0.1:8765。

页面设计（每页 3 条，方便手算）：
    /v1/p1.html        正常 3 条
    /v1/p2.html        正常 3 条（内容与 p1 不同）
    /v1/p3.html        空页（HTML 里没有 .item 节点）
    /v1/p4.html        空页
    /v1/p5.html        空页
    /v1/p6.html        返回 403
    /v1/p7.html        robots 禁止（测试用 robots 规则控制）
"""

import os


def _port():
    """端口来自 MOCK_PORT；空串、"None" 这类脏值一律当没设置（默认 8765）。"""
    v = (os.environ.get("MOCK_PORT") or "").strip()
    if not v or v.lower() == "none":
        return 8765
    try:
        return int(v)
    except ValueError:
        return 8765


# 测试时由 test_crawler.py 通过 MOCK_PORT 注入（每个用例独立端口）
PORT = _port()

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mock",
    "url_template": "http://127.0.0.1:%d/v1/p{page}.html" % PORT,
    "page_start": 1,
    "page_end": 2,

    # 本地服务器，间隔可以压到很小
    "delay_min": 0.05,
    "delay_max": 0.1,
    # timeout 压到 2 秒：这样 /v1/p10.html 的 3 秒延迟会真的触发超时
    "timeout": 2,
    # retries=3：p9 是"前两次 500、第三次 200"，正好需要 3 次尝试来验证退避
    "retries": 3,
    "backoff": 1.5,

    "respect_robots": True,
    "dedup_key": "detail_url",

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
}


def parse_list(html, page_url):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    rows = []
    for it in soup.select("div.item"):
        a = it.select_one("a.title")
        if a is None:
            continue
        rows.append({
            "title": a.get_text(strip=True),
            "detail_url": a.get("href", ""),
            "note": it.select_one("span.note").get_text(strip=True) if it.select_one("span.note") else "",
        })
    return rows