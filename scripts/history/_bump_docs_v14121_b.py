# -*- coding: utf-8 -*-
"""清掉两份报告里剩下的旧数字（第二遍）。"""
import hashlib
from pathlib import Path

DOCS = Path(r"D:\agent-work\docs")
DESK = Path(r"C:\Users\HUAWEI\Desktop")

FULL = "爬虫能力报告-完整版-20261111.md"
HUMAN = "爬虫能力说明-给你的版本-20261112.md"


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


FULL_PAIRS = [
    ("314 项（六套件），任何一项红了都不许往下走。",
     "318 项（六套件），任何一项红了都不许往下走。"),
    ("要么实现 `refresh` 模式（每次重抓 1..k 页靠去重键过滤，**未实现**），要么直接跑一次性快照——后者正是当前主场景。",
     "要么实现 `refresh` 模式（每次重抓 1..k 页靠去重键过滤 → **v14.12.1 已实现**：`coverage_mode=\"window\"`，每轮清空页码断点、只抓前 3 页、`seen_keys` 去重），要么直接跑一次性快照。"),
    ("| `_baseline_v14_11` | v14.11：**74 条受管**（v13.5.1 goal 必填 + wide 拒 A/D）/ 六套 **314 项**测试 | ✅ **现役** |",
     "| `_baseline_v14_12_1` | v14.12.1：**75 条受管**（A5 window 每轮重抓 + 阈值 15）/ 六套 **318 项**测试 | ✅ **现役** |\n| `_baseline_v14_11` | v14.11：74 条（v13.5.1 goal 必填 + wide 拒 A/D）/ 314 项 | 回滚用 |"),
]

HUMAN_PAIRS = [
    ("> **三十秒速览（2026-11-15 / v14.11）**", "> **三十秒速览（2026-11-15 / v14.12.1）**"),
    ("- 版本：**v14.11**（2026-11-15）", "- 版本：**v14.12.1**（2026-11-15）"),
    ("1. 跑 `tests\\test_crawler.py`（208 项）；全套六套件 314 项；",
     "1. 跑 `tests\\test_crawler.py`（212 项）；全套六套件 318 项；"),
    ("**基线**：v14.7 / **73 条受管** / 目录 76 文件（当时值；现在是 v14.11 / 74 条 / 314 项）",
     "**基线**：v14.7 / **73 条受管** / 目录 76 文件（当时值；现在是 v14.12.1 / 75 条 / 318 项）"),
    ("基线 v14.7：**73 条受管**（新增 tools/geo 四份 json）（当时值；现在是 v14.11 / 74 条 / 314 项）",
     "基线 v14.7：**73 条受管**（新增 tools/geo 四份 json）（当时值；现在是 v14.12.1 / 75 条 / 318 项）"),
    ("但注意：**文档写了不等于代码已经强制**；当前 v14.11 已强制 `--goal` 必填并拒绝 A/D 型 wide，不能再靠默认值。",
     "但注意：**文档写了不等于代码已经强制**；当前 v14.12.1 已强制 `--goal` 必填并拒绝 A/D 型 wide，不能再靠默认值。"),
]


def apply(name, pairs):
    s = DOCS / name
    t = s.read_text(encoding="utf-8")
    hit, miss = 0, []
    for a, b in pairs:
        if a in t:
            t = t.replace(a, b, 1)
            hit += 1
        else:
            miss.append(a[:50])
    s.write_text(t, encoding="utf-8")
    (DESK / name).write_text(t, encoding="utf-8")
    print("%-30s %d/%d  docs %s 桌面 %s 一致=%s"
          % (name[:28], hit, len(pairs), md5(s)[:12], md5(DESK / name)[:12],
             md5(s) == md5(DESK / name)))
    for m in miss:
        print("   !! 未命中：", m)


apply(FULL, FULL_PAIRS)
apply(HUMAN, HUMAN_PAIRS)

# 残留复核
print("\n===== 残留复核 =====")
for name in (FULL, HUMAN):
    h = (DOCS / name).read_text(encoding="utf-8")
    bad = [k for k in ("314 项", "引擎 208", "_baseline_v14_11（", "4190 行", "未实现")
           if k in h]
    print("%-30s 残留：%s" % (name[:28], bad or "无"))