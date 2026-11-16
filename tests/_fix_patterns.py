# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""修正站点模块的 total_pages_pattern（wzrc_all 缺失、三个 yq 被双重转义）。"""
from pathlib import Path

BASE = Path(str(_HOME / "crawlers" / "sites"))
# 正确的单反斜杠写法（文件里就是 r"</span>\s*/\s*(\d+)\s*页"）
GOOD = '    "total_pages_pattern": r"</span>\\s*/\\s*(\\d+)\\s*页",'
BAD = '    "total_pages_pattern": r"</span>\\\\s*/\\\\s*(\\\\d+)\\\\s*页",'

for n in ("wzrc_all.py", "yqwzrc.py", "yqwzrc_wage.py", "yqrc.py"):
    p = BASE / n
    s = p.read_text(encoding="utf-8")
    if BAD in s:
        s = s.replace(BAD, GOOD, 1)
        p.write_text(s, encoding="utf-8", newline="\n")
        print(n, "→ 修正双重转义")
        continue
    if '    "total_pages_pattern"' in s:
        print(n, "→ 已正确")
        continue
    anchor = '    "dedup_key": "detail_url",'
    assert anchor in s, n + " 找不到锚点"
    s = s.replace(anchor, anchor + "\n    # 页面里 <span>1</span>/M页 → 声明总页数（读不到就按配置跑）\n" + GOOD, 1)
    p.write_text(s, encoding="utf-8", newline="\n")
    print(n, "→ 已加入 pattern")