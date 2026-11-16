# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""
站点配置：温州人才网 · 乐清分站（yq.wzrc.net）双休职位列表

列表：https://yq.wzrc.net/index.php?m=&c=Jobs&a=jobs_list&jobtag=147&page=N
      jobtag=147 = 双休标签；wage=60(5K~10K)/61(10K以上)；education=65..69(初中..大专)
      实测：&jobtag=147 共 9 页，主列表 5 条/页（页面另有 9 条推荐位不计入）

robots.txt：404（未设限 = 允许抓取）。同系主站 www.wzrc.net 亦为 404。

列表卡片 div.J_jobsList（74cms 系），字段已在列表级齐备，故不抓详情页：
    .td-j-name a           职位名（文本带「乐清市 | 」前缀，需剥离）
    .td3 a                 公司名
    .td4                   薪资原文
    .td5                   发布时间
    .ltx .txt              学历：X | 经验：Y | 职位性质：Z | 人数：N | 地点：A/B/C
    .dlabs .dl             福利标签
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ._common import TOTAL_PAGES_PATTERN
from .families.qscms74 import parse_jobs

BASE = "https://yq.wzrc.net"
TAG_DOUBLE_WEEKEND = 147

CONFIG = {
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "yqwzrc",
    "url_template": BASE + "/index.php?m=&c=Jobs&a=jobs_list&jobtag=147&page={page}",
    "paginate": "number",
    "page_start": 1,
    "page_end": 9,

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
        "canary_url": BASE + "/index.php?m=&c=Jobs&a=jobs_list&jobtag=147&page=1",
        "cooldown_sec": [7200, 21600, 86400],
        "group": "wzrc",
    },

    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


def parse_list(html, page_url):
    return parse_jobs(html, page_url,
                      source_site="温州人才网乐清分站",
                      keep_area=False)
