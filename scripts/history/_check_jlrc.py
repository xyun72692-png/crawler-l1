# -*- coding: utf-8 -*-
"""检查 jlrc_try1 的 50 条：岗位名是否剥出来了、地理分布、字段空值率。"""
import json, collections
from pathlib import Path

p = Path(r"D:\agent-work\data\raw\jlrc_try1.jsonl")
rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
print("记录数:", len(rows))
print("\n前 6 条：")
for r in rows[:6]:
    print("  %-18s | %-26s | %-10s | %-6s | %s"
          % (r.get("title", "")[:18], r.get("company", "")[:26],
             r.get("salary", "")[:10], r.get("education", "")[:6], r.get("location", "")))

print("\n字段空值率：")
keys = ["title", "company", "salary", "education", "location", "treatment", "desc", "source_api_id"]
for k in keys:
    blank = sum(1 for r in rows if not str(r.get(k) or "").strip())
    print("  %-14s 空 %2d / %d" % (k, blank, len(rows)))

print("\n岗位名（title）分布 top15：")
for k, v in collections.Counter(r.get("title", "") or "(空)" for r in rows).most_common(15):
    print("  %-24s %d" % (k[:24], v))

print("\n省份分布（从 location 取省）：")
for k, v in collections.Counter((r.get("location", "").split("-")[0] or "(空)") for r in rows).most_common(12):
    print("  %-10s %d" % (k, v))

print("\n薪资分布 top8：")
for k, v in collections.Counter(r.get("salary", "") or "(空)" for r in rows).most_common(8):
    print("  %-16s %d" % (k[:16], v))

print("\n学历分布：")
for k, v in collections.Counter(r.get("education", "") or "(空)" for r in rows).most_common(8):
    print("  %-10s %d" % (k[:10], v))

# 食品相关命中
kw = ("食品", "检验", "检测", "品控", "化验", "质量", "QA", "QC", "微生物", "研发")
hit = [r for r in rows if any(k in (r.get("title", "") + r.get("company", "") + r.get("desc", "")) for k in kw)]
print("\n食品/检测相关命中: %d / %d" % (len(hit), len(rows)))
for r in hit[:8]:
    print("   %-20s | %-24s | %s" % (r.get("title", "")[:20], r.get("company", "")[:24], r.get("location", "")))