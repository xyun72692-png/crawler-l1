# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""结构审计文档：补第八节"补测执行结果"（8 条已补齐 + v7 已冻）。"""
from pathlib import Path

p = Path(str(_HOME / "docs" / "review-20261111-结构审计.md"))
s = p.read_text(encoding="utf-8")

old_tail = (
    "3. `should_fetch()` 与 A5 已并列记入（报告第七章 A5 / A6）。\n"
    "4. 顺序不变：**明日快照 → 文档存档 → 交付 → 重构（v7）**。"
)
assert old_tail in s, "结尾锚点缺失"

new_tail = old_tail + """

---

## 八、补测执行结果（2026-11-11 17:01，本文件写完后当天补的）

8 条状态断言**已全部补齐**，测试 **130 → 138 项**，状态覆盖 **19/27 → 27/27**。

| 用例 | 状态 | rc | 触发方式 |
|---|---|---|---|
| 131 | `failed / all_pages_failed` | 4 | `/mix/p2`、`p3` 一律 500 |
| 132 | `partial / some_items_failed` | 3 | `/mix/p1` 正常 + `p2` 500 |
| 133 | `failed / all_pages_blocked_by_robots` | 4 | mock robots `forbid-all` |
| 134 | `failed / bad_paginate_mode` | 1 | `paginate="bogus"`（零请求） |
| 135 | `failed / bad_total_scope` | 1 | `json.total_scope="weird"` |
| 136 | `failed / empty_page_range` | 1 | `--page-from 5 --pages 3` |
| 137 | `failed / missing_parse_next` | 1 | next 模式 + 无 `parse_next`（零请求） |
| 138 | `noop / nothing_done` | 0 | next 模式二跑（断点说没有下一页） |

新增夹具：`sites/mockstates.py`（`MOCK_STATE` 切错误配置）、`sites/mocknonext.py`；
`tests/mock_site.py` 加 `/mix/pN.html` 路由。**引擎 `crawler.py` 未改一行。**

门禁：138/138 × 两轮；verify v7 `--strict` 51/51；compare 49 项全过；guard 12/12。
**基线已冻为 `_baseline_v7_stageB`**（v1~v6 一字未动）。

> 到这一步，"重构安全"的前提才真正成立：27 种状态全部有断言，改结构时任何一条判定被改坏都会立刻变红。
"""

p.write_text(s.replace(old_tail, new_tail, 1), encoding="utf-8", newline="\n")
print("审计文档已补第八节，字节:", p.stat().st_size)