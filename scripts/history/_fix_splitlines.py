# -*- coding: utf-8 -*-
"""把三个脚本里的 .splitlines() 换成 .split("\\n")。

原因（2026-11-15 实测）：json.dumps(ensure_ascii=False) 不转义 U+2028/U+2029，
而 Python 的 str.splitlines() 会把它们当换行 → 4,683 行的文件被读成 4,695 行，
再 json.loads 就报 14 行"坏行"。数据本身没坏，是读法错了。
引擎自己用 `for line in f:`（按 \n 分行），clean.py 也是，所以生产链路安全。
"""
from pathlib import Path

TARGETS = [r"D:\agent-work\scripts\_health_jlrc.py",
           r"D:\agent-work\scripts\_analyze_jlrc.py",
           r"D:\agent-work\tools\build_jlrc_list.py"]

OLD_A = 'read_text(encoding="utf-8").splitlines()'
NEW_A = 'read_text(encoding="utf-8").split("\\n")'

for t in TARGETS:
    p = Path(t)
    s = p.read_text(encoding="utf-8")
    n = s.count(OLD_A) + s.count(".splitlines()")
    s = s.replace(OLD_A, NEW_A)
    s = s.replace(".splitlines()", '.split("\\n")')
    p.write_text(s, encoding="utf-8")
    print("%-42s 替换 %d 处" % (p.name, n))