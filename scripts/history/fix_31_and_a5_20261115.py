# -*- coding: utf-8 -*-
"""修正两处：3.1 的「反自动化=放弃」例子；第七章 A5 的表述（易被读成没修）。"""
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

DOC = Path(r"D:\agent-work\docs\爬虫能力说明-给你的版本-20261112.md")
BAK = DOC.parent / "_backup_20261115"

EDITS = [
    # ① 3.1：把"反自动化=放弃"拆成两条（2026-11-15 按 16.10 实测纠正）
    (
        "| **⑤ 装了反自动化** | 打开后页面自己跳成空白、或弹验证 | **放弃，不绕过** | — | jrzp 那批城市站（列表页实测自毁） |",
        "| **⑤ 装了反自动化**（JS 自查调试器/CDP） | 打开后页面自己跳成空白 | **可过，但有痕迹**：拦掉那个检测脚本 + 用有头浏览器 | 中（对方日志会留下\"这个 js 加载失败\"） | jrzp 列表页（disable-devtool，实测可过） |\n"
        "| **⑥ 登录墙 / 防火墙挑战** | 第 1 页能看、翻页弹登录；或整站任何路径都返回同一个验证页 | **放弃，不绕过** | — | jrzp 第 3 道锁（翻页要登录）、拉勾（WAF 滑块页） |",
    ),
    # ② 3.1 下面那句结论
    (
        "**① ② 可以直接答应；③ 渲染通道已就绪、但还没有验证过的站；④ 要能解析表格（已做过）；⑤ 直接放弃。**",
        "**① ② 可以直接答应；③ 渲染通道已就绪、但还没有验证过的站；④ 要能解析表格（已做过）；⑤ 能过但有痕迹；⑥ 直接放弃。**\n\n"
        "> ⑤ 和 ⑥ 必须分开看，这是 2026-11-14/15 在 jrzp 上实测踩出来的：\n"
        "> **反自动化本身能过**（它只是页面里一个独立脚本，拦掉就失效），真正过不去的是**它后面那道登录墙**。\n"
        "> 把两件事混成一句\"反自动化就放弃\"，会白扔掉本来能抓的站。",
    ),
    # ③ A5：让"已修"出现在最前面，和 A6 的写法一致
    (
        "| **A5** | **滚动时间窗任务曾因页码断点看不到新数据** | 网址里没有具体日期（\"最近 3 天\"这种相对天数），筛选条件指纹永远不变 → 断点永久保留。而新岗位出现在第 1 页顶部（按更新时间倒序），第 1 页永远\"已完成\" → **不会再抓** | 这类任务不能用页码断点做增量。①每次重抓前几页、靠去重过滤新岗位 → **已实现**（v14.12.1「window 模式」：每轮清空页码断点、只抓前 3 页、靠已抓过的清单去重）②或者直接跑一次性快照 |",
        "| **A5** | **滚动时间窗任务曾因页码断点看不到新数据** | 网址里没有具体日期（\"最近 3 天\"这种相对天数），筛选条件指纹永远不变 → 断点永久保留。而新岗位出现在第 1 页顶部（按更新时间倒序），第 1 页永远\"已完成\" → **不会再抓** | **已修**（v14.12.1「window 模式」：每轮清空页码断点、只抓前 3 页、靠已抓过的清单去重，连续 15 条都见过就提前停）。这类任务改用 window，或直接跑一次性快照 |",
    ),
]


def main():
    src = DOC.read_text(encoding="utf-8")
    out = src
    fails = []
    for i, (old, new) in enumerate(EDITS, 1):
        n = out.count(old)
        if n != 1:
            fails.append((i, n))
            continue
        out = out.replace(old, new, 1)
    if fails:
        print("[FAIL] 未命中：", fails)
        return 1

    BAK.mkdir(parents=True, exist_ok=True)
    bak = BAK / ("plain_before_31fix_%s.md" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DOC, bak)
    DOC.write_text(out, encoding="utf-8", newline="\n")

    raw = DOC.read_bytes()
    print("[OK] 3 处已改")
    print("     %d 字节 | %d 行 | MD5 %s" % (len(raw), out.count("\n"), hashlib.md5(raw).hexdigest().upper()))
    print("     备份 %s" % bak.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())