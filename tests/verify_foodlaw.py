# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""foodlaw page=1 逐条验收（对照用户给的通过标准）"""
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

RAW = str(_HOME / "data" / "raw" / "foodlaw.jsonl")
rows = [json.loads(l) for l in open(RAW, encoding="utf-8") if l.strip()]

print("=" * 66)
print("foodlaw page=1 验收：%d 条" % len(rows))
print("=" * 66)

def rate(name, ok, total, detail=""):
    flag = "PASS" if ok == total else "FAIL"
    print("  [%s] %-28s %d/%d  %s" % (flag, name, ok, total, detail))
    return ok == total

allpass = True

# 1. publish_date
n = sum(1 for r in rows if (r.get("publish_date") or "").strip())
allpass &= rate("有 publish_date", n, 20, "")

# 2. detail_url
n = sum(1 for r in rows if (r.get("detail_url") or "").strip())
allpass &= rate("有 detail_url", n, 20, "")

# 3. status_img
n = sum(1 for r in rows if (r.get("status_img") or "").strip())
allpass &= rate("有 status_img", n, 20, "")

# 4. 详情无静默失败
n = sum(1 for r in rows if r.get("detail_fetch") == "ok")
allpass &= rate("详情全部成功", n, 20,
                "" if n == 20 else "失败: " + str([r.get('title','')[:20] for r in rows if r.get('detail_fetch')!='ok']))

# 5. 无重复
urls = [r.get("detail_url") for r in rows]
n = len(set(urls))
allpass &= rate("detail_url 无重复", n, 20)

# 6. 日期格式
import re
bad = [r["publish_date"] for r in rows if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.get("publish_date", ""))]
allpass &= rate("publish_date 格式 YYYY-MM-DD", 20 - len(bad), 20, str(bad) if bad else "")

print()
print("=== 状态图片分布 ===")
c = Counter(r.get("status_img") for r in rows)
for k, v in c.most_common():
    sample = [r for r in rows if r.get("status_img") == k][0]
    print("  %-12s %2d 条   示例生效日期=%s" % (k, v, sample.get("effective_date")))

print()
print("=== xxyx / jjss 映射自检（生效日期 vs 今天 2026-11-10）===")
import datetime
today = "2026-11-10"
for img, expect in (("xxyx.gif", "<= today"), ("jjss.gif", "> today")):
    sub = [r for r in rows if r.get("status_img") == img]
    if not sub:
        continue
    viol = []
    for r in sub:
        eff = r.get("effective_date") or ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", eff):
            continue
        if expect == "<= today" and eff > today:
            viol.append((r["title"][:20], eff))
        if expect == "> today" and eff <= today:
            viol.append((r["title"][:20], eff))
    status = "PASS" if not viol else "FAIL"
    print("  [%s] %-10s %d 条，期望 %s，违反 %d 条 %s" %
          (status, img, len(sub), expect, len(viol), viol if viol else ""))
    allpass &= (not viol)

print()
print("=== jdxwj 条目（需人工核对图标文字）===")
for r in rows:
    if r.get("status_img") == "jdxwj.gif":
        print("  - 生效=%s 属性=%s" % (r.get("effective_date"), r.get("attr")))
        print("    %s" % r.get("title"))
        print("    %s" % r.get("detail_url"))

print()
print("=" * 66)
print("机器可验证项：%s" % ("全部通过" if allpass else "有未通过项"))
print("=" * 66)