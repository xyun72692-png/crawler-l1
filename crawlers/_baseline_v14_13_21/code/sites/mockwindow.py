# -*- coding: utf-8 -*-
"""A5 测试夹具：window 覆盖模式的假站（本地 mock，零外网）。

和 sites/mock.py 完全同一个假站，只多三个配置项：
  coverage_mode="window"          断点跨天作废
  refresh_pages=3                 每轮只看前 3 页
  refresh_stop_after_dups=20      连续 20 条都见过就提前停

为什么要单独一个夹具：crawler.py 用子进程跑，改不了父进程的 CONFIG，
所以只能靠"换站点模块"来切模式。跑完 A5 的用例后这个文件保留，
它是 window 语义的唯一可执行说明书。
"""
from .mock import CONFIG as _MOCK, parse_list as _parse_list, PORT  # noqa: F401

CONFIG = dict(_MOCK)
CONFIG.update({
    # 显式写一遍 terms_status：Rule 0 的防漏标检查是**静态读文件**找这个字面量，
    # 只靠 dict(_MOCK) 继承它是看不见的（T-R0-9 会报"缺 mockwindow.py"）。
    "terms_status": "allowed",
    "job": "mockwindow",
    # 用 /v5/ 路由：每页 5 条，对齐真实站 wzrc 的条数。
    # 这样"3 页 × 5 条 = 15 条"才够得着 refresh_stop_after_dups=15。
    "url_template": "http://127.0.0.1:%d/v5/p{page}.html" % PORT,
    "page_end": 5,               # 给足 5 页，好验证"只看前 3 页"
    "coverage_mode": "window",
    "refresh_pages": 3,
    "refresh_stop_after_dups": 15,
    # window 模式会按日期作废旧断点，"抓完整个结果集"不是它的目标
    "total_pages_pattern": None,
})

parse_list = _parse_list

__all__ = ["CONFIG", "parse_list", "PORT"]