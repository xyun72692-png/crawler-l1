# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
温州全市招聘清洗：对口方向 + 大专及以下 + 月薪5K以上

对口方向（用户：国际商务专业 / 剪辑运营账号拍视频 / 直播电商）：
  A 国际商务·外贸     外贸/国际贸易/进出口/报关/单证/跨境电商/国际站/货代/跟单/国际商务
  B 视频剪辑·账号运营  剪辑/短视频/视频/新媒体/抖音/快手/小红书/账号运营/内容运营/拍摄/摄影/编导/后期
  C 直播电商          直播/带货/主播/电商运营/店铺运营/淘宝/天猫/拼多多/场控/中控/美工

硬条件：大专及以下（含学历不限/未标注） + 月薪下限 ≥ 5000
软条件：双休 —— 拆成两层，因为站上大部分职位根本不填双休标签：
  ① 明确双休（福利标签含双休，或标题写双休）→ 主表
  ② 未标注双休 → 单独一页，标注"需自行确认"，不当成双休骗人

薪资取区间下限；年薪自动/12；「面议」单列。
"""
import io
import json
import os
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

RAW_DIR = str(_HOME / "data" / "raw")
CLEAN_DIR = str(_HOME / "data" / "clean")
REPORT_DIR = str(_HOME / "out" / "reports")
SALARY_FLOOR = 5000

KW_INTL = ["外贸", "国际贸易", "进出口", "报关", "单证", "跨境电商", "国际商务", "跨境",
           "货代", "国际站", "亚马逊", "速卖通", "跟单", "海外业务", "海外销售", "外销", "内外贸"]
KW_VIDEO = ["剪辑", "短视频", "视频", "新媒体", "抖音", "快手", "小红书", "账号运营",
            "内容运营", "拍摄", "摄影", "编导", "后期", "自媒体", "摄像"]
KW_LIVE = ["直播", "带货", "主播", "电商运营", "店铺运营", "淘宝", "天猫", "拼多多",
           "场控", "中控", "电商专员", "电商助理", "网店", "电商", "美工"]

CAT_NAMES = {"A": "国际商务·外贸", "B": "视频剪辑·账号运营", "C": "直播电商"}


def classify(title):
    t = title or ""
    cats = []
    if any(k in t for k in KW_INTL):
        cats.append("A")
    if any(k in t for k in KW_VIDEO):
        cats.append("B")
    if any(k in t for k in KW_LIVE):
        cats.append("C")
    return cats


def discover_files():
    out = []
    for f in sorted(os.listdir(RAW_DIR)):
        if not f.endswith(".jsonl") or "try" in f:
            continue
        if not (f.startswith("wzrc") or f.startswith("yq")):
            continue
        name = f[:-6]
        if name.startswith("wzrc_dw"):
            site = "温州人才网(双休筛选)"
        elif name.startswith("wzrc_kw"):
            site = "温州人才网(关键词搜索)"
        elif name.startswith("wzrc_"):
            site = "温州人才网(行业薪资档)"
        elif name.startswith("yqrc"):
            site = "乐清人才网"
        else:
            site = "温州人才网乐清分站"
        out.append((os.path.join(RAW_DIR, f), site))
    return out


UNIT = {"万": 10000, "w": 10000, "W": 10000, "k": 1000, "K": 1000, "千": 1000}


def _num(seg):
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(万|w|W|k|K|千)?", seg)
    if not m:
        return None
    v = float(m.group(1))
    u = m.group(2)
    if u:
        v *= UNIT[u]
    return v


def parse_salary(raw):
    s = (raw or "").strip()
    if not s:
        return None, "unknown"
    if "面议" in s:
        return None, "negotiable"
    is_year = ("年薪" in s) or ("/年" in s) or ("元/年" in s)
    parts = re.split(r"[~～\-—－至到]", s)
    low = _num(parts[0])
    if low is None:
        return None, "unknown"
    if is_year:
        low /= 12.0
    return low, "ok"


NOT_WEEKEND_RE = re.compile(r"单双休|大小周|周休一天半|5\.5\s*天|五天半|六天|单休")


def weekend_state(rec):
    """返回 (状态, 说明)  状态：明确双休 / 非双休 / 未标注"""
    welfare = rec.get("welfare") or ""
    tags = [t for t in welfare.split("|") if t]
    title = rec.get("title") or ""
    if ("单休" in tags) or ("单双休" in tags) or NOT_WEEKEND_RE.search(title):
        return "非双休", "标签或标题写明单休/大小周"
    if "双休" in title or "双休" in tags:
        return "明确双休", ""
    return "未标注", "站上没填双休标签，需面试确认"


EDU_OK = {"初中", "高中", "中技", "中专", "大专", "不限", "学历不限", "未标注"}
EDU_BAD = {"本科", "硕士", "博士", "博后"}
EXP_LIKE_RE = re.compile(r"^\d+\s*年(以上|以下)?$|^无经验$|^应届")


def judge_edu(rec):
    edu = (rec.get("edu_req") or "").strip()
    if not edu:
        return "未标注", True, "卡片未显示学历(按不限处理)"
    if EXP_LIKE_RE.match(edu):
        return "未标注", True, "学历位显示成经验(%s)" % edu
    if edu in EDU_OK:
        return edu, True, ""
    if edu in EDU_BAD:
        return edu, False, ""
    return edu, True, "取值未见过，按通过处理"


RE_TRAINING = re.compile(r"编程培训|培训学校|教育~|网校|招生|集中营|专注.*培训|技能培训|培训班")
RE_INSURANCE = re.compile(r"保险|平安|人寿|泰康|太平洋保险|新华保险|证券|贷款|理财|金融|财富管理|康养顾问")
RE_DELIVERY = re.compile(r"配送员|骑手|外卖|闪送|跑腿|快递员")


def judge_nature(rec):
    t = rec.get("title") or ""
    c = rec.get("company") or ""
    both = t + " " + c
    if RE_TRAINING.search(t) or RE_TRAINING.search(c):
        return "机构招生(非岗位)"
    if RE_INSURANCE.search(both):
        return "保险/金融销售(提成制)"
    if RE_DELIVERY.search(t):
        return "配送/骑手(计件)"
    return "企业直招"


FRESH_OK = {"", "无经验", "1年以下", "应届毕业生", "不限"}


def fresh_friendly(rec):
    exp = (rec.get("exp_req") or "").strip()
    return "是" if exp in FRESH_OK else ""


HEADERS = ["序号", "职位", "公司", "方向", "月薪下限(元)", "薪资原文", "学历要求",
           "经验要求", "应届可投", "地区", "双休", "岗位性质", "福利标签", "发布时间", "来源", "链接"]
WIDTHS = [6, 28, 34, 18, 12, 16, 10, 10, 9, 20, 10, 22, 34, 12, 26, 50]
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)
THIN_WRAP = Alignment(vertical="top", wrap_text=True)


def row_of(i, r):
    return [i, r.get("title") or "", r.get("company") or "", r.get("_cat_text") or "",
            int(r["_low"]) if r.get("_low") else "",
            r.get("salary_raw") or "", r.get("_edu_text") or "",
            r.get("exp_req") or "", fresh_friendly(r),
            r.get("region") or "", r.get("_dw") or "",
            judge_nature(r), r.get("welfare") or "",
            r.get("published") or "", r.get("_site") or "", r.get("detail_url") or ""]


def write_sheet(ws, rows, title=None):
    ws.append(HEADERS)
    for c in ws[1]:
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
    for i, r in enumerate(rows, 1):
        ws.append(row_of(i, r))
    for idx, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.alignment = THIN_WRAP
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:P%d" % ws.max_row
    if title:
        ws.title = title


def load_all():
    rows, seen, dup = [], set(), 0
    for path, site in discover_files():
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                u = r.get("detail_url")
                if u and u in seen:
                    dup += 1
                    continue
                if u:
                    seen.add(u)
                r["_site"] = site
                rows.append(r)
    return rows, dup


def build():
    recs, dup = load_all()
    stats = {"raw_total": len(recs), "dup_same_url": dup}

    strict, need_check, negotiable, low_pay, edu_out, non_job = [], [], [], [], [], []
    for r in recs:
        cats = classify(r.get("title"))
        if not cats:
            continue
        r["_cats"] = cats
        r["_cat_text"] = "、".join(CAT_NAMES[c] for c in cats)

        dw, _ = weekend_state(r)
        r["_dw"] = dw
        if dw == "非双休":
            continue
        if judge_nature(r) == "机构招生(非岗位)":
            non_job.append(r)
            continue
        edu_text, edu_pass, _note = judge_edu(r)
        r["_edu_text"] = edu_text
        if not edu_pass:
            edu_out.append(r)
            continue
        low, kind = parse_salary(r.get("salary_raw"))
        r["_low"] = low
        if kind in ("negotiable", "unknown"):
            negotiable.append(r)
            continue
        if low is None or low < SALARY_FLOOR:
            low_pay.append(r)
            continue
        if dw == "明确双休":
            strict.append(r)
        else:
            need_check.append(r)

    def dedup(rows):
        seen = {}
        out = []
        for r in rows:
            k = (re.sub(r"\s+", "", r.get("company") or ""),
                 re.sub(r"\s+", "", r.get("title") or ""))
            if k in seen:
                seen[k]["_site"] += " + " + r["_site"]
                if len(r.get("salary_raw") or "") > len(seen[k].get("salary_raw") or ""):
                    seen[k]["salary_raw"] = r["salary_raw"]
                continue
            seen[k] = r
            out.append(r)
        return out

    strict = sorted(dedup(strict), key=lambda x: -(x["_low"] or 0))
    need_check = sorted(dedup(need_check), key=lambda x: -(x["_low"] or 0))
    negotiable = sorted(dedup(negotiable), key=lambda x: -(x["_low"] or 0))

    stats.update({
        "strict_weekend": len(strict),
        "weekend_unknown": len(need_check),
        "negotiable": len(negotiable),
        "low_pay_dropped": len(low_pay),
        "edu_dropped": len(edu_out),
        "non_job": len(non_job),
    })
    for k in "ABC":
        stats["strict_" + k] = sum(1 for r in strict if k in r["_cats"])
        stats["unknown_" + k] = sum(1 for r in need_check if k in r["_cats"])
    return strict, need_check, negotiable, low_pay, edu_out, non_job, stats


def main():
    strict, need_check, negotiable, low_pay, edu_out, non_job, stats = build()
    stamp = datetime.now().strftime("%Y%m%d")
    os.makedirs(CLEAN_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    wb = Workbook()
    write_sheet(wb.active, strict, "①双休+对口(主表)")
    write_sheet(wb.create_sheet("②对口但双休未标注"), need_check)

    for c in "ABC":
        sub = [r for r in strict if c in r["_cats"]]
        if sub:
            write_sheet(wb.create_sheet(CAT_NAMES[c][:28]), sub)

    write_sheet(wb.create_sheet("③对口但薪资面议"), negotiable)
    write_sheet(wb.create_sheet("④被剔除-薪资不足5K"), low_pay)
    write_sheet(wb.create_sheet("⑤被剔除-学历超大专"), edu_out)
    if non_job:
        write_sheet(wb.create_sheet("⑥机构招生(非岗位)"), non_job)

    xlsx = os.path.join(CLEAN_DIR, "温州-对口岗位-双休5K-{}.xlsx".format(stamp))
    wb.save(xlsx)
    stats["xlsx"] = xlsx
    with io.open(os.path.join(REPORT_DIR, "clean_wz_final_{}.json".format(stamp)), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("\n=== ① 双休+对口 %d 条 ===" % len(strict))
    for i, r in enumerate(strict, 1):
        print("%2d. %5d | %-4s | %-14s | %-22s | %-20s | %s" % (
            i, int(r["_low"]), r["_edu_text"], r["_cat_text"][:14],
            r["title"][:20], r["company"][:18], r["region"][:12]))
    print("\n=== ② 对口但双休未标注 %d 条（前20）===" % len(need_check))
    for i, r in enumerate(need_check[:20], 1):
        print("%2d. %5d | %-4s | %-14s | %-22s | %-20s | %s" % (
            i, int(r["_low"]), r["_edu_text"], r["_cat_text"][:14],
            r["title"][:20], r["company"][:18], r["region"][:12]))


if __name__ == "__main__":
    main()