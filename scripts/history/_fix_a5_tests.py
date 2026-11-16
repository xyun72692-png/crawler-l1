# -*- coding: utf-8 -*-
"""修 A5 测试插入：撤销误插、编号改 209/210、调用移到 main 开头。"""
from pathlib import Path

P = Path(r"D:\agent-work\tests\test_crawler.py")
t = P.read_text(encoding="utf-8")

# 1) 撤销误插（插到了 record(138...) 的参数中间）
bad = "    a5_cases()\n                  stt.get("
if bad in t:
    t = t.replace(bad, "                  stt.get(", 1)
    print("已撤销误插")

# 2) 编号 139/140 → 209/210（139 被 golden 组占用；最大现号 208）
t = t.replace('begin_case("c139")', 'begin_case("c209")')
t = t.replace('begin_case("c140")', 'begin_case("c210")')
t = t.replace('"139. A5 window', '"209. A5 window')
t = t.replace('"140. A5 full', '"210. A5 full')

# 3) 调用放到 main 开头（紧跟标题行之后），不再猜末尾位置
anchor = '''def main():
    print("v13 爬虫离线测试（0 请求）")'''
alt = '''def main():
    print("v14 爬虫离线测试（0 请求）")'''
if "    a5_cases()\n" not in t:
    if anchor in t:
        t = t.replace(anchor, anchor + "\n    a5_cases()", 1)
    elif alt in t:
        t = t.replace(alt, alt + "\n    a5_cases()", 1)
    else:
        # 兜底：找 def main(): 后第一行 print
        i = t.index("def main():")
        j = t.index("\n", t.index("print", i))
        t = t[:j + 1] + "    a5_cases()\n" + t[j + 1:]
    print("已在 main 开头插入调用")

P.write_text(t, encoding="utf-8")
print("209 用例:", "209. A5" in t, "| 210 用例:", "210. A5" in t)
print("调用次数:", t.count("    a5_cases()"))