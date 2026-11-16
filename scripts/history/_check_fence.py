# -*- coding: utf-8 -*-
"""检查人话版代码块是否成对，并列出未闭合的位置。"""
from pathlib import Path

P = Path(r"D:\agent-work\docs\爬虫能力说明-给你的版本-20261112.md")
lines = P.read_text(encoding="utf-8").split("\n")

FENCE = "`" * 3
fences = [(i + 1, l.strip()) for i, l in enumerate(lines) if l.strip().startswith(FENCE)]
print("fence 行数:", len(fences), "| 成对?", len(fences) % 2 == 0)

# 逐段配对，找出落单的
open_at = None
unclosed = []
for n, l in fences:
    if open_at is None:
        open_at = n
    else:
        open_at = None
if open_at is not None:
    unclosed.append(open_at)
    print("未闭合的起始行:", open_at)
    for k in range(max(0, open_at - 4), min(len(lines), open_at + 3)):
        print("  %d| %s" % (k + 1, lines[k]))