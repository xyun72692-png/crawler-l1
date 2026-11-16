# -*- coding: utf-8 -*-
"""A5 补丁：window 模式的 pages_planned 要反映"实际只计划 3 页"，不是 20。

不加这一条，报告会出现 pages_planned=20 而实际只跑 3 页 —— 报告与实际不符。
"""
from pathlib import Path

P = Path(r"D:\agent-work\crawlers\crawler.py")
t = P.read_text(encoding="utf-8")

old = '''            log("window 模式：本轮只看前 %d 页（第 %d–%d 页）"
                % (_cap, CONFIG["page_start"], _pe))'''
new = '''            log("window 模式：本轮只看前 %d 页（第 %d–%d 页）"
                % (_cap, CONFIG["page_start"], _pe))
            # 报告里的 pages_planned 必须跟着变小，否则"计划 20 页、实际 3 页"是假账
            ctx["pages_planned"] = _pe
            ctx["pages_effective"] = _pe'''
assert old in t
t = t.replace(old, new, 1)

# 后面那句无条件覆盖 pages_planned，要避开 window 已设的值
old2 = '''    ctx["pages_planned"] = CONFIG["page_end"]
    ctx["pages_effective"] = CONFIG["page_end"]'''
new2 = '''    if coverage_mode() != "window":      # window 模式下上面已按 refresh_pages 设过
        ctx["pages_planned"] = CONFIG["page_end"]
        ctx["pages_effective"] = CONFIG["page_end"]'''
assert old2 in t, "未找到 pages_planned 赋值"
t = t.replace(old2, new2, 1)

P.write_text(t, encoding="utf-8")
print("已打补丁：window 的 pages_planned 跟随 refresh_pages")