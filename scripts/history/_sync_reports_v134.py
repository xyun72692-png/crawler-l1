# -*- coding: utf-8 -*-
"""把桌面上更新的两份报告同步到 docs（桌面 00:38 比 docs 00:31 新）。"""
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

DESK = Path(r"C:\Users\HUAWEI\Desktop")
DOCS = Path(r"D:\agent-work\docs")
BAK = DOCS / "_backup_20261115"
BAK.mkdir(exist_ok=True)
stamp = datetime.now().strftime("%H%M%S")


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


for kw in ("完整版", "给你的版本"):
    d = [p for p in DESK.iterdir() if p.suffix == ".md" and kw in p.name][0]
    s = [p for p in DOCS.iterdir() if p.suffix == ".md" and kw in p.name and ".bak" not in p.name][0]
    hd, hs = md5(d), md5(s)
    if hd == hs:
        print("%-14s 已一致  %s" % (kw, hd[:8]))
        continue
    shutil.copy2(s, BAK / ("docs_%s_%s.md" % (kw, stamp)))
    shutil.copy2(d, s)
    print("%-14s 桌面 %d B %s  ->  docs %d B %s（旧 docs 备份到 _backup_20261115）"
          % (kw, d.stat().st_size, hd[:8], s.stat().st_size, md5(s)[:8]))

print("\n同步后核对：")
for kw in ("完整版", "给你的版本"):
    d = [p for p in DESK.iterdir() if p.suffix == ".md" and kw in p.name][0]
    s = [p for p in DOCS.iterdir() if p.suffix == ".md" and kw in p.name and ".bak" not in p.name][0]
    print("  %-10s 桌面 %6d B %s | docs %6d B %s | 一致=%s"
          % (kw, d.stat().st_size, md5(d)[:8], s.stat().st_size, md5(s)[:8], md5(d) == md5(s)))