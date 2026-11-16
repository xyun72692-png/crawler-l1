# -*- coding: utf-8 -*-
"""把 crawler-site-onboarding 的数字从 v14.7/308/23 更新到 v14.9/312/27。"""
from pathlib import Path

P = Path(r"C:\Users\HUAWEI\.agents\skills\crawler-site-onboarding\SKILL.md")
t = P.read_text(encoding="utf-8")
orig_len = len(t)

PAIRS = [
    ("> 现行基线 **`crawlers\\_baseline_v14_7`**：**73 条受管 / 308 项测试**（六套件）；站点模块 **24 个**",
     "> 现行基线 **`crawlers\\_baseline_v14_9`**：**74 条受管 / 312 项测试**（六套件）；站点模块 **24 个**"),
    ("→ v14_3_1(68) → **v14_7(73)**。",
     "→ v14_3_1(68) → v14_7(73) → v14_8(74) → **v14_9(74)**。"),
    ("308 项测试（六套件：test_crawler 208 / test_discover 23 / test_identify 21 / test_transport 21 / test_rule0 17 / test_render_batch 18）",
     "312 项测试（六套件：test_crawler 208 / test_discover 27 / test_identify 21 / test_transport 21 / test_rule0 17 / test_render_batch 18）"),
    ("# 只跑这一套属于漏检：另外五套也要跑（合起来 308 项）",
     "# 只跑这一套属于漏检：另外五套也要跑（合起来 312 项）"),
    ("当前活跃基线 **`crawlers\\_baseline_v14_7`**：**73 条受管 / 308 项测试**；v1~v14_7 全部保留",
     "当前活跃基线 **`crawlers\\_baseline_v14_9`**：**74 条受管 / 312 项测试**；v1~v14_9 全部保留"),
]

n = 0
for a, b in PAIRS:
    if a in t:
        t = t.replace(a, b)
        n += 1
    else:
        print("  !! 未匹配：", a[:60])

P.write_text(t, encoding="utf-8")
print("替换 %d/%d 处；%d → %d 字符" % (n, len(PAIRS), orig_len, len(t)))
print("残留 308:", t.count("308"), "| 残留 v14_7:", t.count("v14_7"), "| 残留 test_discover 23:", t.count("test_discover 23"))