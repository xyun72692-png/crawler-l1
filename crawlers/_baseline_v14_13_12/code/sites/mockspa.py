# -*- coding: utf-8 -*-
"""
SPA 抓取两层能力示范（只给 tests 用，不出网）。

两种站点写法都在这一个文件里，靠 MOCKSPA_MODE 切换：

    mode=api       第 1 层：页面是空壳，数据靠后端 JSON 接口 → 用引擎的 response=json
    mode=embedded  第 2 层：页面里内嵌 __NEXT_DATA__ JSON → 用 parse_list 抠出来

真站对应关系：
    第 1 层 = 找 XHR/接口（乐清政务 unit-build API 就是这类，实测 GET+queryData 返回 data.html）
    第 2 层 = 抠 <script id="__NEXT_DATA__"> 里的 JSON
"""
import json
import os

from bs4 import BeautifulSoup

PORT = (os.environ.get("MOCK_PORT") or "").strip() or "8765"
MODE = os.environ.get("MOCKSPA_MODE", "api")
SOFT = os.environ.get("MOCKSPA_SOFT", "")   # "1" = 开软封（测 json 冲突）
BASE = "http://127.0.0.1:%s" % PORT

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockspa",
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
    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}

if SOFT == "1":
    CONFIG["soft_block"] = {"enabled": True,
                            "canary_url": BASE + "/spa/index.html"}

if MODE == "api":
    # 第 1 层：直接打接口，站点模块连 parse_list 都不用写
    CONFIG["response"] = "json"
    CONFIG["url_template"] = BASE + "/spa/api/list?page={page}"
    CONFIG["json"] = {
        "list_path": "data.items",
        "field_map": {"title": "name", "detail_url": "link"},
        "ok_path": "code", "ok_value": 0,
    }
else:
    # 第 2 层：抓空壳 HTML，从 __NEXT_DATA__ 里抠 JSON
    CONFIG["response"] = "html"
    # 单页站点：把 url_template 也指到这张空壳页，否则引擎会用默认模板
    CONFIG["url_template"] = BASE + "/spa/index.html"
    CONFIG["page_end"] = 1


def parse_list(html, page_url):
    """第 2 层专用：把内嵌 JSON 抠出来，再映射成记录。"""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None:
        raise RuntimeError("页面里没有 __NEXT_DATA__，说明这个站不属于第 2 层")
    data = json.loads(tag.get_text())
    items = (((data.get("props") or {}).get("pageProps") or {}).get("items")) or []
    return [{"title": it.get("name"), "detail_url": it.get("link")} for it in items]