# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""公告型（announcement）解析器 —— 政府/事业单位招聘公告。

为什么单独一个模块：
  公告型 ≠ 列表型。一条公告 = 一个单位一批岗位，报名期 5~7 天；
  岗位明细**不在正文里**，在附件（xlsx/xls/doc）的表格里。
  所以解析要做两件事：① 抽公告元信息 + 附件清单；② 解析附件里的岗位表。

实测结论（2026-11-14，浙江人社厅）：
  · **公告正文页是 SSR**：requests 直接能拿到 title/正文/4 个附件链接 ✅
  · **栏目列表页是 JS 渲染**：requests 只有 57 字壳（需要浏览器或列名单接口）
  · 附件下载走网关 `/api-gateway/jpaas-web-server/front/document/download?fileUrl=…`，
    requests 直接 GET 能拿到真文件（PK 头，xlsx）✅

用法：
    python tools\\announcement_parser.py --announce <html> [--table <xlsx>]
"""

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

DATE_RE = re.compile(r"(20\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})")
DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".wps")
JOB_HINT = ("岗位", "专业", "学历", "学位", "人数", "需求", "招聘")


def _clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def parse_announcement(html, page_url=""):
    soup = BeautifulSoup(html, "lxml")
    title = _clean(soup.title.get_text() if soup.title else "")

    # 正文：优先常见容器，退化为"文本最长的 div"
    body_el = None
    for sel in ("div.article-content", "div#zoom", "div.TRS_Editor", "div.content",
                "div.article", "div#detail", "div.article-content-box"):
        el = soup.select_one(sel)
        if el is not None and len(el.get_text(strip=True)) > 200:
            body_el = el
            break
    if body_el is None:
        divs = [d for d in soup.find_all("div") if len(d.get_text(strip=True)) > 200]
        if divs:
            body_el = max(divs, key=lambda d: len(d.get_text(strip=True)))
    body = _clean(body_el.get_text(" ", strip=True)) if body_el is not None else ""

    # 发布时间：正文/全文里第一个日期；也看 meta
    published = ""
    m = re.search(r"(?:发布(?:时间|日期)?|时间)[:：\s]*" + DATE_RE.pattern, soup.get_text(" "))
    if m:
        published = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    else:
        meta = soup.find("meta", attrs={"name": re.compile("pubdate|publishdate|author", re.I)})
        cand = (meta.get("content") if meta else "") or ""
        m2 = DATE_RE.search(cand) or DATE_RE.search(soup.get_text(" ")[:4000])
        if m2:
            published = "%s-%02d-%02d" % (m2.group(1), int(m2.group(2)), int(m2.group(3)))

    # 附件
    atts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        name = _clean(a.get_text())
        low = href.lower()
        if any(x in low for x in DOC_EXT) or ("document/download" in low):
            # 扩展名优先取文件名后缀（附件1.xlsx 的 URL 里可能同时含 .xls 与 .xlsx）
            m3 = re.search(r"(\.(?:pdf|docx?|xlsx?|zip|rar|wps))$", (name or "").lower())
            ext = m3.group(1) if m3 else ""
            if not ext:
                cands = [e for e in DOC_EXT if e in low]
                ext = max(cands, key=len) if cands else ""
            atts.append({"name": name or Path(low.split("=")[-1]).name,
                         "url": href, "ext": ext})

    # 单位（公告标题里常带，取"关于/单位名"前段）
    unit = ""
    m4 = re.search(r"(浙江省?[\u4e00-\u9fa5]{2,12}(?:部门|厅|局|中心|大学|学院|研究院|医院|学校))", title)
    if m4:
        unit = m4.group(1)

    return {
        "page_url": page_url,
        "title": title,
        "unit": unit,
        "published": published,
        "body_text": body,
        "body_len": len(body),
        "attachments": atts,
        "job_tables": [a for a in atts if a["ext"] in (".xls", ".xlsx")],
        "source_type": "announcement",
    }


def _grid_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    return [(ws.title, [[_clean(str(c.value)) if c.value is not None else "" for c in row]
                        for row in ws.iter_rows()]) for ws in wb.worksheets]


def _grid_xls(path):
    """老 .xls（OLE/BIFF）：xlrd 2.x 只支持读 .xls。"""
    import xlrd
    book = xlrd.open_workbook(str(path))
    out = []
    for sh in book.sheets():
        grid = []
        for r in range(sh.nrows):
            grid.append([_clean(str(sh.cell_value(r, c))) for c in range(sh.ncols)])
        out.append((sh.name, grid))
    return out


def parse_jobtable(path):
    """解析附件里的岗位表：自动找表头行（含 岗位/专业/学历 等关键词的那一行）。

    按**文件头**判断格式，不看后缀（实测：政府站很多 .xls 被存成 .xlsx 名字）：
        PK\x03\x04        → xlsx（openpyxl）
        D0 CF 11 E0        → xls （xlrd）
    """
    head = Path(path).read_bytes()[:8]
    if head[:2] == b"PK":
        sheets = _grid_xlsx(path)
    elif head[:4] == bytes.fromhex("D0CF11E0"):
        sheets = _grid_xls(path)
    else:
        raise ValueError("不是 Excel 文件（前 4 字节 %r）" % head[:4])

    out = []
    for sheet_name, grid in sheets:
        if not grid:
            continue
        header_idx, header = None, []
        for i, row in enumerate(grid[:12]):
            hits = sum(1 for cell in row if any(k in cell for k in JOB_HINT))
            if hits >= 2 and sum(1 for cell in row if cell) >= 3:
                header = [c for c in row]
                header_idx = i
                # 两行表头：第 1 行有空位 / 第 2 行也像表头 → 合并
                filled = sum(1 for c in header if c)
                nxt = grid[i + 1] if i + 1 < len(grid) else []
                nxt_hits = sum(1 for c in nxt if any(k in c for k in JOB_HINT))
                # 只有"表头有空位 + 下一行至少 2 个关键词"才合并（否则会把数据行吞进表头）
                if filled < len(header) * 0.8 and nxt_hits >= 2:
                    merged = []
                    for j in range(max(len(header), len(nxt))):
                        a = header[j] if j < len(header) else ""
                        b = nxt[j] if j < len(nxt) else ""
                        merged.append((a + ("/" + b if b and a != b else b)).strip("/"))
                    header, header_idx = merged, i + 1
                break
        if header_idx is None:
            continue
        rows = []
        for row in grid[header_idx + 1:]:
            if not any(row):
                continue
            rows.append({header[j] or ("col%d" % j): row[j]
                         for j in range(min(len(header), len(row)))})
        out.append({"sheet": sheet_name, "preamble": grid[:header_idx],
                    "header": header, "rows": rows, "n_rows": len(rows)})
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    ap = None
    tb = None
    i = 0
    while i < len(args):
        if args[i] == "--announce":
            ap = args[i + 1]; i += 2
        elif args[i] == "--table":
            tb = args[i + 1]; i += 2
        else:
            i += 1
    out = {}
    if ap:
        html = Path(ap).read_text(encoding="utf-8", errors="replace")
        # 浏览器 dump 出来的 HTML 可能是被 JSON 转义过的（\" 形式），先还原
        if '\\"' in html:
            html = html.replace('\\"', '"').replace("\\n", "\n")
        d = parse_announcement(html, ap)
        print("标题:", d["title"][:60])
        print("单位:", d["unit"] or "-", "| 发布:", d["published"] or "-")
        print("正文 %d 字 | 附件 %d 个（其中岗位表 %d 个）"
              % (d["body_len"], len(d["attachments"]), len(d["job_tables"])))
        for a in d["attachments"]:
            print("   [%s] %s" % (a["ext"] or "?", a["name"][:40]))
        out["announcement"] = d
    if tb:
        tabs = parse_jobtable(tb)
        for t in tabs:
            print("表 %s：表头行 %s | 数据 %d 行" % (t["sheet"], t["header"][:4], t["n_rows"]))
            if t["rows"]:
                print("   首行:", {k: v[:10] for k, v in list(t["rows"][0].items())[:5]})
        out["jobtable"] = tabs
    if len(args) >= 2:
        Path(str(_HOME / "out" / "announcement_parse.json")).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("JSON → out\\announcement_parse.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())