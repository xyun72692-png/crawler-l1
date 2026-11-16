# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""把 A6 与"8 种未断言状态"并入能力报告，并同步桌面副本。"""
import hashlib
import shutil
from pathlib import Path

SRC = Path(str(_HOME / "docs" / "爬虫能力报告-完整版-20261111.md"))
DST = Path(r"C:\Users\HUAWEI\Desktop\爬虫能力报告-完整版-20261111.md")

s = SRC.read_text(encoding="utf-8")
before = s

# ① 第七章 A 级表：A5 行后并列插入 A6
i = s.index("| **A5** |")
line_end = s.index("\n", i)
a6_row = (
    "\n| **A6** | **一页要不要抓的判定散在 4 处 → noop 会多抓一页** | "
    "`work` 列表 / 断点超限剔除 / `pages_done` 跳过 / M 夹紧，四处靠代码先后顺序配合。"
    "二跑时 1–5 页全跳过，第一个没被跳过的就是第 6 页 → 白抓一页 → `pages_ok=1` → 状态变 `success`（期望 `noop`） | "
    "抽成一个 `should_fetch(page)` 单一判定即可治；**但它治不了 A5** —— A5 是“新数据在第 1 页、第 1 页永远已完成”，两件事必须分开修 |"
)
s = s[:line_end] + a6_row + s[line_end:]

# ② A5 实测证据之后补一段并列说明 + 结构度量
anchor = "**如果这 3 天里真有新岗位，这一次是抓不到的。**"
assert anchor in s, "锚点缺失"
add = anchor + """

**A5 与 A6 必须并列看（别用一个盖住另一个）**

| 编号 | 症状 | 修法 | 治不治 A5 |
|---|---|---|---|
| A6 | 二跑多抓一页、状态从 `noop` 变 `success` | 抽 `should_fetch(page)` | **不治** |
| A5 | 二跑“看起来没新增”，其实新岗位就在第 1 页顶部 | `refresh` 模式（每次重抓 1..k 页、靠去重键过滤）或只用一次性快照 | 只有这条能治 |

**结构风险补充（2026-11-11 审计）**：引擎 `main()` **1143 行 / 近似复杂度 236 / 33 个 return**；
`finalize(status, reason)` 共 **27 种**组合，其中 **8 种从未被任何用例断言**
（`all_pages_blocked_by_robots` / `all_pages_failed` / `bad_paginate_mode` / `bad_total_scope` /
`empty_page_range` / `missing_parse_next` / `nothing_done` / `some_items_failed`）。
所以 **「130 项全绿」不等于「重构安全」**：动结构前先把这 8 条补成用例（→ **138 项**）。
详见 `docs/review-20261111-结构审计.md`。"""
s = s.replace(anchor, add, 1)

# ③ 修订记录追加一行
tail = "| 连带 2 | 14 章速查表 | 「增量」后面补「仅静态条件；滚动时间窗见 7 章 A5」 |"
assert tail in s, "修订记录表尾缺失"
s = s.replace(
    tail,
    tail + "\n| **A-5** | 7 章 A 级 + 本表 | 新增 **A6「一页要不要抓散在 4 处 → noop 多抓一页」**，与 A5 并列；补记结构度量与 **8 种未断言状态**（目标 138 项）；指向 `review-20261111-结构审计.md` |",
    1,
)

if s == before:
    print("!! 未命中任何替换")
else:
    SRC.write_text(s, encoding="utf-8", newline="\n")
    shutil.copyfile(SRC, DST)
    d = SRC.read_bytes()
    print("报告已更新: %d 行 / %d 字节 / MD5 %s"
          % (len(s.splitlines()), len(d), hashlib.md5(d).hexdigest()))
    print("桌面副本: %d 字节" % DST.stat().st_size)
    print("A6 存在:", "| **A6** |" in s, "| 138 提及:", "138" in s)