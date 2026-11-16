# -*- coding: utf-8 -*-
"""对比两份「给你的版本」报告差异（自动匹配文件名，避开 GBK 通配符坑）。"""
import difflib
from pathlib import Path

def find(dirpath, kw):
    for p in Path(dirpath).iterdir():
        if p.suffix == ".md" and kw in p.name:
            return p
    return None

a = find(r"C:\Users\HUAWEI\Desktop", "给你的版本")
b = find(r"D:\agent-work\docs", "给你的版本")
print("桌面:", a, a.stat().st_size if a else None)
print("D盘 :", b, b.stat().st_size if b else None)
if not a or not b:
    raise SystemExit("找不到文件")

ta = a.read_text(encoding="utf-8", errors="replace").splitlines()
tb = b.read_text(encoding="utf-8", errors="replace").splitlines()
print("行数 桌面=%d D盘=%d" % (len(ta), len(tb)))
sm = difflib.SequenceMatcher(None, tb, ta)
n = 0
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag == "equal":
        continue
    n += 1
    if n > 10:
        print("... 更多差异省略")
        break
    print("[%s] D盘 %d-%d -> 桌面 %d-%d" % (tag, i1 + 1, i2, j1 + 1, j2))
    for line in ta[j1:min(j2, j1 + 3)]:
        print("   +", line[:100])
    for line in tb[i1:min(i2, i1 + 3)]:
        print("   -", line[:100])