# -*- coding: utf-8 -*-
"""数据可信度体检：抓得到 ≠ 数据真。统计灌水/错位特征。"""
import json, collections, re
from pathlib import Path

p = Path(r"D:\agent-work\data\raw\jlrc_p20.jsonl")
rows, bad = [], 0
for l in p.read_text(encoding="utf-8").split("\n"):
    l = l.strip()
    if not l:
        continue
    try:
        rows.append(json.loads(l))
    except Exception:
        bad += 1
print("行数 %d（坏行 %d）" % (len(rows), bad))

# 1) 一家公司挂了多少岗位
by_ent = collections.Counter(r["company"] for r in rows)
print("\n单公司岗位数 top10：")
for k, v in by_ent.most_common(10):
    print("  %-30s %d" % (k[:30], v))
multi = sum(1 for v in by_ent.values() if v >= 5)
print("  挂 ≥5 个岗位的公司: %d 家（共 %d 家）" % (multi, len(by_ent)))

# 2) 薪资异常：20k以上 / ≥15k
yakko = sum(1 for r in rows if "20k" in (r.get("salary") or ""))
print("\n薪资 '20k以上':", yakko)
big = []
for r in rows:
    s = r.get("salary") or ""
    m = re.search(r"(\d+)\s*k", s)
    if m and int(m.group(1)) >= 15:
        big.append(r)
print("薪资 ≥15k:", len(big))
for r in big[:8]:
    print("   %-16s | %-26s | %s | %s" % (r["title"][:16], r["company"][:26], r["salary"], r["location"]))

# 3) 行业与岗位明显错位
SUSPECT_ENT = ("教育", "文化", "影视", "传播", "汽车设计", "咨询", "商贸", "互联网", "科技")
TECH_JOB = ("实验室", "医药研发", "质量", "检验", "检测", "化验", "工程师", "研发")
mis = [r for r in rows
       if any(k in r["company"] for k in SUSPECT_ENT)
       and any(k in r["title"] for k in TECH_JOB)]
print("\n行业/岗位可疑错位（教育/文化/影视/咨询 公司 招 技术岗）:", len(mis))
for r in mis[:10]:
    print("   %-16s | %-30s | %s" % (r["title"][:16], r["company"][:30], r.get("location")))

# 4) 同一公司同薪资全一致（批量灌水特征）
print("\n同一公司薪资种类数（1 = 全公司一个价，可疑）：")
same = 0
for ent, cnt in by_ent.most_common(12):
    sals = set((r.get("salary") or "") for r in rows if r["company"] == ent)
    if len(sals) == 1 and cnt >= 3:
        same += 1
        print("  %-30s %d 岗 / 薪资全为 %s" % (ent[:30], cnt, list(sals)[0]))
print("  合计 %d 家" % same)

# 5) 描述是否有信息量
empty_desc = sum(1 for r in rows if len((r.get("desc") or "").strip()) < 8)
print("\n描述 <8 字（等于没有）:", empty_desc)
tmpl = sum(1 for r in rows if any(k in (r.get("desc") or "") for k in ("工作认真", "有工作经验优先", "身体健康", "服从")))
print("描述是模板话术:", tmpl)