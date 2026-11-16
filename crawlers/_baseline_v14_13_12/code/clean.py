# -*- coding: utf-8 -*-
"""
整理脚本（clean.py）
===================

把 data/raw/<job>.jsonl（爬下来的原始数据）整理成 out/<job>_clean.xlsx。

做四件事：
    1. 去重（同一个 detail_url 只留第一次抓到的）
    2. 字段清洗（价格去货币符号转数字、评分英文转 1~5、库存转是/否）
    3. 质量检查（哪些字段有空值、空了多少）
    4. 导出 Excel（首行冻结、自动筛选、列宽自适应、表头加粗）

运行：
    D:\\agent-work\\venv\\Scripts\\python.exe D:\\agent-work\\crawlers\\clean.py
    D:\\agent-work\\venv\\Scripts\\python.exe D:\\agent-work\\crawlers\\clean.py --job books
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TZ = timezone(timedelta(hours=8))

DEFAULTS = {
    "job": "books",
    "raw_dir": r"D:\agent-work\data\raw",
    "out_dir": r"D:\agent-work\out",
    "log_dir": r"D:\agent-work\logs",
}

RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def load_jsonl(path):
    rows = []
    bad = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return rows, bad


def to_number_price(s):
    """'£51.77' -> 51.77；解析不了就留空（NaN）"""
    if s is None:
        return None
    txt = str(s).strip()
    for ch in "£$¥ €,":
        txt = txt.replace(ch, "")
    txt = txt.strip()
    try:
        return float(txt)
    except ValueError:
        return None


def enrich_status(df, job):
    """
    状态字段分两层（重要设计）：

      status_img       原始事实：详情页里那张图的文件名（不解析、不假设）
      valid_status     映射结果：按站点模块的 STATUS_MAP 翻译成中文
      status_confirmed 映射是否可信（未确认的映射标 False）
      status_derived   推断结果：只根据 生效日期 / 废止日期 推出来的状态

    为什么要在 clean 阶段重算：
      映射写在抓取阶段的话，一旦确认 jdxwj.gif 的真实含义，就得重抓 20 条。
      现在只要改 sites/<job>.py 的 STATUS_MAP，重跑 clean 即可，不用再请求网站。
    """
    if "status_img" not in df.columns:
        return df

    # 1) 用站点模块的 STATUS_MAP 重算映射（拿不到就保留抓取时的值）
    status_map = {}
    try:
        import importlib
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        mod = importlib.import_module("sites." + job)
        status_map = getattr(mod, "STATUS_MAP", {}) or {}
    except Exception as e:
        print("状态映射: 未能加载 sites/%s.py（%s），保留抓取时的 valid_status" % (job, type(e).__name__))

    if status_map:
        def _map(x):
            return status_map.get(x, ("未知", False))
        df["valid_status"] = df["status_img"].map(lambda x: _map(x)[0])
        df["status_confirmed"] = df["status_img"].map(lambda x: _map(x)[1])
        print("状态映射: 已按 sites/%s.py 的 STATUS_MAP 重算（%d 条规则）" % (job, len(status_map)))

    # 2) 派生状态：只看日期，不依赖图标含义
    from datetime import date as _date

    def _parse(d):
        try:
            y, m, dd = str(d).split("-")
            return _date(int(y), int(m), int(dd))
        except Exception:
            return None

    today = datetime.now(TZ).date()

    def _derive(row):
        ab = str(row.get("abolish_date") or "").strip()
        if ab and ab not in ("暂无", "", "-", "—"):
            return "已废止（推断）"
        eff = _parse(row.get("effective_date"))
        if eff is None:
            return "未知"
        if eff <= today:
            return "现行有效（推断）"
        return "即将实施（推断）"

    df["status_derived"] = df.apply(_derive, axis=1)
    return df


def main():
    ap = argparse.ArgumentParser(description="把原始 jsonl 整理成 Excel")
    ap.add_argument("--job", default=DEFAULTS["job"])
    ap.add_argument("--dedup-key", default=None, dest="dedup_key",
                    help="按哪一列去重；不指定则自动找 detail_url / quote_key / url / id")
    ap.add_argument("--site", default=None,
                    help="状态映射用哪个站点模块（默认同 job 名）。"
                         "跑 A/B 时 job 名带后缀（如 foodlaw_att1），就靠它指回 foodlaw")
    ap.add_argument("--format", default="xlsx",
                    help="导出格式，逗号分隔：xlsx,csv,json（默认 xlsx）")
    args = ap.parse_args()

    job = args.job
    raw_path = os.path.join(DEFAULTS["raw_dir"], "%s.jsonl" % job)
    os.makedirs(DEFAULTS["out_dir"], exist_ok=True)

    if not os.path.exists(raw_path):
        print("找不到原始数据：%s" % raw_path)
        print("先把爬虫跑起来，它会生成这个文件。")
        return 2

    rows, bad_lines = load_jsonl(raw_path)
    print("读入        : %d 条（坏行 %d 条已跳过）" % (len(rows), bad_lines))
    if not rows:
        print("没有数据，结束。")
        return 1

    df = pd.DataFrame(rows)
    n0 = len(df)

    # ---------- 1. 去重 ----------
    # 早期版本把 detail_url 写死，换到没有这个字段的站点就静默跳过去重。
    # 现在自动探测 + 允许 --dedup-key 指定。
    keycol = args.dedup_key
    if not keycol:
        for cand in ("detail_url", "quote_key", "url", "id"):
            if cand in df.columns:
                keycol = cand
                break
    if keycol and keycol in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=[keycol], keep="first")
        print("去重        : %d -> %d（按 %s，丢掉 %d 条）"
              % (before, len(df), keycol, before - len(df)))
    else:
        print("去重        : 没找到合适的去重列，跳过（可用 --dedup-key 指定）")

    # ---------- 2. 字段清洗 ----------
    if "price_raw" in df.columns:
        df["price"] = df["price_raw"].map(to_number_price)
        print("价格        : 已从 %s 转成数字（%d 条解析失败留空）"
              % ("price_raw", int(df["price"].isna().sum())))

    if "rating" in df.columns:
        df["rating_num"] = df["rating"].map(RATING_MAP)
        unmapped = df["rating_num"].isna() & df["rating"].notna()
        if unmapped.any():
            print("评分        : 有 %d 条英文评分配不上（检查 RATING_MAP）" % int(unmapped.sum()))
        else:
            print("评分        : 已从英文转成 1~5 数字")

    if "availability" in df.columns:
        df["in_stock"] = df["availability"].fillna("").str.contains("In stock", case=False)
        print("库存        : 已转成 True/False（True = 有货）")

    if "title" in df.columns:
        df["title"] = df["title"].fillna("").str.strip()
        df = df[df["title"] != ""]          # 标题空的是废数据

    if "fetched_at" in df.columns:
        dt = pd.to_datetime(df["fetched_at"], errors="coerce")
        df["fetched_date"] = dt.dt.strftime("%Y-%m-%d")

    # ---------- 2.5 状态字段增强（原始 / 映射 / 推断 三层）----------
    df = enrich_status(df, getattr(args, "site", None) or job)

    # ---------- 3. 质量检查 ----------
    # 空值必须同时算两种：
    #   NaN / None        —— 字段缺失
    #   空字符串 / 纯空白  —— 字段存在但没值（如 tags 为空）
    # 早期版本只算 isna()，导致"tags 是空字符串"被报成"零空值"，
    # 但导出 CSV 后空串会变成空字段，读者在 Excel 里看到的就是真空。
    def count_blank(series):
        try:
            ss = series.astype("string")
            return int((ss.isna() | (ss.str.strip() == "")).sum())
        except Exception:
            return int(series.isna().sum())

    def count_nan(series):
        return int(series.isna().sum())

    print("")
    print("字段空值统计（空值 = 缺失 或 空字符串）：")
    total = len(df)
    any_blank = False
    blank_detail = {}
    for col in df.columns:
        miss = count_blank(df[col])
        if miss:
            any_blank = True
            nan_only = count_nan(df[col])
            empty_str = miss - nan_only
            blank_detail[col] = {"blank": miss, "nan": nan_only, "empty_str": empty_str}
            print("  %-14s 空 %4d / %-4d  (%.1f%%)   其中 缺失 %d / 空字符串 %d"
                  % (col, miss, total, miss * 100.0 / total, nan_only, empty_str))
    empty_cols = [c for c in df.columns if count_blank(df[c]) == total]
    if empty_cols:
        print("  整列为空（选择器可能写错了）：%s" % ", ".join(empty_cols))
    if not any_blank:
        print("  （无空值：既没有缺失，也没有空字符串）")

    # ---------- 3.5 附件列扁平化 ----------
    # attachments 是 [{url,status,bytes,...}] 这样的列表，直接丢给 openpyxl 会报
    # "Cannot convert [...] to Excel"（list 不是可写单元格类型）。
    # 处理成：完整明细存成 JSON 字符串（不丢信息）+ 两个好用的计数列。
    if "attachments" in df.columns:
        import json as _json

        def _att_json(v):
            if isinstance(v, list):
                return _json.dumps(v, ensure_ascii=False)
            if v is None or (isinstance(v, float) and v != v):
                return ""
            return str(v)

        def _att_count(v, only_ok=False):
            if not isinstance(v, list):
                return 0
            if only_ok:
                return sum(1 for a in v if isinstance(a, dict) and a.get("status") == "ok")
            return len(v)

        df["attachments_count"] = df["attachments"].apply(_att_count)
        df["attachments_ok"] = df["attachments"].apply(lambda v: _att_count(v, True))
        df["attachments"] = df["attachments"].apply(_att_json)
        print("附件列: 已转成 JSON 字符串，并新增 attachments_count / attachments_ok")

    # ---------- 4. 导出（xlsx / csv / json 任选，可多选）----------
    # 列顺序：业务字段在前，血缘字段在后
    front = [c for c in ["title", "price", "rating", "rating_num", "in_stock",
                         "availability", "price_raw", "detail_url", "thumb_url"]
             if c in df.columns]
    back = [c for c in ["source_url", "fetched_at", "fetched_date", "http_status",
                        "content_hash", "run_id"] if c in df.columns]
    rest = [c for c in df.columns if c not in front and c not in back]
    df = df[front + rest + back]

    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    formats = [f.strip().lower() for f in args.format.split(",") if f.strip()]
    if not formats:
        formats = ["xlsx"]

    outputs = {}

    for fmt in formats:
        path = os.path.join(DEFAULTS["out_dir"], "%s_clean_%s.%s" % (job, stamp, fmt))

        if fmt == "xlsx":
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name=job)
                ws = writer.sheets[job]

                from openpyxl.styles import Font, PatternFill, Alignment
                head_fill = PatternFill("solid", fgColor="DDEBF7")
                for cell in ws[1]:
                    cell.font = Font(bold=True)
                    cell.fill = head_fill
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                for idx, col in enumerate(df.columns, start=1):
                    # 必须强制 str()：pandas 3.x 里含 NA 的列 astype(str) 仍可能留下
                    # float 的 nan，后面 ord(ch) 迭代会抛 "'float' object is not iterable"
                    sample = [str(x) for x in df[col].head(200).tolist()]
                    width = max([len(str(col)) * 2] + [
                        len(s) * 2 if any(ord(ch) > 127 for ch in s) else len(s)
                        for s in sample]) if sample else 12
                    ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = min(max(width + 2, 10), 60)

                ws.freeze_panes = "A2"
                ws.auto_filter.ref = ws.dimensions

        elif fmt == "csv":
            # utf-8-sig：带 BOM，Excel 双击中文不乱码
            df.to_csv(path, index=False, encoding="utf-8-sig")

        elif fmt == "json":
            # records 格式：一个数组，每条是对象；NaN 会变成 null
            df.to_json(path, orient="records", force_ascii=False, indent=2)

        else:
            print("跳过未知格式: %s（只支持 xlsx / csv / json）" % fmt)
            continue

        outputs[fmt] = path
        print("")
        print("导出 %-5s: %s" % (fmt, path))
        print("              %d 行 x %d 列，%.1f KB" % (len(df), len(df.columns),
                                                      os.path.getsize(path) / 1024))

    print("")
    print("列          : %s" % ", ".join(df.columns))

    # ---------- 5. 运行摘要 ----------
    summary = {
        "job": job,
        "raw_file": raw_path,
        "out_files": outputs,          # {格式: 路径}
        "raw_records": n0,
        "clean_rows": int(len(df)),
        "columns": list(df.columns),
        "blank_fields": blank_detail,  # {列: {blank, nan, empty_str}}
        "bad_lines": bad_lines,
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
    }
    sp = os.path.join(DEFAULTS["log_dir"], "clean-%s-%s.json" % (job, stamp))
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("摘要        : %s" % sp)
    return 0


if __name__ == "__main__":
    sys.exit(main())