# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
生成「温州 · 大专及以下 · 5K+ · 双休 · 对口」投递清单（**0 个请求**）。

规则全部 import 自 `crawlers/clean_jobs_wz.py`，**不复制、不修改**它
（它在 v8 基线里，改一个字 verify_baseline --strict 立刻漂移）。

用法：
    python tools\\build_wz_shortlist.py                  # 五个输入文件全跑
    python tools\\build_wz_shortlist.py --only-main      # 只喂主站 502 条（硬验收：21 条 / 16 岗位 / 9 公司）

产物：
    out\\温州岗位清单_20261111.xlsx   （4 个 sheet）
    out\\温州岗位清单_20261111.json   （只存「①明确符合」，给抓 JD 用）
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

AGENT = Path(str(_HOME))
sys.path.insert(0, str(AGENT / "crawlers"))
import clean_jobs_wz as cw          # noqa: E402  （第 332 行有 __main__ 保护）

BASE = date(2026, 11, 11)           # 写死，保证可复现

INPUTS = [
    AGENT / "data" / "raw" / "wzrc_dw_20261111.jsonl",   # 主站·全温州·双休 tag，502
    AGENT / "data" / "raw" / "yqwzrc_w60.jsonl",         # 乐清分站·5K-10K，358
    AGENT / "data" / "raw" / "yqwzrc_w61.jsonl",         # 乐清分站·10K+，42
    AGENT / "data" / "raw" / "yqwzrc_20261110.jsonl",    # 乐清分站·双休，44
    AGENT / "data" / "raw" / "yqrc_20261110.jsonl",      # 乐清人才网，200
]

OUT_XLSX = AGENT / "out" / "温州岗位清单_20261111.xlsx"
OUT_JSON = AGENT / "out" / "温州岗位清单_20261111.json"


# ------------------------------------------------------------------ 时间
def parse_published(raw, base=BASE):
    """返回 (age_days, kind)。kind: abs / rel / none。

    乐清那三份里有 `1周前/2周前/3周前`（共 64 条），**必须按 N×7 算**，
    否则会被当成"日期缺失"，A 层直接少一截。
    """
    s = (raw or "").strip()
    if not s:
        return None, "none"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return (base - date(y, mo, d)).days, "abs"
        except ValueError:
            return None, "none"
    if "刚刚" in s:
        return 0, "rel"
    if re.search(r"\d+\s*分钟前", s) or re.search(r"\d+\s*小时前", s):
        return 0, "rel"
    m = re.search(r"(\d+)\s*天前", s)
    if m:
        return int(m.group(1)), "rel"
    m = re.search(r"(\d+)\s*周前", s)
    if m:
        return int(m.group(1)) * 7, "rel"
    m = re.search(r"(\d+)\s*个月前", s)
    if m:
        return int(m.group(1)) * 30, "rel"
    return None, "none"


def norm_key(*texts):
    s = "|".join(unicodedata.normalize("NFKC", t or "") for t in texts)
    return re.sub(r"\s+", "", s).lower()


#: 乐清的乡镇/街道。乐清人才网（yqrc）的 region 字段只写乡镇名（如"柳市镇"），
#: 不带"乐清"二字，只按关键字判会把这批全归到"其他"——实测 7 条被误判。
LEQING_TOWNS = (
    "柳市", "北白象", "磐石", "七里港", "黄华", "白石", "翁垟", "盐盆",
    "城南", "乐成", "城东", "城西", "石帆", "天成", "虹桥", "淡溪",
    "清江", "南塘", "南岳", "蒲岐", "芙蓉", "雁荡", "大荆", "仙溪",
    "智仁", "龙西", "岭底",
)


def region_group(region):
    r = region or ""
    if "乐清" in r or any(t in r for t in LEQING_TOWNS):
        return "乐清"
    if any(x in r for x in ("鹿城", "瓯海", "龙湾", "洞头")):
        return "市区"
    if "温州" in r:
        return "其他县市"
    return "其他"


# ------------------------------------------------------------------ 读入
def load_rows(only_main=False):
    files = INPUTS[:1] if only_main else INPUTS
    rows, per_file = [], []
    for f in files:
        if not f.exists():
            print("!! 缺文件：%s" % f)
            continue
        n = 0
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            r["_src"] = f.name
            rows.append(r)
            n += 1
        per_file.append((f.name, n))
        print("读入 %-28s %5d 行" % (f.name, n))
    return rows, per_file


# ------------------------------------------------------------------ 筛选
def screen(rows):
    """严格按指令顺序筛：顺序错了剔除原因就会写错。"""
    kept, rejected = [], []
    seen_url = set()
    dup_url = 0

    for r in rows:
        url = (r.get("detail_url") or "").strip()
        if url:
            if url in seen_url:
                dup_url += 1
                continue
            seen_url.add(url)
        title = r.get("title") or ""
        age, _kind = parse_published(r.get("published"))

        # 1 对口
        cats = cw.classify(title)
        if not cats:
            rejected.append((r, age, "不对口", ""))
            continue
        # 2 双休
        wk, wk_note = cw.weekend_state(r)
        if wk == "非双休":
            rejected.append((r, age, "非双休", wk_note))
            continue
        # 3 岗位性质
        nature = cw.judge_nature(r)
        if nature != "企业直招":
            rejected.append((r, age, "非直招:%s" % nature, ""))
            continue
        # 4 学历
        edu_text, edu_ok, edu_note = cw.judge_edu(r)
        if not edu_ok:
            rejected.append((r, age, "学历超大专", edu_text or edu_note))
            continue
        # 5 薪资可解析
        floor, sal_state = cw.parse_salary(r.get("salary_raw"))
        if sal_state != "ok":
            rejected.append((r, age, "薪资面议/不明", r.get("salary_raw") or ""))
            continue
        # 6 薪资门槛
        if floor is None or floor < cw.SALARY_FLOOR:
            rejected.append((r, age, "薪资<5K", r.get("salary_raw") or ""))
            continue

        kept.append({
            "title": title,
            "company": r.get("company") or "",
            "cats": cats,
            "region": r.get("region") or "",
            "rgroup": region_group(r.get("region")),
            "salary_raw": r.get("salary_raw") or "",
            "floor": floor,
            "edu": edu_text if edu_text else "",
            "exp": r.get("exp_req") or "",
            "published": r.get("published") or "",
            "age": age,
            "detail_url": url,
            "src": r["_src"],
            "weekend": wk,
            "weekend_note": wk_note,
        })
    return kept, rejected, dup_url


def dedup_posts(items):
    """公司+岗位去重：保留薪资下限最高的一条，记同岗位数。"""
    groups = OrderedDict()
    for it in items:
        k = norm_key(it["company"], it["title"])
        groups.setdefault(k, []).append(it)
    out = []
    for k, g in groups.items():
        g2 = sorted(g, key=lambda x: (-(x["floor"] or 0),
                                      x["age"] if x["age"] is not None else 10 ** 6))
        main = dict(g2[0])
        main["dup"] = len(g)
        out.append(main)
    return out


def sort_key(it):
    age = it["age"] if it["age"] is not None else 10 ** 6
    return (age, -(it["floor"] or 0))


# ------------------------------------------------------------------ 输出
HEAD = ["序号", "岗位", "公司", "分类", "地区", "薪资原文", "薪资下限", "学历", "经验",
        "发布时间", "年龄(天)", "同岗位数", "详情链接", "来源文件"]
W = {1: 6, 2: 24, 3: 30, 4: 8, 5: 20, 6: 14, 7: 10, 8: 10, 9: 10,
     10: 14, 11: 9, 12: 9, 13: 52, 14: 22}


def write_xlsx(main, pending, rejected, stats_lines):
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "④统计"

    def sheet(title, rows, extra_col=None, widths=None):
        ws = wb.create_sheet(title)
        head = HEAD + ([extra_col] if extra_col else [])
        ws.append(head)
        for c in range(1, len(head) + 1):
            ws.cell(row=1, column=c).font = Font(bold=True)
            ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
        for i, it in enumerate(rows, 1):
            line = [i, it["title"], it["company"], "/".join(it["cats"]), it["region"],
                    it["salary_raw"], it["floor"], it["edu"], it["exp"],
                    it["published"], it["age"], it.get("dup", 1),
                    it["detail_url"], it["src"]]
            if extra_col:
                line.append(it.get("_note", ""))
            ws.append(line)
        w = dict(W)
        if extra_col:
            w[len(head)] = 26
        for c in range(1, len(head) + 1):
            ws.column_dimensions[get_column_letter(c)].width = w.get(c, 16)
        ws.freeze_panes = "A2"
        return ws

    sheet("①明确符合", main)
    pend = []
    for it in pending:
        x = dict(it)
        x["_note"] = "面试前电话确认双休"
        pend.append(x)
    sheet("②双休待确认", pend, extra_col="备注")

    # ③被剔除：按原因分组
    rej = []
    for r, age, reason, note in sorted(rejected, key=lambda t: (t[2], -(t[1] if t[1] is not None else 10 ** 6))):
        rej.append({
            "title": r.get("title") or "", "company": r.get("company") or "",
            "cats": [], "region": r.get("region") or "",
            "salary_raw": r.get("salary_raw") or "", "floor": None,
            "edu": r.get("edu_req") or "", "exp": r.get("exp_req") or "",
            "published": r.get("published") or "", "age": age,
            "detail_url": r.get("detail_url") or "", "src": r["_src"],
            "_note": reason + (("：" + note) if note else ""),
        })
    sheet("③被剔除", rej, extra_col="剔除原因")

    ws0.append(["项目", "值"])
    for c in (1, 2):
        ws0.cell(row=1, column=c).font = Font(bold=True)
        ws0.cell(row=1, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
    for k, v in stats_lines:
        ws0.append([k, v])
    ws0.column_dimensions["A"].width = 40
    ws0.column_dimensions["B"].width = 62
    wb.save(OUT_XLSX)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-main", action="store_true", help="只喂主站 502 条（硬验收用）")
    a = ap.parse_args()

    rows, per_file = load_rows(only_main=a.only_main)
    print("合计读入 %d 行（去重前）" % len(rows))

    kept, rejected, dup_url = screen(rows)
    print("detail_url 重复跳过 %d 条" % dup_url)

    # 记录数（去重前）与岗位数（公司+岗位去重后）是两个口径，分开记：
    #   21 条记录 → 16 个岗位（同一公司同岗位挂了多条）→ 9 家公司
    main_raw = [x for x in kept if x["weekend"] == "明确双休"]
    pend_raw = [x for x in kept if x["weekend"] != "明确双休"]
    main_rows = sorted(dedup_posts(main_raw), key=sort_key)
    pend_rows = sorted(dedup_posts(pend_raw), key=sort_key)

    total_after = len(kept) + len(rejected)
    print()
    print("=" * 62)
    print("①明确符合：记录 %d 条 → 去重后 %d 个岗位" % (len(main_raw), len(main_rows)))
    print("②双休待确认：记录 %d 条 → 去重后 %d 个岗位" % (len(pend_raw), len(pend_rows)))
    print("③被剔除：%d 条" % len(rejected))
    print("合计 %d = 输入 %d（detail_url 重复跳过 %d）"
          % (len(main_raw) + len(pend_raw) + len(rejected), len(rows), dup_url))
    print("=" * 62)

    if a.only_main:
        comps = len({norm_key(x["company"]) for x in main_raw})
        got = (len(main_raw), len(main_rows), comps)
        print()
        print("硬验收（只喂主站）：① 记录 %d / 去重岗位 %d / 公司 %d   期望 21 / 16 / 9   %s"
              % (got[0], got[1], got[2], "PASS" if got == (21, 16, 9) else "FAIL"))
        return 0 if got == (21, 16, 9) else 1

    # 统计
    reasons = Counter(t[2] for t in rejected)
    cats = Counter(c for it in main_rows for c in it["cats"])
    rgroups = Counter(it["rgroup"] for it in main_rows)
    stats = [("生成时间基准日", str(BASE)), ("", "")]
    stats.append(("输入文件", ""))
    for name, n in per_file:
        stats.append(("   " + name, n))
    stats.append(("   合计（去重前）", len(rows)))
    stats.append(("detail_url 重复跳过", dup_url))
    stats.append(("", ""))
    stats.append(("①明确符合（记录数）", len(main_raw)))
    stats.append(("①明确符合（去重后岗位数）", len(main_rows)))
    stats.append(("②双休待确认（记录数）", len(pend_raw)))
    stats.append(("②双休待确认（去重后岗位数）", len(pend_rows)))
    stats.append(("③被剔除", len(rejected)))
    stats.append(("合计 = ①+②+③", len(main_raw) + len(pend_raw) + len(rejected)))
    stats.append(("", ""))
    stats.append(("剔除原因分布", ""))
    for k, v in reasons.most_common():
        stats.append(("   " + k, v))
    stats.append(("", ""))
    stats.append(("①分类分布", ""))
    for k in ("A", "B", "C"):
        stats.append(("   " + k, cats.get(k, 0)))
    stats.append(("①地区分布", ""))
    for k, v in rgroups.most_common():
        stats.append(("   " + k, v))
    stats.append(("", ""))
    stats.append(("①公司数（去重后）", len({norm_key(x["company"]) for x in main_rows})))
    stats.append(("①岗位数（公司+岗位去重后）", len(main_rows)))

    write_xlsx(main_rows, pend_rows, rejected, stats)

    OUT_JSON.write_text(json.dumps(
        [{"title": x["title"], "company": x["company"], "cats": x["cats"],
          "region": x["region"], "rgroup": x["rgroup"], "salary_raw": x["salary_raw"],
          "floor": x["floor"], "edu": x["edu"], "exp": x["exp"],
          "published": x["published"], "age": x["age"],
          "detail_url": x["detail_url"], "src": x["src"]}
         for x in main_rows], ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("剔除原因分布：")
    for k, v in reasons.most_common():
        print("  %-22s %d" % (k, v))
    print()
    print("①分类分布：", dict(cats))
    print("①地区分布：", dict(rgroups))
    print()
    print("xlsx : %s" % OUT_XLSX)
    print("json : %s（① %d 条）" % (OUT_JSON, len(main_rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())