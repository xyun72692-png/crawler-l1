# -*- coding: utf-8 -*-
"""生成 v14.12.1 冻结脚本（window 每轮重抓 + 阈值 15 + refresh_no_new）。"""
from pathlib import Path

SRC = Path(r"D:\agent-work\tests\make_baseline_v14_12.py")
DST = Path(r"D:\agent-work\tests\make_baseline_v14_12_1.py")

t = SRC.read_text(encoding="utf-8")
t = t.replace('TARGET = AGENT / "crawlers" / "_baseline_v14_12"',
              'TARGET = AGENT / "crawlers" / "_baseline_v14_12_1"')
t = t.replace('PREV = AGENT / "crawlers" / "_baseline_v14_11"',
              'PREV = AGENT / "crawlers" / "_baseline_v14_12"')
t = t.replace('建立 _baseline_v14_12（A5：window 模式断点加时间维度）。',
              '建立 _baseline_v14_12_1（A5 补丁：window 每轮重抓 + 阈值 15）。')

start = t.index('BASELINE_MD = r"""')
end = t.index('"""', start + len('BASELINE_MD = r"""')) + 3
new_md = '''BASELINE_MD = r"""# 基线 v14.12.1（2026-11-15 冻结 · A5 补丁：window 每轮重抓）

## 为什么有这一版（v14.12 的问题）

v14.12 的 window 只做到「**跨天**作废」。同一天第二次跑时，第 1 页在这一轮之前刚被抓过、
日期戳还是今天 → 仍然"有效" → 又被跳过 → **一个请求都不发**。
病根没除，只是把复发周期从"每次"推到了"每天一次"。

## 这一版改了什么

| # | 内容 | 落点 |
|---|---|---|
| 1 | window **每轮清空 pages_done** | `load_state()` 之后无条件 `pages_done = set()`；同一天第二次跑也重抓 |
| 2 | 阈值 `refresh_stop_after_dups` 20 → **15** | `refresh_pages=3` × 5 条/页 = 15 条，正好够得着（20 时永远不触发） |
| 3 | 提前停检查移到 `pages_ok += 1` **之后** | 否则提前停的那一页不算"处理完"，计数少一页 |
| 4 | `refresh_no_new` 进白名单 | 它是 window 的正常收工（这轮没新数据），不是翻页异常，不能被判 partial |
| 5 | success 时带出 `refresh_no_new` | 报告 reason 能看到"为什么提前收工" |
| 6 | 夹具新增 `/v5/pN.html`（每页 5 条） | 默认 v1 每页 3 条，3 页才 9 条，够不到 15 |

## 语义（写死）

```
window：每轮清空页码断点 → 重抓前 refresh_pages 页 → 靠 seen_keys 去重
        "覆盖不全"是设计如此；没新数据时 status=success + reason=refresh_no_new
full  ：完全没有时间维度，照常续跑（用例 210 钉死）
seen_keys 不清（它跟页码无关，是真正的"抓过没有"）
```

## 四条 A5 用例

```
209  window 跨天        → 断点作废、第 1 页重抓（跳过=0）
210  full 跨天          → 断点保留、照旧 noop（window 不污染 full）
211  window 同天连跑两次 → 第二次 total=3 / ok=3 / skipped=0 / new=0，不是 noop
212  3 页全重复          → reason=refresh_no_new、dup=15、ok=3、仍 success
```

## 门禁

```
test_crawler 212 ｜ test_discover 29 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 318 项
```

## 回滚

```
上一版基线：crawlers\\_baseline_v14_12（75 条）
本版源码差异：crawlers/crawler.py + sites/wzrc_inc.py + sites/mockwindow.py + tests/mock_site.py + tests/test_crawler.py
A5 之前的引擎：crawlers\\_baseline_v14_11\\code\\crawler.py
"""'''
t = t[:start] + new_md + t[end:]
DST.write_text(t, encoding="utf-8")
print("已生成:", DST.name)
print([l for l in t.splitlines() if l.startswith(("TARGET", "PREV"))])