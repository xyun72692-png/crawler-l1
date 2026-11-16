# -*- coding: utf-8 -*-
"""用 v14_7 的冻结脚本生成本次 v14_8 的脚本（只改目标目录 + baseline.md 正文）。"""
from pathlib import Path

SRC = Path(r"D:\agent-work\tests\make_baseline_v14_7.py")
DST = Path(r"D:\agent-work\tests\make_baseline_v14_8.py")

t = SRC.read_text(encoding="utf-8")

# 1) 目标与上一版
t = t.replace('TARGET = AGENT / "crawlers" / "_baseline_v14_7"',
              'TARGET = AGENT / "crawlers" / "_baseline_v14_8"')
t = t.replace('PREV = AGENT / "crawlers" / "_baseline_v14_6"',
              'PREV = AGENT / "crawlers" / "_baseline_v14_7"')

# 2) 顶部 docstring
old_doc_head = '建立 _baseline_v14_7（v13.1：foodmate 接入 + 扩展白名单）。'
new_doc_head = '建立 _baseline_v14_8（v13.5：discover.py 加判型 --mode）。'
assert old_doc_head in t
t = t.replace(old_doc_head, new_doc_head, 1)

# 3) baseline.md 正文（整块替换）
start = t.index('BASELINE_MD = r"""')
end = t.index('"""', start + len('BASELINE_MD = r"""')) + 3
new_md = '''BASELINE_MD = r"""# 基线 v14.8（2026-11-15 冻结 · 发现阶段补「判型 --mode」）

## 这一版新增

| 内容 | 说明 |
|---|---|
| `tools/discover.py --mode` | 判型落地：`single`（A/D 型，只跑第 0 步官方名录 + 给定 URL）/ `wide`（B 型，六步全跑，默认）/ `account`（C 型，零请求，先要账号） |
| 判型闸门 | `--mode single` 带 `--search-result` 或 `--from-enum` → **rc=2 明确拒绝**，不静默忽略；`account` 模式 0 请求、不写文件 |
| 步骤日志 | 每步带编号（第 0~5 步），single 模式下除第 0 步外一律不打印，便于按"日志里有没有第 2~5 步"做验收 |

## 行为边界（写死）

```
wide   与 v13.4 完全一致：同一组参数下候选 CSV 逐字节相同（已用 11 行 diff 验过）
single 只跑官方名录 + --seed；不跑检索 / 页脚 / 域名语法 / 枚举
account 零请求、零文件，只打印"要账号"三问
执行顺序未变：seed 仍在枚举之前（去重是"先出现者优先"，换序会改来源标记）
```

## 为什么判型要进代码

判型（A/B/C/D）此前只写在技能和方案里 —— 文档不是约束。典型浪费：
天气/法规/价格这类"单点权威"任务被当成 B 型，跑满六步去搜聚合站。
加 `--mode` 后，A/D 型第一次就能停下；C 型第一次就会反问你有没有账号。

## 门禁

```
test_crawler 208 ｜ test_discover 23 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 308 项
verify --strict ｜ baseline_compare 49 项 ｜ test_baseline_guard 12/12
```

## 回滚

```
上一版基线：crawlers\\_baseline_v14_7（73 条）
本版相对上一版的源码差异：只有 tools/discover.py 一个文件
"""'''
t = t[:start] + new_md + t[end:]

DST.write_text(t, encoding="utf-8")
print("已生成:", DST, len(t), "字符")
print("TARGET:", [l for l in t.splitlines() if l.startswith("TARGET")][0])
print("PREV  :", [l for l in t.splitlines() if l.startswith("PREV")][0])