# -*- coding: utf-8 -*-
"""对比插入前后 fence 数量，确认未闭合是否为我引入。"""
from pathlib import Path
import glob

FENCE = "`" * 3
for p in sorted(glob.glob(r"D:\agent-work\docs\_backup_20261115\plain_before_robots_*.md"))[-1:]:
    txt = Path(p).read_text(encoding="utf-8")
    n = sum(1 for l in txt.split("\n") if l.strip().startswith(FENCE))
    print("备份 %s → fence %d（偶数? %s）" % (Path(p).name, n, n % 2 == 0))

cur = Path(r"D:\agent-work\docs\爬虫能力说明-给你的版本-20261112.md").read_text(encoding="utf-8")
n2 = sum(1 for l in cur.split("\n") if l.strip().startswith(FENCE))
print("当前 → fence %d（偶数? %s）" % (n2, n2 % 2 == 0))