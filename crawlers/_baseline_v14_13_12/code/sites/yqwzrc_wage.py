# -*- coding: utf-8 -*-
"""
站点配置：温州人才网 · 乐清分站（yq.wzrc.net）高薪档全量职位

用途：双休标签（jobtag=147）只能覆盖主动勾了「双休」的企业，
      大量职位没勾标签但实际可能双休。因此再按【薪资档】抓一遍：
      拿到乐清分站全部高薪职位，本地再判双休，避免漏。

薪资档（勘察实测）：
      wage=60 → 5K~10K/月，72 页 × 5 条 ≈ 360 条
      wage=61 → 10K以上/月，9 页 × 5 条 ≈ 45 条
      （wage=59 是 3K~5K，低于 6K 门槛，不抓）

环境变量：
      YQWZRC_WAGE   薪资档码，默认 60
      YQWZRC_PAGES  结束页，默认 40（原 72，降载后收紧）

字段解析与 yqwzrc.py 完全一致（同一个站，同一套选择器）。
"""

import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ._common import TOTAL_PAGES_PATTERN
from .families.qscms74 import parse_jobs

BASE = "https://yq.wzrc.net"
WAGE = os.environ.get("YQWZRC_WAGE", "60")
PAGES = int(os.environ.get("YQWZRC_PAGES", "40"))   # 默认 40（原 72），防手滑跑满全站
WAGE_LABEL = {"56": "1K~1.5K", "57": "1.5K~2K", "58": "2K~3K", "59": "3K~5K",
              "60": "5K~10K", "61": "10K以上"}.get(WAGE, WAGE)

CONFIG = {
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "yqwzrc_wage" + WAGE,
    "url_template": BASE + "/index.php?m=&c=Jobs&a=jobs_list&wage=" + WAGE + "&page={page}",
    "paginate": "number",
    "page_start": 1,
    "page_end": PAGES,

    # 与 wzrc_all 对齐降载：实测约 150 次请求就被 IP 级限流，
    # 同一家站共用一把冷却锁，节奏也必须一致（3~5 秒、只重试 1 次）
    "delay_min": 3.0,
    "delay_max": 5.0,
    "timeout": 25,
    "retries": 1,
    "backoff": 2.0,

    "respect_robots": True,
    # v14.5：published 常见"30分钟前"这种相对时间，会随抓取时刻变；
    # 它不属于内容变化，排除出 content_hash（P1 会补 published_at 绝对时间）
    "hash_exclude": ["published"],
    "dedup_key": "detail_url",
    # 页面里 <span>1</span>/M页 → 声明总页数（读不到就按配置跑）
    "total_pages_pattern": TOTAL_PAGES_PATTERN,   # 唯一副本见 _common.py

    "detail": {"enabled": False},
    "attachments": {"enabled": False},

    # 软封判定：空页时用「双休第 1 页」做 canary（这页一定有结果）
    "soft_block": {
        "enabled": True,
        # canary 必须是"这个模块自己列表的第 1 页"：封禁若按栏目/路径生效，
        # 拿别的栏目的页当 canary 会误判成"还能出卡片"，从而漏判软封。
        "canary_url": BASE + "/index.php?m=&c=Jobs&a=jobs_list&wage=" + WAGE + "&page=1",
        "cooldown_sec": [7200, 21600, 86400],
        "group": "wzrc",
    },

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def parse_list(html, page_url):
    return parse_jobs(html, page_url,
                      source_site="温州人才网乐清分站(薪资档" + WAGE_LABEL + ")",
                      keep_area=False)
