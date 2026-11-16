# -*- coding: utf-8 -*-
"""对比两份完整版报告差异 + 校验方案文件两副本 MD5。"""
import hashlib, difflib
from pathlib import Path

def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()

pairs = [
    (r"C:\Users\HUAWEI\Desktop\方案-v13.4-发现阶段补搜索与官方平台-20261114.md",
     r"D:\agent-work\docs\方案-v13.4-发现阶段补搜索与官方平台-20261114.md"),
    (r"C:\Users\HUAWEI\Desktop\爬虫能力报告-完整版-20261111.md",
     r"D:\agent-work\docs\爬虫能力报告-完整版-20261111.md"),
]
for a, b in pairs:
    print("=" * 60)
    print("A:", a, Path(a).stat().st_size, md5(a))
    print("B:", b, Path(b).stat().st_size, md5(b))
    print("一致:", md5(a) == md5(b))

a = Path(pairs[1][0]).read_text(encoding="utf-8", errors="replace").splitlines()
b = Path(pairs[1][1]).read_text(encoding="utf-8", errors="replace").splitlines()
sm = difflib.SequenceMatcher(None, b, a)
print("\n--- 报告差异（D盘=基准 → 桌面=新版）---")
n = 0
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag == "equal":
        continue
    n += 1
    if n > 12:
        print("... 还有更多")
        break
    print("[%s] D盘 %d-%d → 桌面 %d-%d" % (tag, i1 + 1, i2, j1 + 1, j2))
    for line in a[j1:min(j2, j1 + 4)]:
        print("   +", line[:110])
    for line in b[i1:min(i2, i1 + 2)]:
        print("   -", line[:110])