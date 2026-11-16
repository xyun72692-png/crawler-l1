# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""
状态断言专用假站：用 MOCK_STATE 环境变量切换"要触发哪种状态"。

为什么单独做一个：现有 mock*.py 各自只覆盖一种玩法（json/附件/next…），
而"27 种状态里 8 种没被断言"需要的是**同一站点的不同错误配置**，
用同一个模块 + 环境变量切换，测试里一行就够，也不会污染别的用例。

用法（测试内）：
    crawl(["--site","mockstates","--job","x"], env_extra={"MOCK_STATE":"failsome"})

支持的模式：
    normal      正常列表页（/v1/pN.html），默认
    failsome    第 1 页正常、第 2 页 500 → 部分页面失败
    failall     第 2、3 页都 500（第 1 页不抓）→ 全部页面失败
    bogus       paginate 配成非法值
    badscope    response=json 且 json.total_scope 非法
    blocked     正常列表页 + 强制 respect_robots=True（配合 --robots forbid-all）
"""
import os

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
BASE = "http://127.0.0.1:%s" % PORT
MODE = (os.environ.get("MOCK_STATE") or "normal").strip().lower()

_PAGES = {"normal": (1, 2), "blocked": (1, 2),
          "failsome": (1, 2), "failall": (2, 3)}.get(MODE, (1, 2))
_TMPL = BASE + ("/mix/p{page}.html" if MODE in ("failsome", "failall") else "/v1/p{page}.html")

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockstates",
    "url_template": _TMPL,
    "paginate": "bogus" if MODE == "bogus" else "number",
    "page_start": _PAGES[0],
    "page_end": _PAGES[1],
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 3,
    "retries": 1,
    "backoff": 0.2,
    "respect_robots": (MODE == "blocked"),
    "dedup_key": "detail_url",
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}

if MODE == "badscope":
    CONFIG["response"] = "json"
    CONFIG["json"] = {
        "method": "GET",
        "params": {"page": "{page}"},
        "list_path": "data.items",
        "field_map": {"title": "name", "detail_url": "url"},
        "total_scope": "weird",       # ← 非法值，应当直接 failed/bad_total_scope
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