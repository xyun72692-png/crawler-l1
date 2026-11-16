# -*- coding: utf-8 -*-
"""生成 v14.12 冻结脚本（A5：window 模式的时间维度断点）。"""
from pathlib import Path

SRC = Path(r"D:\agent-work\tests\make_baseline_v14_11.py")
DST = Path(r"D:\agent-work\tests\make_baseline_v14_12.py")

t = SRC.read_text(encoding="utf-8")
t = t.replace('TARGET = AGENT / "crawlers" / "_baseline_v14_11"',
              'TARGET = AGENT / "crawlers" / "_baseline_v14_12"')
t = t.replace('PREV = AGENT / "crawlers" / "_baseline_v14_11"',
              'PREV = AGENT / "crawlers" / "_baseline_v14_11"')
t = t.replace('建立 _baseline_v14_11（v13.5.1 补丁：--goal 全模式必填 + wide 拒 A/D goal）。',
              '建立 _baseline_v14_12（A5：window 模式断点加时间维度）。')

start = t.index('BASELINE_MD = r"""')
end = t.index('"""', start + len('BASELINE_MD = r"""')) + 3
new_md = '''BASELINE_MD = r"""# 基线 v14.12（2026-11-15 冻结 · A5：断点加时间维度）

## 这一版解决什么问题（A5）

```
滚动时间窗（settr=3 + sort=rtime）+ 页码断点 = 永远看不到新数据
  新岗位永远出现在第 1 页顶部
  而第 1 页永远"已完成" → 跳过 → 一个请求都不发
```

## 改了什么（最小版，六件）

| # | 内容 | 落点 |
|---|---|---|
| 1 | `pages_done` 加日期戳 | `st["pages_done_at"] = {页码: 'YYYY-MM-DD'}`；`blank_state()` 补默认键 |
| 2 | window 跨天作废，full 保持续跑 | `load_state()` 之后、`pages_done = set(...)` 之后判 `coverage_mode()` |
| 3 | 每次只重抓前 3 页 | `work` 构造时 `page_end = min(page_end, page_start + refresh_pages - 1)` |
| 4 | `seen_keys` 去重 | 复用既有去重前置（未改） |
| 5 | 连续 N 条都见过就提前停 | 跨页累计 `window_consec_dup`，达 `refresh_stop_after_dups` → `stop_reason=refresh_no_new` |
| 6 | 跨天后第 1 页必须重抓 | 用例 209（window）/ 210（full 对照） |

## 语义边界（别搞混）

```
window：断点只认「当天」，跨天作废；覆盖不全属设计如此（不给 coverage=1.0 的假象）
full  ：完全没有时间维度，照旧续跑（用例 210 钉死这一点，window 不污染 full）
```

**阈值 20 的数学提醒**：`refresh_pages=3` × 5 条/页 = 15 条 < 20，
所以当前配置下"连续 20 条提前停"**不会触发**；它是把 refresh_pages 调大时的安全阀。

## 站点配置

`wzrc_inc`：`coverage_mode="window"` + `refresh_pages=3` + `refresh_stop_after_dups=20`。
（11-11 曾裁定"不配 coverage_mode"，那针对一次性快照语义；11-15 按滚动时间窗改判，注释已写清。）

## 新增夹具

`crawlers/sites/mockwindow.py`：与 `mock.py` 同一个假站，只多三个 window 配置项。
它是 window 语义的唯一可执行说明书；`terms_status` 必须显式写（Rule 0 静态检查看不见继承）。

## 门禁

```
test_crawler 210 ｜ test_discover 29 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 316 项
```

## 回滚

```
上一版基线：crawlers\\_baseline_v14_11（74 条）
本版源码差异：crawlers/crawler.py（A5 六处）+ sites/wzrc_inc.py + sites/mockwindow.py（新）+ tests/test_crawler.py
A5 之前的引擎：crawlers\\_baseline_v14_11\\code\\crawler.py
"""'''
t = t[:start] + new_md + t[end:]
DST.write_text(t, encoding="utf-8")
print("已生成:", DST.name)
print([l for l in t.splitlines() if l.startswith(("TARGET", "PREV"))])