# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""把两个基线脚本的默认 BASE 从 v6 改到 v7（必须在重新冻结之前做）。"""
from pathlib import Path

for fn in ("baseline_snapshot.py", "verify_baseline.py", "baseline_compare.py"):
    p = Path(str(_HOME / "tests")) / fn
    s = p.read_text(encoding="utf-8")
    if "_baseline_v6_stageA" in s:
        p.write_text(s.replace("_baseline_v6_stageA", "_baseline_v7_stageB"),
                     encoding="utf-8", newline="\n")
        print(fn, "→ 默认基线改为 v7")
    else:
        print(fn, "（未提 v6，跳过）")