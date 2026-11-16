# -*- coding: utf-8 -*-
"""
站点配置：本地 mock 的"附件下载"测试站（只给 tests/test_crawler.py 用，不出网）。

阶段4 的样板：站点只在记录里给出 attachments（这里由 JSON 的 files 字段映射而来），
下载/robots/类型/大小/配额/SHA256 全部由引擎负责。

环境变量：
    MOCK_PORT                 mock 服务端口
    MOCKATTACH_CASE           ok / many / big / quota / robots / redir / mixed / noctype
    MOCKATTACH_ALLOW_PRIVATE  "1"=允许 127.0.0.1（测试必须开，生产保持关）
    MOCKATTACH_MAXFILE        单文件上限（字节）
    MOCKATTACH_MAXTOTAL       任务累计上限（字节）
    MOCKATTACH_MAXFILES       单条记录附件数上限
    MOCKATTACH_ROBOTS         "0"=不查附件 robots
"""

import os


def _port():
    v = (os.environ.get("MOCK_PORT") or "").strip()
    return v if v and v.lower() != "none" else "8765"


PORT = _port()
CASE = os.environ.get("MOCKATTACH_CASE", "ok")
ALLOW_PRIVATE = os.environ.get("MOCKATTACH_ALLOW_PRIVATE", "1") == "1"
ALLOW_HOSTS = os.environ.get("MOCKATTACH_ALLOW_HOSTS", "")     # 逗号分隔；非空则只认这些 host
MAXFILE = int(os.environ.get("MOCKATTACH_MAXFILE", "1048576"))
MAXTOTAL = int(os.environ.get("MOCKATTACH_MAXTOTAL", str(10 * 1024 * 1024)))
MAXFILES = int(os.environ.get("MOCKATTACH_MAXFILES", "5"))
CHECK_ROBOTS = os.environ.get("MOCKATTACH_ROBOTS", "1") == "1"
PAGES = int(os.environ.get("MOCKATTACH_PAGES", "1"))
RETRIES = int(os.environ.get("MOCKATTACH_RETRIES", "0"))
DELAY = float(os.environ.get("MOCKATTACH_DELAY", "0"))
TWO_PAGE = CASE == "twopage"
EXT_ALLOW = [x for x in os.environ.get("MOCKATTACH_EXT_ALLOW", "").split(",") if x]
SNIFF = os.environ.get("MOCKATTACH_SNIFF", "0") == "1"
CHECK_DNS = os.environ.get("MOCKATTACH_CHECK_DNS", "1") == "1"

BASE = "http://127.0.0.1:%s" % PORT
# 附件目录放在本用例的 data 目录下（case_env 会注入 CRAWLER_OUT_DIR）
ATT_DIR = os.path.join(os.environ.get("CRAWLER_OUT_DIR", r"D:\agent-work\data"), "_attachments")

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockattach",
    "response": "json",
    "paginate": "number",
    "url_template": BASE + ("/api/att2" if TWO_PAGE else "/api/att?case=%s" % CASE),
    "page_start": 1,
    "page_end": (PAGES if TWO_PAGE else 1),

    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 5,
    "retries": 1,
    "backoff": 1.0,

    "respect_robots": False,      # 列表接口本身不查（附件单独查）
    "dedup_key": "detail_url",

    "detail": {"enabled": False},

    "json": {
        "list_path": "data.items",
        "field_map": {"title": "name", "detail_url": "link", "attachments": "files"},
        "ok_path": "code", "ok_value": 0,
        "total_path": "data.total",
        "total_scope": "page",     # 这个接口的 total 是"本页条数"
        # 数字分页必须把 {page} 传给接口，否则每页都请求第 1 页
        "params": ({"page": "{page}"} if TWO_PAGE else {}),
    },

    "attachments": {
        "enabled": True,
        "dir": ATT_DIR,
        "max_files_per_record": MAXFILES,
        "max_total_bytes": MAXTOTAL,
        "max_file_bytes": MAXFILE,
        "timeout": 5,
        "retries": RETRIES,
        "respect_robots": CHECK_ROBOTS,
        "allow_private_hosts": ALLOW_PRIVATE,
        "allow_hosts": [h for h in ALLOW_HOSTS.split(",") if h],
        "ext_allow": EXT_ALLOW,
        "sniff_magic": SNIFF,
        "check_dns": CHECK_DNS,
        "delay_min": DELAY,
        "delay_max": DELAY,
    },

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def parse_list(html, page_url):
    raise RuntimeError("mockattach 是 JSON 站点，不应该调用 parse_list")