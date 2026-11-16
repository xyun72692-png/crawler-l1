# -*- coding: utf-8 -*-
"""把 v14_10 脚本的目标目录、上一版、baseline.md 正文改对（A6 重构这一批）。"""
from pathlib import Path

P = Path(r"D:\agent-work\tests\make_baseline_v14_10.py")
t = P.read_text(encoding="utf-8")

t = t.replace('TARGET = AGENT / "crawlers" / "_baseline_v14_9"',
              'TARGET = AGENT / "crawlers" / "_baseline_v14_10"')
t = t.replace('PREV = AGENT / "crawlers" / "_baseline_v14_8"',
              'PREV = AGENT / "crawlers" / "_baseline_v14_9"')
t = t.replace("建立 _baseline_v14_9（v13.6：判型必填 + --goal 分类 + 检索结果校验）。",
              "建立 _baseline_v14_10（v13.7：A6 判定集中化，纯重构零行为变化）。")

start = t.index('BASELINE_MD = r"""')
end = t.index('"""', start + len('BASELINE_MD = r"""')) + 3
new_md = '''BASELINE_MD = r"""# 基线 v14.10（2026-11-15 冻结 · A6：判定集中化，纯重构）

## 这一版做了什么

**只重构，不改行为。** 312 项测试一项没动、全部通过。

| 内容 | 说明 |
|---|---|
| `beyond_declared(page, pages_declared)` | "页码是否超出站点声明的总页数 M" 的**唯一**判定点。原来这表达式散在 4 处（进循环前剔除 / 循环内发现 M 后剔除 / 两处 `pages_done.add` 前），改一处容易漏另外三处 |
| `page_done(page, pages_done)` | "断点里是否已完成"的**唯一**判定点。原来循环里直接写 `page in pages_done` |
| 替换 7 处调用 | 4 处 `p>X` + 2 处 `page>ctx["pages_declared"]` + 1 处循环跳过；字符 161,738 → 161,707 |

## 语义边界（写清楚，防止后来人误解）

```
beyond_declared  → 只决定「记不记断点 / 报不报覆盖率」，**不决定「这一页抓不抓」**
page_done        → 才决定「跳过还是发请求」；它不看 M
```

所以 noop 续跑仍会多发 1 个请求去确认 M —— 这是**已知代价**，属于 A6 里"不改行为"的保留项，
真正的修法在 A5（pages_done 加时间维度 + window 模式）那一批里一起处理。

## 为什么值得单独冻一版

判定散在 4 处时，"改判定"要同时改 4 个地方且必须保持一致；
集中成 2 个函数后，A5 改 window 模式只需改 `page_done()` 一处，测试能立刻告诉你有没有改坏。

## 门禁

```
test_crawler 208 ｜ test_discover 27 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 312 项
```

## 回滚

```
上一版基线：crawlers\\_baseline_v14_9（74 条）
本版源码差异：crawlers/crawler.py（只加两个谓词 + 换 7 处调用）
重构前的引擎副本：logs\\_crawler_before_a6.py
"""'''
t = t[:start] + new_md + t[end:]
P.write_text(t, encoding="utf-8")
print("已改:", P.name)
print([l for l in t.splitlines() if l.startswith(("TARGET", "PREV"))])