# -*- coding: utf-8 -*-
"""用 v14_8 的冻结脚本生成 v14_9（本轮：判型必填 + --goal + 检索结果校验）。"""
from pathlib import Path

SRC = Path(r"D:\agent-work\tests\make_baseline_v14_8.py")
DST = Path(r"D:\agent-work\tests\make_baseline_v14_9.py")

t = SRC.read_text(encoding="utf-8")
t = t.replace('TARGET = AGENT / "crawlers" / "_baseline_v14_8"',
              'TARGET = AGENT / "crawlers" / "_baseline_v14_9"')
t = t.replace('PREV = AGENT / "crawlers" / "_baseline_v14_7"',
              'PREV = AGENT / "crawlers" / "_baseline_v14_8"')
t = t.replace('建立 _baseline_v14_8（v13.5：discover.py 加判型 --mode）。',
              '建立 _baseline_v14_9（v13.6：判型必填 + --goal 分类 + 检索结果校验）。')

start = t.index('BASELINE_MD = r"""')
end = t.index('"""', start + len('BASELINE_MD = r"""')) + 3
new_md = '''BASELINE_MD = r"""# 基线 v14.9（2026-11-15 冻结 · 判型必填 + --goal + 检索结果校验）

## 这一版新增

| 内容 | 说明 |
|---|---|
| `--mode` 改为**必填** | 不给 → 0 请求 + 判型三问 + rc=2。**不再默认 wide**（默认跑六步等于没判型） |
| `--goal`（jobs/regulation/price/weather） | `--print-queries` 只出对应那一类；不给 goal → rc=2，不许把 14 条全吐 |
| 名录按 goal 过滤 | `from_gov_roster(goal=...)` 按 `kind` 过滤 —— 天气任务不会看到招聘站 |
| 检索有前提 | 只在 B 型（wide）跑；A/D 型只有"名录没命中且没给 seed"时才提示该检索（仍 0 请求） |
| `--search-result` 校验 | 嵌套 JSON 递归取 URL（字符串判断前置，深度 ≤8）；**解析 0 条 → rc=2**，不许显示成功 |
| `tests/test_discover.py` 23 → **27** | 新增 T28 天气给官方源不搜索 / T29 法规给官方平台不枚举 / T30 拼多多 0 请求 / T31 招聘 wide 必须检索 |

## 修掉的一个静默丢数据 bug

```
_iter_urls 原来把 `depth > 6` 放在最前面 —— 第 7 层的字符串直接被截断，
deep.items[].href 这种结构会"静默丢 URL"（实测 3 条只解出 2 条）。
现在字符串先判、不受深度限制。
```

## 口径（写死）

```
判型先于发现：不判型 → 0 请求，先问三个问题
A/D 停止条件：找到 1 个可信官方源或接口就停，不进页脚/域名/枚举
C  停止条件：直接问账号，0 搜索 0 发现
B  才跑六步
检索前提    ：没有候选源或不知道一手源时才检索；已知官方站/API 不检索
```

## 门禁

```
test_crawler 208 ｜ test_discover 27 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 312 项
```

## 回滚

```
上一版基线：crawlers\\_baseline_v14_8（74 条）
本版源码差异：tools/discover.py + tests/test_discover.py
"""'''
t = t[:start] + new_md + t[end:]
DST.write_text(t, encoding="utf-8")
print("已生成:", DST)
print([l for l in t.splitlines() if l.startswith(("TARGET", "PREV"))])