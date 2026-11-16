# -*- coding: utf-8 -*-
"""A6：把散在 4 处的"页码判定"统一到 beyond_declared() / page_done()。

纯重构：判定表达式换名，执行顺序、副作用、计数一律不动。
"""
import re
from pathlib import Path

P = Path(r"D:\agent-work\crawlers\crawler.py")
t = P.read_text(encoding="utf-8")
before = t

# 1) 超限判定：isinstance(p, int) and p > X  →  beyond_declared(p, X)
pat_p = re.compile(r"isinstance\(p, int\) and p > (\w+)")
n1 = len(pat_p.findall(t))
t = pat_p.sub(r"beyond_declared(p, \1)", t)

# 2) 超限判定：isinstance(page, int) and page > ctx["pages_declared"]
pat_page_ctx = re.compile(r'isinstance\(page, int\) and page > ctx\["pages_declared"\]')
n2 = len(pat_page_ctx.findall(t))
t = pat_page_ctx.sub('beyond_declared(page, ctx.get("pages_declared"))', t)

# 3) 超限判定：isinstance(page, int) and page > M
pat_page_m = re.compile(r"isinstance\(page, int\) and page > (\bM\b)")
n3 = len(pat_page_m.findall(t))
t = pat_page_m.sub(r"beyond_declared(page, \1)", t)

# 4) 断点跳过：page in pages_done（只改循环里那一处判定）
old_skip = "if paginate == \"number\" and page in pages_done:"
n4 = t.count(old_skip)
t = t.replace(old_skip, "if paginate == \"number\" and page_done(page, pages_done):")

P.write_text(t, encoding="utf-8")
print("替换：p>X %d 处 / page>ctx %d 处 / page>M %d 处 / 循环跳过 %d 处"
      % (n1, n2, n3, n4))
print("字符 %d → %d" % (len(before), len(t)))
# 残留检查
left = [m for m in re.finditer(r"isinstance\([^)]*, int\) and \w+ >", t)]
print("残留旧写法:", len(left))
for m in left[:5]:
    print("   ...", t[max(0, m.start() - 50):m.start() + 40].replace("\n", " "))