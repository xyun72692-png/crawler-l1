# -*- coding: utf-8 -*-
"""v14.8 落地后同步文档与技能：方案 §九·补 标记已做；技能判型节补 --mode 命令。"""
from pathlib import Path

# ---------- 1) 方案 v13.4：§九·补 追加"已落地" ----------
plan = None
for p in Path(r"D:\agent-work\docs").iterdir():
    if p.suffix == ".md" and "v13.4" in p.name:
        plan = p
        break
assert plan, "找不到方案文件"
t = plan.read_text(encoding="utf-8")

MARK = "## 九·补、待办：`discover.py --mode`（2026-11-15 提出，未做）"
DONE = """## 九·补、**已完成**：`discover.py --mode`（2026-11-15 提出，2026-11-15 01:20 落地）

> 状态：**已实现并冻结 v14.8**（74 条受管）。以下保留原始设计，末尾附落地口径。

### 落地口径（2026-11-15）

```
--mode single    只跑第 0 步官方名录 + --seed 给定 URL
                 带 --search-result / --from-enum → rc=2 明确拒绝（不静默忽略）
--mode wide      六步全跑（默认），候选 CSV 与 v13.4 逐字节相同（11 行 diff 验过）
--mode account   零请求、零文件，只打印"要账号"三问，rc=0
执行顺序        seed 仍在枚举之前（去重是"先出现者优先"，换序会改来源标记）
```

验收（实跑）：

```
--mode single --region 浙江 --seed https://www.zjhr.com/
   输出只有：第 0 步 官方名录：2 个 / 给定 URL：1 个 / 判型 single 说明
   日志里 0 条"第 2~5 步"            ✅
--mode wide --region 江苏 --from-enum ... --b-sample 5 --limit 10
   候选 10 个，与改动前同参数输出完全一致（11 行 JSON/CSV 逐字节 diff）✅
--mode account                        rc=0，0 请求              ✅
--mode single --from-enum x.csv       rc=2 + 明确提示改用 wide   ✅
```

---

### 原始设计（保留）"""
assert MARK in t
t = t.replace(MARK, DONE, 1)
plan.write_text(t, encoding="utf-8")
print("方案已更新:", plan.name, len(t), "字符")

# ---------- 2) 技能 crawler-source-discovery：判型节补 --mode ----------
sk = Path(r"C:\Users\HUAWEI\.agents\skills\crawler-source-discovery\SKILL.md")
s = sk.read_text(encoding="utf-8")
ANCHOR = """**硬规矩**：

```
A / D 型：停在第 ① 步（官方名录 / 直接接口），不许往下跑 ②~⑤"""
NEW = """**判型已进代码（2026-11-15，`discover.py --mode`）**：

```bash
# A / D 型：只查官方名录 + 直接给 URL，不跑检索/页脚/域名/枚举
python tools/discover.py --region 浙江 --mode single --seed https://example.gov.cn/

# B 型（默认 wide）：六步全跑
python tools/discover.py --region 浙江 --industry 食品

# C 型：零请求，直接打印"要账号"三问
python tools/discover.py --mode account
```

`--mode single` 若同时带 `--search-result` / `--from-enum` → **rc=2 拒绝**（不是静默忽略）。
验收标准：single 的输出里不该出现"第 2~5 步"的日志。

**硬规矩**：

```
A / D 型：停在第 ① 步（官方名录 / 直接接口），不许往下跑 ②~⑤"""
assert ANCHOR in s
s = s.replace(ANCHOR, NEW, 1)
sk.write_text(s, encoding="utf-8")
print("技能已更新:", sk.name, len(s), "字符")