# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""jlrc 三层清单：从 4,684 条原始数据筛出「食品/检测相关」的可投清单。

口径（照 crawler-site-onboarding 6.5）：
  · 0 请求，只读 jsonl
  · 但本站**没有发布时间字段**（API 19 个字段里没有），所以做不了"新鲜度分桶"，
    改为按【相关度档位】分：① 岗位名直接命中 ② 公司是食品/农牧/药业但岗位名不命中
  · 地区：吉林省内（标注城市）/ 省外（单独列，不建议）
  · 薪资：解析区间下限；「薪资不限」单列

用法：
    python tools\\build_jlrc_list.py                # 预览
    python tools\\build_jlrc_list.py --xlsx          # 同时导出 xlsx
"""
import argparse
import json
import re
from pathlib import Path

RAW = Path(str(_HOME / "data" / "raw" / "jlrc_p20.jsonl"))
OUT = Path(str(_HOME / "out"))

# 岗位名直接命中（强相关）
TITLE_KW = ("食品", "检验", "检测", "品控", "品保", "化验", "质量管理", "质量工程",
            "品管", "QA", "QC", "微生物", "理化", "实验室", "研发", "工艺",
            "生产安全", "食品安全", "体系")
# 公司类型命中（弱相关：公司是这行，但岗位名不一定对口）
ENT_KW = ("食品", "农牧", "牧业", "粮油", "油脂", "乳业", "酒业", "饮料", "肉业",
          "饲料", "生物科技", "药业", "制药", "医药", "农业", "农副")

CITY_ORDER = ["长春市", "吉林市", "四平市", "通化市", "松原市", "白城市",
              "辽源市", "白山市", "延边朝鲜族自治州"]

# ---- 灌水/脏数据规则（2026-11-15 实测得出，别删）----
# 依据：1,199 条抽样里，长春英利汽车挂 81 个岗、虹基酒店 40 个、达利食品 26 个；
#       「麦田希望教育培训学校」招"自动驾驶系统工程师"、「汽车设计公司」招"医药研发" ——
#       这是企业批量注册后灌库，不是真实在招。
SPAM_ENT_MIN_JOBS = 20          # 单公司岗位数 ≥ 此值 → 判灌水（76/264 家 ≥5，26 家 ≥20）
SUSPECT_ENT = ("教育", "文化", "影视", "传播", "汽车设计", "咨询", "商贸", "互联网",
               "人力资源", "境外就业", "劳务")
TECH_JOB = ("工程师", "研发", "实验室", "质量", "检验", "检测", "化验", "技术员")
HIGH_PAY_FOR_LOW_JOB = ("普工", "操作工", "包装工", "店员", "营业员", "其他职位", "客服")


def parse_salary(s):
    """'5k-6k/月' → 5000；'3k-4k/月' → 3000；'薪资不限'/'' → None"""
    if not s or "不限" in s or "面议" in s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[kK千]", s)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d{3,6})", s)
    if m:
        return int(m.group(1))
    return None


def load():
    lines = RAW.read_text(encoding="utf-8").split("\n")
    rows, bad = [], 0
    for l in lines:
        l = l.strip()
        if not l:
            continue
        try:
            rows.append(json.loads(l))
        except Exception:
            bad += 1          # 抓取进行中可能读到半行，跳过而不是崩
    if bad:
        print("!! 跳过 %d 行不完整 JSON（抓取可能仍在进行）" % bad)
    seen, uniq = set(), []
    for r in rows:                      # 同一个 API id 只留一条（跨页重叠）
        k = r.get("source_api_id")
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return rows, uniq


def grade(r):
    t = (r.get("title") or "")
    e = (r.get("company") or "")
    if any(k.lower() in t.lower() for k in TITLE_KW):
        return "A"
    if any(k in e for k in ENT_KW):
        return "B"
    return "-"


def spam_reason(r, ent_jobs):
    """返回灌水/不可信原因；空串表示通过。"""
    ent = r.get("company") or ""
    title = r.get("title") or ""
    if ent_jobs.get(ent, 0) >= SPAM_ENT_MIN_JOBS:
        return "公司挂%d岗(灌水)" % ent_jobs[ent]
    if any(k in ent for k in SUSPECT_ENT) and any(k in title for k in TECH_JOB):
        return "行业岗位错位"
    sal = r.get("salary") or ""
    if "20k" in sal and any(k in title for k in HIGH_PAY_FOR_LOW_JOB):
        return "低端岗挂高薪"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", action="store_true")
    args = ap.parse_args()

    raw, rows = load()
    print("原始 %d 条 → 按 API id 去重后 %d 条（重叠 %d）" % (len(raw), len(rows), len(raw) - len(rows)))

    ent_jobs = {}
    for r in rows:
        ent_jobs[r.get("company", "")] = ent_jobs.get(r.get("company", ""), 0) + 1

    for r in rows:
        r["_grade"] = grade(r)
        r["_floor"] = parse_salary(r.get("salary"))
        r["_jl"] = (r.get("location") or "").startswith("吉林省")
        r["_spam"] = spam_reason(r, ent_jobs)

    clean = [r for r in rows if not r["_spam"]]
    spam = [r for r in rows if r["_spam"]]
    print("灌水/不可信剔除：%d 条（%.1f%%）" % (len(spam), 100.0 * len(spam) / max(1, len(rows))))
    for reason, cnt in __import__("collections").Counter(
            (r["_spam"].split("(")[0]) for r in spam).most_common():
        print("   %-22s %d" % (reason, cnt))

    A = [r for r in clean if r["_grade"] == "A"]
    B = [r for r in clean if r["_grade"] == "B"]
    A_jl = [r for r in A if r["_jl"]]
    B_jl = [r for r in B if r["_jl"]]

    print("\n档位分布（已剔除灌水）：A（岗位名命中）%d 条，其中吉林省内 %d" % (len(A), len(A_jl)))
    print("                        B（公司同行、岗位名不命中）%d 条，其中吉林省内 %d" % (len(B), len(B_jl)))
    print("                        合计可用（A+B 吉林省内）%d 条" % (len(A_jl) + len(B_jl)))

    def show(title, lst, limit=40):
        print("\n=== %s（%d 条）===" % (title, len(lst)))
        for r in sorted(lst, key=lambda x: (-(x["_floor"] or 0), x.get("location") or ""))[:limit]:
            print("  %-22s | %-24s | %-10s | %-10s | %s"
                  % (r["title"][:22], r["company"][:24], r["salary"][:10],
                     (r.get("education") or "")[:10], r.get("location") or ""))

    show("A 档 · 吉林省内（强相关，优先看）", A_jl)
    show("B 档 · 吉林省内（同行公司，岗位需人工判断）", B_jl, 25)

    out = OUT / "jlrc_food_shortlist.json"
    OUT.mkdir(parents=True, exist_ok=True)
    keep = [{k: v for k, v in r.items()} for r in (A_jl + B_jl)]
    out.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n清单已写出：%s（%d 条）" % (out, len(keep)))

    if args.xlsx:
        try:
            from openpyxl import Workbook
        except ImportError:
            print("!! 没装 openpyxl，跳过 xlsx")
            return
        wb = Workbook()
        ws = wb.active
        ws.title = "A-食品检测岗"
        head = ["档位", "岗位", "公司", "薪资", "学历", "专业", "地区", "人数", "待遇", "描述", "API_ID"]
        ws.append(head)
        for r in A_jl:
            ws.append([r["_grade"], r["title"], r["company"], r["salary"], r.get("education"),
                       r.get("major"), r.get("location"), r.get("headcount"),
                       r.get("treatment"), (r.get("desc") or "")[:200], r.get("source_api_id")])
        ws2 = wb.create_sheet("B-同行公司其他岗")
        ws2.append(head)
        for r in B_jl:
            ws2.append([r["_grade"], r["title"], r["company"], r["salary"], r.get("education"),
                        r.get("major"), r.get("location"), r.get("headcount"),
                        r.get("treatment"), (r.get("desc") or "")[:200], r.get("source_api_id")])
        xp = OUT / "jlrc_food_shortlist.xlsx"
        wb.save(xp)
        print("xlsx: %s" % xp)


if __name__ == "__main__":
    main()