# -*- coding: utf-8 -*-
"""
温州人才网系站点（74cms）共用的小工具。

为什么有这个文件：`total_pages_pattern` 原来在 5 个站点模块里各写一遍，
已经因此出过一次事故 —— 其中 4 个被写成 `\\s`（双重转义），正则静默匹配不上，
M 永远解析不出来，报告里 pages_declared 一直是 None，却没有任何报错。

现在只保留**一份**，站点模块统一 `from ._common import TOTAL_PAGES_PATTERN`。

约定：本文件以下划线开头，**不算"站点模块"**
（报告里的"N 个站点模块"只数业务站与假站，不数公共库）。
"""

import re

#: 页面里的「<span>1</span>/949页」→ 抓 949。
#: 注意：必须是单反斜杠。写成 r"</span>\\s*/..." 就永远匹配不上。
TOTAL_PAGES_PATTERN = r"</span>\s*/\s*(\d+)\s*页"


def parse_total_pages(html):
    """从页面文本里读出站点声明的总页数；读不到返回 None（不猜、不抛异常）。"""
    if not html:
        return None
    m = re.search(TOTAL_PAGES_PATTERN, html)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def pick(field_map, key):
    """从「学历：大专 | 经验：3年」这种解析出来的字典里取值，取不到返回空串。"""
    return (field_map.get(key) or "").strip()