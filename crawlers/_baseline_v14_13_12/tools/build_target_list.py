# -*- coding: utf-8 -*-
"""按新口径重出三层清单（0 请求）。

口径（2026-11-14 用户确认）：
  T1 严   检验/检测/化验/品控/品保/质检/质量/品管/QC/QA/微生物/理化/实验
  T2 技术  T1 + 研发/工艺/生产/技术/设备/工程/安全/环保/体系/法规/注册/
           车间/厂长/班组长/管培/储备
  X       销售（销售/业务/营销/客户/渠道/推广/直播）、职能/普工（财务/人事/行政/
           采购/仓储/物流/文员/普工/操作工/司机/保安）→ **不进三层**

三层（按"确定性"，不按字母）：
  L1 可直接投    T1/T2 + 本科及以下 + 薪资明确 ≥4500
  L2 要问薪      T1/T2 + 薪资面议/未知（学历本科及以下或未写）
  L3 备选        T1/T2 + 薪资明确但 <4500，或学历偏高（硕士/博士）

用法：
    python tools\\build_target_list.py                # 用 foodmate 全量
    python tools\\build_target_list.py --jsonl <path>
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r"D:\agent-work\tools")
sys.dont_write_bytecode = True
import region_map as rm   # noqa: E402

DEFAULT_JSONL = Path(r"D:\agent-work\data\raw\foodmate_full_20261113.jsonl")
OUT_DIR = Path(r"D:\agent-work\out")

STRICT = ("检验", "检测", "化验", "品控", "品保", "质检", "质量", "品管",
          "QC", "QA", "微生物", "理化", "实验")
TECH = STRICT + ("研发", "工艺", "生产", "技术", "设备", "工程", "安全", "环保",
                 "体系", "法规", "注册", "车间", "厂长", "班组长", "组长", "管培", "储备")
SALES = ("销售", "业务", "营销", "客户", "渠道", "推广", "导购", "直播", "主播", "招商")
FUNC = ("财务", "会计", "人事", "人力资源", "HR", "行政", "法务", "采购", "仓储",
        "物流", "文员", "普工", "操作工", "司机", "保安", "客服", "招聘", "培训")
SENIOR = ("总经理", "总监", "副总裁", "副总", "董事长", "总裁", "首席", "合伙人")
MGR = ("厂长", "部长", "经理", "主任", "主管", "组长", "领班")
SALARY_SUSPECT = 50000   # 月薪 > 5 万：大概率是"年薪写成月薪"或乱填


def tier(title):
    t = title or ""
    if any(k in t for k in SENIOR):
        return "X-高管"
    if any(k in t for k in STRICT):
        return "T1"
    if any(k in t for k in TECH):
        return "T2"
    if any(k in t for k in SALES):
        return "X-销售"
    if any(k in t for k in FUNC):
        return "X-职能"
    return "T2"          # 兜底：食品企业里非销售非职能的，按技术类算


def edu_level(s):
    t = (s or "").strip()
    if not t:
        return None
    if any(k in t for k in ("博士",)):
        return 7
    if any(k in t for k in ("硕士", "研究生", "MBA")):
        return 6
    if "本科" in t:
        return 5
    if "大专" in t or "专科" in t:
        return 4
    if "中专" in t or "中技" in t:
        return 2
    if "高中" in t:
        return 3
    if "初中" in t:
        return 1
    if "不限" in t:
        return 0
    return None


def salary_floor(t):
    t = (t or "").strip()
    if not t or "面议" in t:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*(万|千|K|k)?", t)
    if m:
        lo = float(m.group(1))
        u = m.group(3) or ""
        if u == "万":
            lo *= 10000
        elif u in ("千", "K", "k"):
            lo *= 1000
        return int(lo)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(万|千|K|k)", t)
    if m:
        lo = float(m.group(1))
        u = m.group(2)
        return int(lo * (10000 if u == "万" else 1000))
    m = re.search(r"(\d{3,})", t)
    if not m:
        return None
    v = int(m.group(1))
    # 年薪 → 折月（「10万-20万/年」不能被当成 10 万/月）
    if ("年" in t) and ("月" not in t):
        v = int(v / 12)
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    ap.add_argument("--salary-min", type=int, default=4500)
    args = ap.parse_args()

    src = Path(args.jsonl)
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    tgt = []
    for r in rows:
        if not rm.in_target(r.get("region", "")):
            continue
        r = dict(r)
        r["province"] = rm.province_of(r["region"])
        r["tier"] = tier(r.get("title"))
        r["edu_lv"] = edu_level(r.get("edu_req"))
        r["floor"] = salary_floor(r.get("salary_raw"))
        r["is_mgr"] = any(k in (r.get("title") or "") for k in MGR)
        r["salary_suspect"] = bool(r["floor"] and r["floor"] > SALARY_SUSPECT)
        tgt.append(r)

    core = [r for r in tgt if r["tier"] in ("T1", "T2")]
    excluded = [r for r in tgt if r["tier"].startswith("X")]

    L1 = [r for r in core if r["floor"] is not None and r["floor"] >= args.salary_min
          and not r["salary_suspect"] and not r["is_mgr"]
          and (r["edu_lv"] is None or r["edu_lv"] <= 5)]
    L2 = [r for r in core if (r["floor"] is None or r["is_mgr"]) and not r["salary_suspect"]
          and (r["edu_lv"] is None or r["edu_lv"] <= 5)]
    L3 = [r for r in core if r not in L1 and r not in L2]

    cols = ["layer", "tier", "province", "region", "title", "salary_raw", "floor",
            "exp_req", "edu_req", "company", "job_nature", "headcount", "detail_url"]
    out = OUT_DIR / "三层清单_新口径_20261114.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for layer, items in (("L1", L1), ("L2", L2), ("L3", L3)):
            for r in sorted(items, key=lambda x: (-(x["floor"] or 0), x["province"], x["region"])):
                w.writerow({"layer": layer, **{k: r.get(k, "") for k in cols if k != "layer"}})

    ex_out = OUT_DIR / "排除_销售与职能_20261114.csv"
    with open(ex_out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tier", "province", "region", "title", "salary_raw", "company"])
        w.writeheader()
        for r in excluded:
            w.writerow({k: r.get(k, "") for k in ("tier", "province", "region", "title",
                                                 "salary_raw", "company")})

    print("源 %s → 两省 %d 条" % (src.name, len(tgt)))
    print("  T1 %d / T2 %d / 排除(销售+职能) %d"
          % (sum(1 for r in tgt if r["tier"] == "T1"),
             sum(1 for r in tgt if r["tier"] == "T2"), len(excluded)))
    print("  L1 可直接投（薪资≥%d + 本科及以下） %d" % (args.salary_min, len(L1)))
    print("  L2 要问薪（面议 + 本科及以下）        %d" % len(L2))
    print("  L3 备选（薪资低/学历偏高/薪资可疑）     %d" % len(L3))
    print("  其中薪资可疑（>5万/月）              %d"
          % sum(1 for r in core if r["salary_suspect"]))
    print("  管理岗（厂长/部长/经理/主任/主管）      %d" % sum(1 for r in core if r["is_mgr"]))
    print("→", out)
    print("→", ex_out)
    print("\nL1 前 12 条：")
    for r in sorted(L1, key=lambda x: -(x["floor"] or 0))[:12]:
        print("  %-5s %5d %-8s %-24s %-8s %s" % (r["province"], r["floor"], r["region"][:6],
                                                 r["title"][:22], r["edu_req"][:6], r["company"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())