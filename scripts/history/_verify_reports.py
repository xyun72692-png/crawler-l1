# -*- coding: utf-8 -*-
"""核对：out/reports 下有多少份报告真的带 pages_declared / coverage / truncated（顶层字段）"""
import glob
import json
import os

files = sorted(glob.glob(r"D:\agent-work\out\reports\report-*.json"))
print("报告总数:", len(files))

has_declared = []
has_coverage = []
has_truncated = []
in_stats_instead = []
bad = 0

TOP = ("pages_declared", "pages_planned", "pages_effective", "coverage", "truncated")
for f in files:
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        bad += 1
        continue
    if not isinstance(d, dict):
        bad += 1
        continue
    if d.get("pages_declared") is not None:
        has_declared.append(f)
    if d.get("coverage") is not None:
        has_coverage.append(f)
    if d.get("truncated") is not None:
        has_truncated.append(f)
    st = d.get("stats") or {}
    if st.get("pages_declared") is not None or st.get("coverage") is not None:
        in_stats_instead.append(f)

print("解析失败:", bad)
print("顶层 pages_declared 有值的:", len(has_declared))
for f in has_declared[-8:]:
    d = json.load(open(f, encoding="utf-8"))
    print("   %-46s declared=%s planned=%s eff=%s cov=%s trunc=%s status=%s/%s"
          % (os.path.basename(f)[:44], d.get("pages_declared"), d.get("pages_planned"),
             d.get("pages_effective"), d.get("coverage"), d.get("truncated"),
             d.get("status"), d.get("reason")))
print("顶层 coverage 有值的:", len(has_coverage))
print("顶层 truncated 有值的:", len(has_truncated))
print("写在 stats 里的:", len(in_stats_instead))
print()
print("=== 真实站（非 127.0.0.1）且带 declared 的报告 ===")
real = []
for f in has_declared:
    d = json.load(open(f, encoding="utf-8"))
    cfg = d.get("config") or {}
    url = str(cfg.get("url_template") or "")
    if "127.0.0.1" not in url and "localhost" not in url:
        real.append((f, d, url))
print("数量:", len(real))
for f, d, url in real[-10:]:
    print("   %-44s declared=%s cov=%s trunc=%s %s/%s"
          % (os.path.basename(f)[:42], d.get("pages_declared"), d.get("coverage"),
             d.get("truncated"), d.get("status"), d.get("reason")))
    print("        url=", url[:96])