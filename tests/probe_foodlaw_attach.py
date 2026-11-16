# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""离线勘察：foodlaw 详情页样本里有没有附件链接（不发任何网络请求）。"""
import re
from pathlib import Path

p = Path(str(_HOME / "crawlers" / "_baseline_v1" / "samples" / "_foodlaw_detail1.html"))
s = p.read_text(encoding="utf-8", errors="replace")
print("html bytes:", len(s))

hrefs = re.findall(r"""href=["']([^"']+)["']""", s)
print("href total:", len(hrefs))

kw = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar",
      "down", "file", "attach", "fujian")
hits = [h for h in hrefs if any(k in h.lower() for k in kw)]
print("可能是附件的链接:", len(hits))
for h in hits[:20]:
    print("  ", h)

for m in re.finditer("附件", s):
    seg = s[max(0, m.start() - 80):m.start() + 120].replace("\n", " ")
    print("  片段:", seg[:200])

# 看看 content 区域的 div 结构里有没有下载块
for m in re.finditer(r'class="[^"]*(down|attach|file|fj)[^"]*"', s, re.I):
    print("  class 命中:", m.group(0))