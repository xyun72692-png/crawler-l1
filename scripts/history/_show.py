# -*- coding: utf-8 -*-
import sys

sys.path.insert(0, r"D:\agent-work\crawlers")
import clean_jobs_yq as C

main, neg, edu_out, low, stats = C.build()
print("=== 主表 %d 条 ===" % len(main))
for i, r in enumerate(main, 1):
    print("%2d. %6d %-4s %-8s %-24s %-20s %s" % (
        i, int(r["_low"]), r["_edu_text"], r.get("exp_req") or "-",
        r["title"][:22], r["company"][:18], r["region"][:16]))

print()
print("=== 面议 %d 条 ===" % len(neg))
for i, r in enumerate(neg, 1):
    print("%2d. %-4s %-26s %-20s %s" % (
        i, r["_edu_text"], r["title"][:24], r["company"][:18], r.get("salary_raw")))

print()
print("=== 被学历剔除 %d 条 ===" % len(edu_out))
for i, r in enumerate(edu_out, 1):
    print("%2d. %-4s %-12s %-24s %s" % (
        i, r["_edu_text"], r.get("salary_raw", ""), r["title"][:22], r["company"][:18]))