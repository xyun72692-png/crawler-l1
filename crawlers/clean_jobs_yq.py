# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
乐清招聘数据清洗：双休 + 月薪≥6000 + 学历大专及以下

输入：data/raw/yqrc_20261110.jsonl（乐清人才网，welfare=5 双休筛选）
      data/raw/yqwzrc_20261110.jsonl（温州人才网乐清分站，jobtag=147 双休筛选）
输出：data/clean/乐清-双休高薪-<日期>.xlsx
      data/clean/乐清-双休高薪-<日期>.csv
      out/reports/clean_jobs_<日期>.json（统计摘要，供复核）

判定规则（写死在代码里，改口径只改这里）：
  1) 双休：福利标签必须含「双休」，且不含「单休」「单双休」；
     标题里出现 单双休/大小周/周休一天半/5.5天/五天半 也判为不是双休。
     说明：乐清人才网 welfare=5 筛选不精确（200 条里 45 条根本没双休标签），
     必须靠标签二次确认，否则会把单休职位混进来。
  2) 高薪：解析薪资原文取【下限】，月薪 ≥ 6000。年薪自动 /12。
     「面议」无法判断，单列一页，不混进主名单。
  3) 学历：初中/高中/中技/中专/大专/不限/未标注 → 保留；
     本科/硕士/博士/博后 → 剔除。
     注意：卡片缺学历显示时，属性位会错位成经验（如「3年以上」），
     这类按「未标注＝不限」处理，但会在备注里标出，供人工复核。
  4) 跨站去重：公司名归一化(去空格/全半角括号统一) + 职位名归一化，
     同一岗位在两个站都出现时只留一条，来源合并标注。
"""

import io
import json
import os
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

RAW_FILES = [
    (str(_HOME / "data" / "raw" / "yqrc_20261110.jsonl"), "乐清人才网"),
    (str(_HOME / "data" / "raw" / "yqwzrc_20261110.jsonl"), "温州人才网乐清分站"),
    (str(_HOME / "data" / "raw" / "yqwzrc_w60.jsonl"), "温州人才网乐清分站(5K-10K档)"),
    (str(_HOME / "data" / "raw" / "yqwzrc_w61.jsonl"), "温州人才网乐清分站(10K以上档)"),
]
GOV_FILE = str(_HOME / "data" / "raw" / "gov_jobs.json")
CLEAN_DIR = str(_HOME / "data" / "clean")
REPORT_DIR = str(_HOME / "out" / "reports")

SALARY_FLOOR = 6000          # 月薪下限门槛
EDU_OK = {"初中", "高中", "中技", "中专", "大专", "不限", "学历不限", "未标注"}
EDU_BAD = {"本科", "硕士", "博士", "博后"}
NOT_WEEKEND_RE = re.compile(r"单双休|大小周|周休一天半|5\.5\s*天|五天半|六天")
EXP_LIKE_RE = re.compile(r"^\d+\s*年(以上|以下)?$|^无经验$|^应届")

# 乐清行政区划（乡镇/街道/开发区），用于剔除外地职位
YUEQING_AREAS = {
    "城东街道", "乐成街道", "城南街道", "盐盆街道", "翁垟街道", "白石街道",
    "石帆街道", "天成街道", "柳市镇", "北白象镇", "磐石镇", "虹桥镇",
    "南塘镇", "南岳镇", "蒲岐镇", "清江镇", "芙蓉镇", "雁荡镇", "大荆镇",
    "湖雾镇", "淡溪镇", "仙溪镇", "黄华镇", "七里港镇", "象阳镇",
    "乐清经济开发区", "新光工业区", "湾港经济开发区", "大桥工业区",
    "乐清市", "温州海经区", "乐清",
}


def in_yueqing(region):
    """地点是否在乐清。空值按通过处理（列表未给地区）。

    实测坑：乐清人才网收录外地企业职位（芜湖、武汉、喀什、上海奉贤…），
    不滤会把安徽、湖北的岗位混进乐清名单。
    """
    s = (region or "").strip()
    if not s:
        return True, ""
    parts = [p for p in re.split(r"[/、,，\s|]+", s) if p]
    for p in parts:
        if p in YUEQING_AREAS or "乐清" in p:
            return True, ""
    return False, s

UNIT = {"万": 10000, "w": 10000, "W": 10000, "k": 1000, "K": 1000, "千": 1000}


def load(path):
    if not os.path.exists(path):
        return []
    out = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


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
    """返回 (下限月薪 或 None, 类型: ok/negotiable/unknown)"""
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
        low = low / 12.0
    return low, "ok"


def norm_company(name):
    s = (name or "").strip()
    s = re.sub(r"\s+", "", s)
    s = s.replace("（", "(").replace("）", ")").replace("　", "")
    return s


def norm_title(title):
    s = (title or "").strip()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[（）()【】\[\]「」<>《》]", "", s)
    return s


def judge_weekend(rec):
    """返回 (是否双休, 判定说明)

    判定顺序（实测踩坑后定稿）：
      1) 标签里明确写了「单休」「单双休」→ 不是双休
      2) 标题里写了 单双休/大小周/周休一天半/5.5天 → 不是双休
      3) 标题里写了「双休」→ 是双休（有职位标题写双休但没勾标签，
         实测「开关工程师/工程部经理/总工（双休）」就是这种）
      4) 福利标签含「双休」→ 是双休
      5) 其余 → 无法确认，剔除（乐清人才网 welfare=5 筛选不精确，
         200 条里 45 条根本没双休标签，不能默认当双休）
    """
    welfare = rec.get("welfare") or ""
    tags = [t for t in welfare.split("|") if t]
    title = rec.get("title") or ""
    if ("单休" in tags) or ("单双休" in tags):
        return False, "标签含单休/单双休"
    if NOT_WEEKEND_RE.search(title):
        return False, "标题写明非双休"
    if "双休" in title:
        return True, ""
    if "双休" in tags:
        return True, ""
    return False, "无双休标签"


def judge_edu(rec):
    """返回 (学历文本, 是否通过, 备注)"""
    edu = (rec.get("edu_req") or "").strip()
    if not edu:
        return "未标注", True, "卡片未显示学历(按不限处理)"
    if EXP_LIKE_RE.match(edu):
        return "未标注", True, "学历位显示成经验(%s),按不限处理" % edu
    if edu in EDU_OK:
        return edu, True, ""
    if edu in EDU_BAD:
        return edu, False, ""
    # 其他杂值：保守按通过但标记
    return edu, True, "学历取值未见过，按通过处理"


def build():
    recs = []
    seen_url = set()
    dup_url = 0
    for path, site in RAW_FILES:
        for r in load(path):
            u = r.get("detail_url")
            if u and u in seen_url:
                dup_url += 1
                continue
            if u:
                seen_url.add(u)
            r["_site"] = site
            recs.append(r)

    stats = {"raw_total": len(recs), "dup_same_url": dup_url}

    # 地点过滤：只要乐清本地
    local, out_of_town = [], []
    for r in recs:
        ok, where = in_yueqing(r.get("region"))
        if ok:
            local.append(r)
        else:
            r["_drop_reason"] = "地点不在乐清: " + where
            out_of_town.append(r)
    stats["location_dropped"] = len(out_of_town)

    weekend_ok = []
    dropped_weekend = 0
    for r in local:
        ok, why = judge_weekend(r)
        if ok:
            weekend_ok.append(r)
        else:
            dropped_weekend += 1
            r["_drop_reason"] = why
    stats["weekend_ok"] = len(weekend_ok)
    stats["weekend_dropped"] = dropped_weekend

    main, negotiable, edu_out, low_pay, non_job = [], [], [], [], []
    for r in weekend_ok:
        low, kind = parse_salary(r.get("salary_raw"))
        edu_text, edu_pass, edu_note = judge_edu(r)
        r["_low"] = low
        r["_kind"] = kind
        r["_edu_text"] = edu_text
        r["_edu_note"] = edu_note
        # 培训机构招生不是招聘岗位，先挑出来单列
        if judge_nature(r) == "机构招生(非岗位)":
            non_job.append(r)
            continue
        if not edu_pass:
            edu_out.append(r)
            continue
        if kind == "negotiable":
            negotiable.append(r)
            continue
        if kind == "unknown":
            negotiable.append(r)
            continue
        if low is None or low < SALARY_FLOOR:
            low_pay.append(r)
            continue
        main.append(r)

    stats["non_job_training"] = len(non_job)
    stats["main"] = len(main)
    stats["negotiable"] = len(negotiable)
    stats["edu_dropped"] = len(edu_out)
    stats["pay_dropped"] = len(low_pay)

    # 跨站去重
    seen = {}
    deduped = []
    dup_pairs = 0
    for r in main:
        key = (norm_company(r.get("company")), norm_title(r.get("title")))
        if key in seen:
            dup_pairs += 1
            prev = seen[key]
            prev["_site"] = prev["_site"] + " + " + r["_site"]
            # 保留信息更全的薪资原文
            if len(r.get("salary_raw") or "") > len(prev.get("salary_raw") or ""):
                prev["salary_raw"] = r["salary_raw"]
            continue
        seen[key] = r
        deduped.append(r)
    stats["cross_site_dup"] = dup_pairs
    stats["main_deduped"] = len(deduped)

    deduped.sort(key=lambda x: (-(x["_low"] or 0), x.get("company") or ""))
    negotiable.sort(key=lambda x: (x.get("company") or ""))

    stats["salary_parse_failed"] = sum(1 for r in deduped if r["_low"] is None)
    return deduped, negotiable, edu_out, low_pay, non_job, stats


HEADERS = ["序号", "职位", "公司", "月薪下限(元)", "薪资原文", "学历要求",
           "经验要求", "地点/乡镇", "双休", "岗位性质提示", "福利标签", "发布时间", "来源", "链接"]

# 岗位性质识别：这些"职位"要么不是真实岗位，要么薪资是提成上限，
# 用户是找正式工作，必须先分清，否则会被"10K"骗进去
RE_TRAINING = re.compile(r"编程培训|培训学校|教育~|网校|学习$|学习\b|招生|集中营|专注.*培训")
RE_INSURANCE = re.compile(r"保险|平安|人寿|泰康|太平洋保险|新华保险|证券|贷款|理财|金融|财富管理|康养顾问|优才")
RE_DELIVERY = re.compile(r"配送员|骑手|外卖|闪送|跑腿|快递员")
RE_REALESTATE = re.compile(r"房产|置业|地产经纪|房屋中介")
RE_STAFFING = re.compile(r"人力资源服务|劳务派遣")


def judge_nature(rec):
    """返回 岗位性质 标签"""
    t = (rec.get("title") or "")
    c = (rec.get("company") or "")
    both = t + " " + c
    if RE_TRAINING.search(t) or RE_TRAINING.search(c):
        return "机构招生(非岗位)"
    if RE_INSURANCE.search(both):
        return "保险/金融销售(薪资多为提成)"
    if RE_DELIVERY.search(t):
        return "配送/骑手(计件为主)"
    if RE_REALESTATE.search(both):
        return "房产中介"
    if RE_STAFFING.search(c):
        return "人力中介代招"
    return "企业直招"


def row_of(i, r):
    return [i, r.get("title") or "", r.get("company") or "",
            int(r["_low"]) if r.get("_low") else "",
            r.get("salary_raw") or "",
            r.get("_edu_text") or "",
            r.get("exp_req") or "",
            r.get("region") or "",
            "是" if judge_weekend(r)[0] else "待核实",
            judge_nature(r),
            r.get("welfare") or "",
            r.get("published") or "",
            r.get("_site") or "",
            r.get("detail_url") or ""]


HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)
THIN_WRAP = Alignment(vertical="top", wrap_text=True)
WIDTHS = [6, 26, 34, 12, 16, 10, 10, 22, 7, 24, 34, 12, 22, 52]


def write_sheet(ws, rows, title_note=""):
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
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{ws.max_row}"
    if title_note:
        ws.title = title_note


def write_gov_sheet(ws, gov_rows):
    heads = ["序号", "发布栏目", "公告标题", "日期", "正文提到大专/中专/不限学历", "属编外/劳务派遣", "提到乐清", "学历原文片段", "链接"]
    ws.append(heads)
    for c in ws[1]:
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
    for i, r in enumerate(gov_rows, 1):
        ws.append([i, r.get("col", ""), r.get("title", ""), r.get("date", ""),
                   "是" if r.get("has_low_edu") else "否",
                   "是" if r.get("is_labor") else "",
                   "是" if r.get("in_yueqing") else "",
                   (r.get("edu_snippet") or "")[:300],
                   r.get("url", "")])
    for idx, w in enumerate([6, 20, 56, 12, 16, 14, 10, 60, 60], 1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.alignment = THIN_WRAP
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:I{ws.max_row}"


def main():
    main_rows, negotiable, edu_out, low_pay, non_job, stats = build()
    stamp = datetime.now().strftime("%Y%m%d")
    os.makedirs(CLEAN_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    write_sheet(ws, main_rows, "符合条件")

    ws2 = wb.create_sheet("薪资面议")
    write_sheet(ws2, negotiable)

    ws3 = wb.create_sheet("被剔除-低薪")
    write_sheet(ws3, low_pay)

    ws4 = wb.create_sheet("被剔除-学历")
    write_sheet(ws4, edu_out)

    gov = []
    if os.path.exists(GOV_FILE):
        with io.open(GOV_FILE, encoding="utf-8") as f:
            gov = json.load(f)
        gov.sort(key=lambda x: (not x.get("has_low_edu"), x.get("date", "")), reverse=False)
        gov.sort(key=lambda x: x.get("date", ""), reverse=True)
    ws5 = wb.create_sheet("政府渠道公告")
    write_gov_sheet(ws5, gov)
    stats["gov_notices"] = len(gov)
    stats["gov_low_edu"] = sum(1 for r in gov if r.get("has_low_edu"))
    stats["gov_in_yueqing"] = sum(1 for r in gov if r.get("in_yueqing"))

    ws6 = wb.create_sheet("机构招生(非岗位)")
    write_sheet(ws6, non_job)

    xlsx = os.path.join(CLEAN_DIR, f"乐清-双休高薪-{stamp}.xlsx")
    wb.save(xlsx)

    csv_path = os.path.join(CLEAN_DIR, f"乐清-双休高薪-{stamp}.csv")
    import csv
    with io.open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for i, r in enumerate(main_rows, 1):
            w.writerow(row_of(i, r))

    stats["xlsx"] = xlsx
    stats["csv"] = csv_path
    stats["by_site"] = {}
    for r in main_rows:
        stats["by_site"][r["_site"]] = stats["by_site"].get(r["_site"], 0) + 1
    stats["salary_min"] = min([int(r["_low"]) for r in main_rows], default=0)
    stats["salary_max"] = max([int(r["_low"]) for r in main_rows], default=0)
    rp = os.path.join(REPORT_DIR, f"clean_jobs_{stamp}.json")
    with io.open(rp, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("\n主表前 15 条：")
    for i, r in enumerate(main_rows[:15], 1):
        print(f"  {i:2d}. {r['_low']:>6.0f} | {r['_edu_text']:<4s} | {r['title'][:24]:<26s} | {r['company'][:20]:<22s} | {r['region'][:14]}")


if __name__ == "__main__":
    main()