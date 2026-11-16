# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""
站点配置：本地 mock 的"JSON 接口"测试站（只给 tests/test_crawler.py 用，不出网）。

这个文件是阶段3 的样板：**JSON 站点连 parse_list 都不用写**。
解析全由 crawler.py 按 CONFIG["json"] 完成。

环境变量：
    MOCK_PORT        mock 服务端口（每个用例独立）
    MOCKJSON_CASE    items / post / bizerror / empty / missing / next / cursor / notjson
    MOCKJSON_PAGES   number 模式抓到第几页
"""

import os


def _port():
    for key in ("MOCK_PORT", "MOCKJSON_PORT"):
        v = (os.environ.get(key) or "").strip()
        if v and v.lower() != "none":
            return v
    return "8765"


PORT = _port()
CASE = os.environ.get("MOCKJSON_CASE", "items")
PAGES = int(os.environ.get("MOCKJSON_PAGES", "3"))
# 覆盖分页方式（测"next 但没配 next_path"这种配置错误）
PAGINATE_ENV = os.environ.get("MOCKJSON_PAGINATE", "")
SINGLE = os.environ.get("MOCKJSON_SINGLE", "0") == "1"
CURSOR_END = os.environ.get("MOCKJSON_CURSOR_END", "")
# v14.5：注入 hash_exclude（逗号分隔），测"相对时间不影响指纹"
HASH_EXCLUDE = [x.strip() for x in (os.environ.get("MOCKJSON_HASH_EXCLUDE") or "").split(",") if x.strip()]
# total 的口径：global（整个结果集）或 page（当前页）；也用来测"非法值直接失败"
TOTAL_SCOPE = os.environ.get("MOCKJSON_TOTAL_SCOPE", "")
RESPONSE = os.environ.get("MOCKJSON_RESPONSE", "json")
BASE = "http://127.0.0.1:%s" % PORT

# 每种场景用不同的 URL / 分页方式，其余全靠下面这份 json 配置
if CASE == "next":
    URL_TMPL = BASE + "/api/next?p=1"
    PAGINATE = "next"
elif CASE == "cursor":
    URL_TMPL = BASE + "/api/cursor"
    PAGINATE = "next"
elif CASE == "cursor0":
    URL_TMPL = BASE + "/api/cursor0"
    PAGINATE = "next"
elif CASE == "globalbad":
    URL_TMPL = BASE + "/api/globalbad?p=1"
    PAGINATE = "next"
elif CASE == "reltime":
    URL_TMPL = BASE + "/api/reltime"
    PAGINATE = "number"
else:
    URL_TMPL = BASE + "/api/%s" % CASE
    PAGINATE = "number"

if PAGINATE_ENV:
    PAGINATE = PAGINATE_ENV

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockjson",
    "hash_exclude": HASH_EXCLUDE,
    "response": RESPONSE,               # ← 阶段3 的开关（非法值由引擎直接判失败）
    "paginate": PAGINATE,
    "max_pages": 20,

    "url_template": URL_TMPL,
    "page_start": 1,
    "page_end": PAGES,

    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 3,
    "retries": 1,
    "backoff": 1.0,

    "respect_robots": False,
    "dedup_key": "detail_url",

    "detail": {"enabled": False},

    "json": {
        "method": "POST" if CASE == "post" else "GET",
        "params": ({} if PAGINATE == "next" else {"page": "{page}"}),
        "form_body": ({"page": "{page}", "from": "test", "size": "3"}
                      if CASE == "post" else None),
        "headers": {"Accept": "application/json"},
        "list_path": "data.items",
        # 接口字段名 → 我方字段名；detail_url 以 _url 结尾，相对地址会自动补全
        "field_map": {
            "title": "name",
            "detail_url": "link",
            "publish_date": "created",
        },
        "ok_path": "code",
        "ok_value": 0,
        "total_path": "data.total",
        "total_scope": (TOTAL_SCOPE if TOTAL_SCOPE else "global"),
        "next_path": ("data.next" if CASE in ("next", "globalbad") else ""),
        "cursor_path": ("data.next_cursor" if CASE in ("cursor", "cursor0") else ""),
        "cursor_req_key": "cursor",
        "single_page": SINGLE,
        "cursor_end_value": (CURSOR_END if CURSOR_END else None),
    },

    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


# JSON 模式下引擎不需要 parse_list；留一个明确的空实现，说明"这个站没有解析代码"。
def parse_list(html, page_url):
    raise RuntimeError("mockjson 是 JSON 站点，不应该调用 parse_list")