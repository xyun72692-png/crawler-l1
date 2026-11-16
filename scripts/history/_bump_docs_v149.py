# -*- coding: utf-8 -*-
"""把两份报告的数字从 308/23 更新到 312/27，基线 v14_7 → v14_9（判型必填这一批）。"""
import hashlib
import re
from pathlib import Path

DOCS = Path(r"D:\agent-work\docs")
DESK = Path(r"C:\Users\HUAWEI\Desktop")
BAK = DOCS / "_backup_20261115"
BAK.mkdir(exist_ok=True)


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def pick(folder, kw):
    for p in Path(folder).iterdir():
        if p.suffix == ".md" and kw in p.name and ".bak" not in p.name:
            return p
    return None


RULES = [
    # 六套合计（多种写法）
    ("= 六套 312 项", "PLACEHOLDER"),          # 占位，真正替换在下面
]

# 逐条精确替换（顺序重要：先把带分量写法的换掉，再换裸 308）
PAIRS = [
    ("六套 308 项", "六套 312 项"),
    ("六套共 **308 项**", "六套共 **312 项**"),
    ("六套合计：208 + 23 + 21 + 21 + 17 + 18 = **308 项**",
     "六套合计：208 + 27 + 21 + 21 + 17 + 18 = **312 项**"),
    ("**308 项测试 × 两轮 + 四道门禁全过**（基线 v14.7 / 73 条）",
     "**312 项测试 × 两轮 + 四道门禁全过**（基线 v14.9 / 74 条）"),
    ("（引擎 208 + 发现 23 + Rule0 17 + identify 21 + transport 21 + render_batch 18）",
     "（引擎 208 + 发现 27 + Rule0 17 + identify 21 + transport 21 + render_batch 18）"),
    ("测试        308 项（引擎 208 + 发现 23 + 判定 21 + 传输 21 + Rule0 17 + 渲染 18）",
     "测试        312 项（引擎 208 + 发现 27 + 判定 21 + 传输 21 + Rule0 17 + 渲染 18）"),
    ("`_baseline_v14_7` | v14.7：**73 条受管**（+`tools/geo/*.json` 四份）/ 六套 308 项测试 | ✅ **现役** |",
     "`_baseline_v14_9` | v14.9：**74 条受管**（judge 判型必填 + --goal + 检索结果校验）/ 六套 312 项测试 | ✅ **现役** |"),
    ("/ 基线 `_baseline_v14_7`（73 条）/ 六套共 **308 项**测试",
     "/ 基线 `_baseline_v14_9`（74 条）/ 六套共 **312 项**测试"),
    ("| crawlers\\\\_baseline_v14_7 | **v14.7，现役**：73 条受管 / 308 项测试 | ✅ 用这个 |",
     "| crawlers\\\\_baseline_v14_9 | **v14.9，现役**：74 条受管 / 312 项测试 | ✅ 用这个 |"),
    # 兜底：剩余裸 308（带"项"字）
    ("308 项", "312 项"),
    ("test_discover 23", "test_discover 27"),
]

for kw in ("完整版", "给你的版本"):
    d = pick(DESK, kw)
    s = pick(DOCS, kw)
    if not s:
        print("跳过", kw)
        continue
    t = s.read_text(encoding="utf-8")
    before = len(re.findall(r"308", t))
    for a, b in PAIRS:
        if a in t:
            t = t.replace(a, b)
    after = len(re.findall(r"308", t))
    if d:
        bak = BAK / ("doc_" + kw + "_before_v149.md")
        if not bak.exists():
            bak.write_text(s.read_text(encoding="utf-8"), encoding="utf-8")
    s.write_text(t, encoding="utf-8")
    if d:
        d.write_text(t, encoding="utf-8")
    print("%-12s 308 残留 %d → %d ；桌面与 docs 同步 %d B / %s"
          % (kw, before, after, s.stat().st_size, md5(s)[:8]))