# -*- coding: utf-8 -*-
"""改后自检：列出全文所有 ✅，人工判断是否都有证据；并扫残留错误表述。"""
import io
import re

P = r"D:\agent-work\docs\爬虫能力报告-完整版-20261111.md"
lines = io.open(P, encoding="utf-8").read().split("\n")

print("总行数:", len(lines))
print()
print("=== 全文 ✅ 所在行（共 %d 处）===" % sum(1 for l in lines if "✅" in l))
for i, l in enumerate(lines, 1):
    if "✅" in l:
        print("L%-4d %s" % (i, l.strip()[:120]))

print()
print("=== 残留错误表述扫查 ===")
pat = {
    "success / noop": r"success\s*/\s*noop",
    "failed / cooldown_file_corrupt": r"failed\s*/\s*cooldown_file_corrupt",
    "36.7": r"36\.7",
    "109 页": r"109\s*页",
    "只看前 2 页": r"只看前\s*2\s*页",
    "122 项": r"122\s*项",
    "data\\clean 当唯一": r"data\\clean\\\*\.xlsx` / `\.csv",
    "IPv6 当好事": r"IPv6——地址池巨大",
    "这才是爬虫真正的价值": r"这才是\"爬虫\"真正的价值",
    "抓 40 页": r"抓了\s*40\s*页",
}
for name, p in pat.items():
    hits = [i for i, l in enumerate(lines, 1) if re.search(p, l)]
    print("  %-28s %s" % (name, ("仍在 L" + str(hits)) if hits else "已清除"))

print()
print("=== 关键数字一致性 ===")
for k, p in [("3642 行", r"3642"), ("18 个模块", r"18 个"), ("126 项", r"126 项"),
             ("coverage=1.0", r"coverage=1\.0"), ("declared=5", r"pages_declared=5")]:
    print("  %-16s 出现 %d 次" % (k, sum(1 for l in lines if re.search(p, l))))