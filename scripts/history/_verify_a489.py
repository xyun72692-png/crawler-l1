# -*- coding: utf-8 -*-
"""核实 A4（去重战绩）/ A8（关键词文件统计）/ A9（清洗脚本去重范围）"""
import glob
import io
import json
import os
import re

print("=== A4：温州主站真实跑的 records_dup ===")
for f in sorted(glob.glob(r"D:\agent-work\out\reports\report-wzrc_dw_20261110-*.json")):
    d = json.load(open(f, encoding="utf-8"))
    st = d.get("stats") or {}
    print("  %-46s status=%s/%s 新增=%s 重复丢弃=%s pages=%s/%s"
          % (os.path.basename(f)[:44], d.get("status"), d.get("reason"),
             st.get("records_new"), st.get("records_dup"),
             st.get("pages_ok"), st.get("pages_total")))

print()
print("=== A8：wzrc_kw*.jsonl 统计 ===")
tot = 0
nonempty = []
for f in sorted(glob.glob(r"D:\agent-work\data\raw\wzrc_kw*.jsonl")):
    n = sum(1 for line in io.open(f, encoding="utf-8") if line.strip())
    tot += n
    if n:
        nonempty.append((os.path.basename(f), n))
print("  文件数:", len(glob.glob(r"D:\agent-work\data\raw\wzrc_kw*.jsonl")))
print("  非空文件数:", len(nonempty), " 这些文件的条数合计:", sum(n for _, n in nonempty))
print("  全部条数（含 try）:", tot)
for name, n in nonempty:
    print("    %-32s %d" % (name, n))

print()
print("=== A9：清洗脚本里的二次去重 ===")
for p in [r"D:\agent-work\crawlers\clean_jobs_wz.py",
          r"D:\agent-work\crawlers\clean_jobs_yq.py"]:
    print(" ", os.path.basename(p))
    if not os.path.exists(p):
        print("    文件不存在")
        continue
    for i, line in enumerate(io.open(p, encoding="utf-8"), 1):
        if re.search(r"def dedup|norm_company|norm_title|re\.sub\(r\"\\s\+\"", line):
            print("    L%-4d %s" % (i, line.strip()[:96]))

print()
print("=== A9：通用 clean.py 的去重键 ===")
p = r"D:\agent-work\crawlers\clean.py"
for i, line in enumerate(io.open(p, encoding="utf-8"), 1):
    if re.search(r"dedup_key|DEDUP|去重", line):
        print("    L%-4d %s" % (i, line.strip()[:100]))