# -*- coding: utf-8 -*-
"""生成 v14.11 冻结脚本（v13.5.1 补丁：--goal 全模式必填 + wide 拒 A/D goal）。"""
from pathlib import Path

SRC = Path(r"D:\agent-work\tests\make_baseline_v14_10.py")
DST = Path(r"D:\agent-work\tests\make_baseline_v14_11.py")

t = SRC.read_text(encoding="utf-8")
t = t.replace('TARGET = AGENT / "crawlers" / "_baseline_v14_10"',
              'TARGET = AGENT / "crawlers" / "_baseline_v14_11"')
t = t.replace('PREV = AGENT / "crawlers" / "_baseline_v14_9"',
              'PREV = AGENT / "crawlers" / "_baseline_v14_10"')
t = t.replace("建立 _baseline_v14_10（v13.7：A6 判定集中化，纯重构零行为变化）。",
              "建立 _baseline_v14_11（v13.5.1 补丁：--goal 全模式必填 + wide 拒 A/D goal）。")

start = t.index('BASELINE_MD = r"""')
end = t.index('"""', start + len('BASELINE_MD = r"""')) + 3
new_md = '''BASELINE_MD = r"""# 基线 v14.11（2026-11-15 冻结 · v13.5.1 补丁：goal 必填 + wide 拒 A/D 型）

## 这一版改了什么

| 内容 | 说明 |
|---|---|
| `--goal` 改为**所有模式必填** | 不给 → rc=2、0 请求、不写候选文件（原来只在 `--print-queries` 时必填） |
| `--mode wide` 拒绝 A/D 型 goal | `weather` / `regulation` 配 wide → rc=2，提示改用 single；要强制须显式 `--force-wide`，且输出留痕 |
| `tests/test_discover.py` 27 → **29** | T32 不给 goal（即使有 mode）→ rc=2、无文件；T33 A/D goal + wide → rc=2、无文件、提示 --force-wide |

## 为什么

```
goal 决定两件事：① 检索出哪一类模板 ② 官方名录按哪一类 kind 过滤。
不写 → 天气任务会被塞进招聘站和招聘模板，等于把判型的活推回给人。

weather / regulation 是 A/D 型（单点权威），跑六步是"大炮打蚊子"：
  天气：中央气象台 / 一个 API 就够
  法规：一手公报 1~3 个源
所以 wide 遇到它们直接拒；真要多源发现必须写 --force-wide（显式覆盖，不默认放行）。
```

## 门禁

```
test_crawler 208 ｜ test_discover 29 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 314 项
```

## 回滚

```
上一版基线：crawlers\\_baseline_v14_10（74 条）
本版源码差异：tools/discover.py + tests/test_discover.py
本版之前的引擎：crawlers\\_baseline_v14_10\\code\\crawler.py（A6 已含，本版未动引擎）
A6 之前的引擎：crawlers\\_baseline_v14_9\\code\\crawler.py
"""'''
t = t[:start] + new_md + t[end:]
DST.write_text(t, encoding="utf-8")
print("已生成:", DST.name)
print([l for l in t.splitlines() if l.startswith(("TARGET", "PREV"))])