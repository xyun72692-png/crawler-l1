# -*- coding: utf-8 -*-
"""
从单文件生成三层投递清单（0 个请求）。

输入（只读这一个）：D:\\agent-work\\data\\raw\\wzrc_dw_20261111.jsonl
输出：D:\\agent-work\\out\\wzrc_dw_20261111_投递清单_<时间戳>.xlsx（5 个 sheet）

口径（按《阶段B-筛选指令-三层投递清单》执行）：
  · 基准日写死 2026-11-11，不用 now()，保证可复现
  · published 三种形态分开算：绝对日期 / 相对时间（N天前=age N，N小时前=age 0）/ 空
  · 分桶：A ≤30 天（含相对时间）｜B 31~90｜C >90｜D 空或无法解析
  · 去重：公司+岗位（去空白、全角括号转半角），A/B 层内做，保留最新，记同岗位条数
  · 地区分组：乐清 / 温州市区 / 温州其他县市 / 其他
"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

AGENT = Path(os.environ.get("CRAWLER_HOME") or Path(__file__).resolve().parent.parent)
IN_FILE = AGENT / "data" / "raw" / "wzrc_dw_20261111.jsonl"
OUT_DIR = AGENT / "out"
BASE_DATE = date(2026, 11, 11)      # 写死，保证可复现

# ---------------------------------------------------------------- 解析

def parse_published(raw):
    """
    返回 (age_days, kind)
      kind: 'abs' 绝对日期 / 'rel' 相对时间 / 'none' 空
    """
    s = (raw or "").strip()
    if not s:
        return None, "none"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return (BASE_DATE - date(y, mo, d)).days, "abs"
        except ValueError:
            return None, "none"
    # 相对时间
    if "刚刚" in s:
        return 0, "rel"
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        return 0, "rel"
    m = re.search(r"(\d+)\s*小时前", s)
    if m:
        return 0, "rel"          # 小时级一律算今天
    m = re.search(r"(\d+)\s*天前", s)
    if m:
        return int(m.group(1)), "rel"
    m = re.search(r"(\d+)\s*个月前", s)
    if m:
        return int(m.group(1)) * 30, "rel"
    return None, "none"


def norm_key(text):
    """公司+岗位归一化：去所有空白、全角括号转半角、转小写。"""
    s = unicodedata.normalize("NFKC", (text or ""))
    s = re.sub(r"\s+", "", s)
    return s.lower()


def salary_lower(raw):
    """把 '3K-5K/月' / '1万-1.5万/月' / '面议' 解析成「下限，单位 K」。解析失败返回 None。"""
    s = (raw or "").strip()
    if not s:
        return None
    if "面议" in s:
        return None
    part = re.split(r"[-~—到]", s)[0]
    m = re.search(r"(\d+(?:\.\d+)?)\s*(K|k|千|万)", part)
    if m:
        num = float(m.group(1))
        return num * 10 if m.group(2) == "万" else num
    m = re.search(r"(\d+(?:\.\d+)?)", part)
    if m:
        return float(m.group(1)) / 1000.0      # 纯数字按元算
    return None


def salary_band(v):
    if v is None:
        return "未知/面议"
    if v < 5:
        return "<5K"
    if v < 8:
        return "5-8K"
    if v < 12:
        return "8-12K"
    return ">12K"


def region_group(region):
    r = region or ""
    if "乐清" in r:
        return "乐清"
    if any(x in r for x in ("鹿城", "瓯海", "龙湾", "洞头")):
        return "温州市区"
    if "温州" in r:
        return "温州其他县市"
    return "其他"


# ---------------------------------------------------------------- 读数据

rows = []
with IN_FILE.open(encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))

print("输入文件：%s" % IN_FILE)
print("输入行数：%d" % len(rows))

for r in rows:
    age, kind = parse_published(r.get("published"))
    r["_age"] = age
    r["_kind"] = kind
    if kind == "none":
        r["_bucket"] = "D"
    elif age <= 30:
        r["_bucket"] = "A"
    elif age <= 90:
        r["_bucket"] = "B"
    else:
        r["_bucket"] = "C"
    r["_salary"] = salary_lower(r.get("salary_raw"))
    r["_rgroup"] = region_group(r.get("region"))

cnt = Counter(r["_bucket"] for r in rows)
print("分桶（去重前）：A=%d  B=%d  C=%d  D=%d  合计=%d"
      % (cnt["A"], cnt["B"], cnt["C"], cnt["D"],
         cnt["A"] + cnt["B"] + cnt["C"] + cnt["D"]))

# ---------------------------------------------------------------- 去重（全表口径，用于验收第 2 条）

seen = OrderedDict()
merged_total = 0
for r in rows:
    k = norm_key(r.get("company")) + "|" + norm_key(r.get("title"))
    if k in seen:
        merged_total += 1
    else:
        seen[k] = 1
print("全表去重：%d -> %d（合并掉 %d 条）" % (len(rows), len(seen), merged_total))

# ---------------------------------------------------------------- A/B 层内去重

def dedup_layer(items):
    """同「公司+岗位」只留 published 最新的一条；记同岗位条数。"""
    groups = {}
    for r in items:
        k = norm_key(r.get("company")) + "|" + norm_key(r.get("title"))
        groups.setdefault(k, []).append(r)
    out = []
    for k, g in groups.items():
        # 最新：age 小的优先；age 相同时取先出现的
        g_sorted = sorted(g, key=lambda x: (x["_age"] if x["_age"] is not None else 10 ** 6))
        main = dict(g_sorted[0])
        main["_dup"] = len(g)
        out.append(main)
    return out


def sort_key(r):
    age = r["_age"] if r["_age"] is not None else 10 ** 6
    sal = r["_salary"]
    return (age, 0 if sal is not None else 1, -(sal if sal is not None else 0))


A_raw = [r for r in rows if r["_bucket"] == "A"]
B_raw = [r for r in rows if r["_bucket"] == "B"]
C_raw = [r for r in rows if r["_bucket"] == "C"]
D_raw = [r for r in rows if r["_bucket"] == "D"]

A = sorted(dedup_layer(A_raw), key=sort_key)
B = sorted(dedup_layer(B_raw), key=sort_key)
C = dedup_layer(C_raw)
D = D_raw

# ---------------------------------------------------------------- 写 xlsx

HEAD = ["序号", "职位", "公司", "地区分组", "地区", "薪资", "学历", "经验",
        "发布时间(原文)", "年龄(天)", "同岗位条数", "详情链接", "福利"]


def row_of(idx, r):
    return [idx, r.get("title"), r.get("company"), r["_rgroup"], r.get("region"),
            r.get("salary_raw"), r.get("edu_req"), r.get("exp_req"),
            r.get("published"), r["_age"], r.get("_dup", 1),
            r.get("detail_url"), r.get("welfare")]


wb = Workbook()
ws0 = wb.active
ws0.title = "⓪统计"

def sheet(title, head, data, widths=None):
    ws = wb.create_sheet(title)
    ws.append(head)
    for c in range(1, len(head) + 1):
        ws.cell(row=1, column=c).font = Font(bold=True)
        ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
    for i, r in enumerate(data, 1):
        ws.append(row_of(i, r))
    for c in range(1, len(head) + 1):
        ws.column_dimensions[get_column_letter(c)].width = (widths or {}).get(c, 16)
    ws.freeze_panes = "A2"
    return ws

w = {1: 6, 2: 24, 3: 28, 4: 12, 5: 22, 6: 14, 7: 8, 8: 10, 9: 14, 10: 9, 11: 10, 12: 52, 13: 34}
sheet("①A-可直接投", HEAD, A, w)
sheet("②B-备选(31~90天)", HEAD, B, w)
wsC = sheet("③C-仅公司画像(>90天)", HEAD + ["备注"], C, {**w, 14: 22})
for row in wsC.iter_rows(min_row=2, min_col=14, max_col=14):
    for cell in row:
        cell.value = "发布过久，不建议投"
# ④D 与 ①②③ 用同一套 13 列表头（row_of 永远返回 13 列）。
# 之前这里手写了 7 列表头，于是"薪资"列显示的是地区、"详情链接"列显示的是学历 —— 典型错位。
# D 层没有发布时间和年龄，那两列留空即可，不要为了"整齐"去改 row_of()。
sheet("④D-日期缺失", HEAD, D, w)

# ---- 统计 sheet 内容
lines = [
    ("输入文件", str(IN_FILE)),
    ("输入行数", len(rows)),
    ("基准日（写死）", str(BASE_DATE)),
    ("", ""),
    ("A 层（≤30 天，含相对时间，去重前）", cnt["A"]),
    ("B 层（31~90 天，去重前）", cnt["B"]),
    ("C 层（>90 天，去重前）", cnt["C"]),
    ("D 层（日期为空/无法解析）", cnt["D"]),
    ("A+B+C+D", cnt["A"] + cnt["B"] + cnt["C"] + cnt["D"]),
    ("", ""),
    ("全表去重后条数", len(seen)),
    ("全表去重合并掉", merged_total),
    ("A 层去重后", len(A)),
    ("B 层去重后", len(B)),
    ("C 层去重后", len(C)),
    ("", ""),
    ("A 层地区分组", ""),
]
for k, v in sorted(Counter(r["_rgroup"] for r in A_raw).items(), key=lambda x: -x[1]):
    lines.append(("    " + k, v))
lines.append(("", ""))
lines.append(("A 层薪资区间", ""))
for k in ("<5K", "5-8K", "8-12K", ">12K", "未知/面议"):
    n = sum(1 for r in A_raw if salary_band(r["_salary"]) == k)
    lines.append(("    " + k, n))
lines.append(("", ""))
lines.append(("薪资原文为空", sum(1 for r in rows if not (r.get("salary_raw") or "").strip())))
lines.append(("薪资含「面议」", sum(1 for r in rows if "面议" in (r.get("salary_raw") or ""))))
lines.append(("published 为空", sum(1 for r in rows if not (r.get("published") or "").strip())))

ws0.append(["项目", "值"])
for c in (1, 2):
    ws0.cell(row=1, column=c).font = Font(bold=True)
    ws0.cell(row=1, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
for k, v in lines:
    ws0.append([k, v])
ws0.column_dimensions["A"].width = 38
ws0.column_dimensions["B"].width = 60
for row in ws0.iter_rows(min_row=1):
    row[0].alignment = Alignment(vertical="center")

OUT_DIR.mkdir(parents=True, exist_ok=True)
stamp = "20261111-2130"
out = OUT_DIR / ("wzrc_dw_20261111_投递清单_%s.xlsx" % stamp)
wb.save(out)

print()
print("=" * 62)
print("输出：%s" % out)
print("Sheet ①A  %d 行" % len(A))
print("Sheet ②B  %d 行" % len(B))
print("Sheet ③C  %d 行" % len(C))
print("Sheet ④D  %d 行" % len(D))
print("=" * 62)
print("验收1  A 层（去重前）= %d   期望 86   %s" % (cnt["A"], "PASS" if cnt["A"] == 86 else "FAIL"))
print("验收2  全表去重后   = %d   期望 486  %s" % (len(seen), "PASS" if len(seen) == 486 else "FAIL"))
print("验收3  A+B+C+D      = %d   期望 502  %s"
      % (cnt["A"] + cnt["B"] + cnt["C"] + cnt["D"],
         "PASS" if cnt["A"] + cnt["B"] + cnt["C"] + cnt["D"] == 502 else "FAIL"))
print("验收4  输入路径      = %s（只有一个）" % IN_FILE.name)
empty_sal = sum(1 for r in rows if not (r.get("salary_raw") or "").strip())
mianyi = sum(1 for r in rows if "面议" in (r.get("salary_raw") or ""))
print("验收5  薪资空/面议   = %d / %d   %s"
      % (empty_sal, mianyi, "PASS" if empty_sal == 0 and mianyi == 0 else "FAIL"))