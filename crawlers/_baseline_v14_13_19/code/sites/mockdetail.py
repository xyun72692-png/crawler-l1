# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""
站点配置：本地 mock 的"详情阶段"测试站（只给 tests/test_crawler.py 用，不出网）。

它不是真实网站，专门用来验证 crawler.py 里【引擎通用详情流程】的行为：

    MOCKDETAIL_KIND   ok / fail / slow / forbid / nofield
                      列表页 /d/<kind>/p1.html 每页 20 条，
                      每条详情页 /detail/<kind>-<i> 的行为由 kind 决定。

    MOCKDETAIL_RATIO  max_fail_ratio 覆盖值（默认 0.5）
    MOCKDETAIL_PORT   mock 服务端口（默认 8765）
    MOCKDETAIL_ROBOTS "1" 时让详情阶段也检查 robots（配合 --robots deny-detail）

设计意图：这是"通用化"的样板 ——
站点模块只提供两件事：parse_list（列表怎么解析）、parse_detail（详情怎么解析）。
限速、超时、重试、退避、状态码、robots、失败计数、熔断，全在引擎里。
"""

import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup

def _port():
    """端口优先级：MOCK_PORT > MOCKDETAIL_PORT > 8765。脏值（空串/"None"）当没设置。"""
    for key in ("MOCK_PORT", "MOCKDETAIL_PORT"):
        v = (os.environ.get(key) or "").strip()
        if v and v.lower() != "none":
            return v
    return "8765"


KIND = os.environ.get("MOCKDETAIL_KIND", "ok")
RATIO = float(os.environ.get("MOCKDETAIL_RATIO", "0.5"))
PORT = _port()
MAX_ITEMS = int(os.environ.get("MOCKDETAIL_MAX_ITEMS", "0"))
CHECK_ROBOTS = os.environ.get("MOCKDETAIL_ROBOTS", "0") == "1"
BASE = "http://127.0.0.1:%s" % PORT

CONFIG = {
    # Rule 0（v14）：测试夹具（本地/假站），不涉及真实条款
    "terms_status": "allowed",
    "job": "mockdetail",
    "url_template": BASE + "/d/%s/p1.html" % KIND,
    "page_start": 1,
    "page_end": 1,

    # 测试要快：列表页间隔压到 0，重试 1 次
    "delay_min": 0.0,
    "delay_max": 0.0,
    "timeout": 3,
    "retries": 1,
    "backoff": 1.0,

    "respect_robots": CHECK_ROBOTS,
    "dedup_key": "detail_url",

        "attachments": {
        # 只在测试里打开（MOCKDETAIL_ATT=1）：验证第 2 段会顺带下载选中记录的附件
        "enabled": os.environ.get("MOCKDETAIL_ATT") in ("1", "bad"),
        "dir": os.path.join(os.environ.get("CRAWLER_OUT_DIR", str(_HOME / "data")),
                             "_attachments"),
        "max_files_per_record": 5,
        "max_total_bytes": 50 * 1024 * 1024,
        "max_file_bytes": 5 * 1024 * 1024,
        "timeout": 5,
        "retries": 1,
        "respect_robots": False,
        "allow_private_hosts": True,      # 测试用 127.0.0.1
        "ext_allow": [".pdf", ".docx"],
        "sniff_magic": False,
    },
"detail": {
        "enabled": True,
        "delay_min": 0.0,
        "delay_max": 0.0,
        "timeout": 2,          # 比 slow 的 3 秒短，保证会超时
        "retries": 1,
        "backoff": 1.0,
        "abort_on": [401, 403, 429, 451],
        "max_fail_ratio": RATIO,
        "required": ["pub"],
        "respect_robots": CHECK_ROBOTS,
        "max_items_per_page": MAX_ITEMS,
    },
    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


def parse_list(html, page_url):
    """列表页：<a class="dt" href="/detail/xxx">，detail_url 补成绝对地址。"""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for a in soup.select("a.dt"):
        href = a.get("href") or ""
        if not href:
            continue
        row = {
            "title": a.get_text(strip=True),
            "detail_url": urljoin(page_url, href),
        }
        _att_mode = os.environ.get("MOCKDETAIL_ATT")
        if _att_mode in ("1", "bad"):
            # 只给测试用：让这条记录带一个真附件地址，验证第 2 段会顺带下载
            base = "%s://%s" % (urlsplit(page_url).scheme, urlsplit(page_url).netloc)
            # bad = 指向一个 404，用来测“第 2 段附件失败 → partial/attachment_partial”
            row["attachments"] = [base + ("/files/missing.pdf" if _att_mode == "bad"
                                          else "/files/ok.pdf")]
        rows.append(row)
    return rows


def parse_detail(html):
    """详情页：<h1> 标题、<span class="pub"> 发布日期、<span class="st"> 状态。"""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.select_one("h1")
    pub = soup.select_one("span.pub")
    st = soup.select_one("span.st")
    return {
        "title": h1.get_text(strip=True) if h1 else "",
        "pub": pub.get_text(strip=True) if pub else "",
        "st": st.get_text(strip=True) if st else "",
    }