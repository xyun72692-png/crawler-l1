# -*- coding: utf-8 -*-
"""jlrc 999 条画像：食品岗、薪资可用率、地理分布、岗位名质量。"""
import json, collections
from pathlib import Path

p = Path(r"D:\agent-work\data\raw\jlrc_p20.jsonl")
rows = [json.loads(l) for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]
n = len(rows)
print("总记录:", n)
print("公司数:", len(set(r["company"] for r in rows)))

def pct(a, b=n):
    return "%.1f%%" % (100.0 * a / b) if b else "0%"

# 地理
prov = collections.Counter((r["location"].split("-")[0] or "(空)") for r in rows)
print("\n省份分布:", dict(prov.most_common(8)))
jl_n = prov.get("吉林省", 0)
print("  吉林省内:", jl_n, pct(jl_n))

city = collections.Counter((r["location"].split("-")[1] if len(r["location"].split("-")) > 1 else "(空)") for r in rows)
print("  城市 top8:", dict(city.most_common(8)))

# 薪资 / 学历
sal_unknown = sum(1 for r in rows if r["salary"] in ("", "薪资不限"))
edu_none = sum(1 for r in rows if r["education"] in ("", "无要求"))
print("\n薪资 '不限/空':", sal_unknown, pct(sal_unknown))
print("学历 '无要求/空':", edu_none, pct(edu_none))

# 岗位名质量
other = sum(1 for r in rows if r["title"] in ("其他职位", "其他", ""))
print("\n岗位名是'其他职位/空':", other, pct(other))

# 食品/检测相关
KW = ("食品", "检验", "检测", "品控", "化验", "质量", "品管", "QA", "QC", "微生物",
      "理化", "实验室", "研发", "生产", "化验员")
title_hit = [r for r in rows if any(k in r["title"] for k in KW)]
all_hit = [r for r in rows if any(k in (r["title"] + r["company"] + r["desc"]) for k in KW)]
print("\n岗位名含关键词:", len(title_hit), pct(len(title_hit)))
print("任意字段含关键词（含公司名/描述）:", len(all_hit), pct(len(all_hit)))

print("\n岗位名命中明细（前 15 条）：")
for r in title_hit[:15]:
    print("  %-20s | %-22s | %-8s | %s"
          % (r["title"][:20], r["company"][:22], r["salary"][:8], r["location"]))

print("\n公司名含'食品':", sum(1 for r in rows if "食品" in r["company"]))

# 吉林省内 + 岗位名有效 + 有薪资 的交集
good = [r for r in rows if r["location"].startswith("吉林省")
        and r["title"] not in ("其他职位", "") and r["salary"] not in ("", "薪资不限")]
print("\n吉林省内 + 岗位名有效 + 有明确薪资:", len(good), pct(len(good)))
for r in good[:10]:
    print("  %-20s | %-22s | %-10s | %s" % (r["title"][:20], r["company"][:22], r["salary"], r["location"]))