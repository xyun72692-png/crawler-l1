# -*- coding: utf-8 -*-
"""
郑州 2026-11-01 ~ 11-16 天气（v2：按第十八章 18.0.1 A 型「单点权威」重做）

判型：天气 = A 型（单点权威），1 个源，找到就停 → 中央气象台 www.nmc.cn
     （第十八章 18.2 天气排序：API → 一手 → 聚合/门户；上一版把顺序搞反了）

数据源（按权威性排序，实测）
  ① 中央气象台 NMC  rest/weather?stationid=YVItN（郑州）
     - data.tempchart：11-09 ~ 11-16 历史（8 天）+ 11-17~11-22 预报，官方温度曲线
     - data.predict.detail：7 天预报（含天气现象文字）
     - data.real：当前实况（11-16 23:30：7.6℃ / 小雨 / 湿度 90% / 降水 0.9mm）
     - 交叉验证：11-16 逐小时实况最高 11.2℃ == tempchart 11.2℃ → tempchart 是观测，不是模式产品
  ② 历史天气网（第三方聚合，官方接口不含 11-01~11-08）—— 仅补前 8 天，逐行标注

天气现象口径
  - 11-01~11-08：历史天气网（第三方）
  - 11-09~11-15：官方 tempchart 的 day_text/night_text = "9999"（缺），如实写「官方未公开」
  - 11-16：官方 predict.detail 夜间「小雨」

用法：
    python tools\\weather_zhengzhou.py
"""
import json
import pathlib
import re

from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = ROOT / "data" / "raw" / "_probe_weather"
OUT_DIR = ROOT / "out"

WEEK = {"01": "周日", "02": "周一", "03": "周二", "04": "周三", "05": "周四",
        "06": "周五", "07": "周六", "08": "周日", "09": "周一", "10": "周二",
        "11": "周三", "12": "周四", "13": "周五", "14": "周六", "15": "周日",
        "16": "周一"}


def load_nmc():
    """中央气象台（权威）：tempchart 历史温度 + predict 天气预报 + real 实况"""
    d = json.loads((PROBE / "nmc_weather_zz.json").read_text("utf-8"))["data"]
    rows = {}

    for x in d.get("tempchart") or []:
        day = x["time"].replace("/", "-")
        mx, mn = x.get("max_temp"), x.get("min_temp")
        if mx in (None, "9999", 9999) or mn in (None, "9999", 9999):
            continue
        rows[day] = {
            "high": round(float(mx), 1),
            "low": round(float(mn), 1),
            "weather": "",
            "wind": "",
            "src_temp": "中央气象台",
            "src_wx": "",
            "official": True,
        }

    # 预报期补天气现象（day/night 文本）
    for x in (d.get("predict") or {}).get("detail") or []:
        day = x["date"]
        if day not in rows:
            continue
        dw = (x.get("day") or {}).get("weather") or {}
        nw = (x.get("night") or {}).get("weather") or {}
        parts = []
        if dw.get("info") and dw["info"] != "9999":
            parts.append(dw["info"])
        if nw.get("info") and nw["info"] != "9999":
            parts.append(nw["info"] if not parts else f"转{nw['info']}")
        if parts:
            rows[day]["weather"] = "".join(parts)
            rows[day]["src_wx"] = "中央气象台"
        wd = (x.get("day") or {}).get("wind") or {}
        if wd.get("direct") and wd["direct"] not in ("9999", "99999999"):
            rows[day]["wind"] = f"{wd['direct']}{wd.get('power') or ''}"
    return rows


def load_tianqi():
    """历史天气网（第三方）：仅用于官方接口不覆盖的 11-01~11-08"""
    p = PROBE / "tianqi_202611.txt"
    if not p.exists():
        return {}
    soup = BeautifulSoup(p.read_text("utf-8", errors="replace"), "lxml")
    rows = {}
    for li in soup.select("ul.thrui > li"):
        divs = [d.get_text(strip=True) for d in li.find_all("div", recursive=False)]
        if len(divs) < 5:
            continue
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s*(.*)", divs[0])
        if not m:
            continue
        rows[m.group(1)] = {
            "high": float(divs[1].replace("℃", "")),
            "low": float(divs[2].replace("℃", "")),
            "weather": divs[3],
            "wind": divs[4],
            "src_temp": "历史天气网（第三方）",
            "src_wx": "历史天气网（第三方）",
            "official": False,
        }
    return rows


def main():
    nmc = load_nmc()
    tq = load_tianqi()

    dates = [f"2026-11-{d:02d}" for d in range(1, 17)]
    final = []
    for day in dates:
        if day in nmc:
            rec = dict(nmc[day], date=day, week=WEEK[day[8:]])
            if not rec["weather"]:
                rec["weather"] = "官方未公开"
                rec["src_wx"] = "—"
        elif day in tq:
            rec = dict(tq[day], date=day, week=WEEK[day[8:]])
            rec["official"] = False
        else:
            rec = {"date": day, "week": WEEK[day[8:]], "missing": True}
        final.append(rec)

    print(f"{'日期':<12}{'星期':<7}{'最高':>6}{'最低':>6}  {'天气':<16}{'风向':<10}数据源")
    print("-" * 92)
    for r in final:
        if r.get("missing"):
            print(f"{r['date']:<12}{r['week']:<7}  （无数据）")
            continue
        print(f"{r['date']:<12}{r['week']:<7}{r['high']:>5}℃{r['low']:>5}℃  "
              f"{r['weather']:<16}{r.get('wind', ''):<10}{r['src_temp']}")

    hi = [r["high"] for r in final if not r.get("missing")]
    lo = [r["low"] for r in final if not r.get("missing")]
    print("-" * 92)
    print(f"16 天：最高 {max(hi)}℃ / 最低 {min(lo)}℃")

    # 分段统计（源不同，不能混算平均）
    seg1 = [r for r in final if not r.get("missing") and not r["official"]]
    seg2 = [r for r in final if not r.get("missing") and r["official"]]
    if seg1:
        print(f"  11-01~11-08（第三方）：平均高 {sum(x['high'] for x in seg1)/len(seg1):.1f}℃ / "
              f"平均低 {sum(x['low'] for x in seg1)/len(seg1):.1f}℃")
    if seg2:
        print(f"  11-09~11-16（中央气象台）：平均高 {sum(x['high'] for x in seg2)/len(seg2):.1f}℃ / "
              f"平均低 {sum(x['low'] for x in seg2)/len(seg2):.1f}℃")

    # 导出 xlsx
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "郑州11月1-16日天气"
    head = ["日期", "星期", "最高温(℃)", "最低温(℃)", "温差(℃)", "天气", "风向风力",
            "温度来源", "天气来源", "权威级别"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
        c.alignment = Alignment(horizontal="center")

    for r in final:
        if r.get("missing"):
            ws.append([r["date"], r["week"], "", "", "", "（无数据）"])
            continue
        ws.append([r["date"], r["week"], r["high"], r["low"],
                   round(r["high"] - r["low"], 1), r["weather"], r.get("wind", ""),
                   r["src_temp"], r.get("src_wx", ""),
                   "A 型·一手权威" if r["official"] else "第三方回退"])

    for i, w in enumerate([13, 9, 11, 11, 10, 18, 14, 22, 22, 15], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    note = wb.create_sheet("数据来源与口径")
    rows = [
        ["项目", "内容"],
        ["判型（第十八章 18.0.1）", "天气 = A 型「单点权威」：一个机构产生 → 1 个源 → 找到就停"],
        ["权威源（一手）", "中央气象台 www.nmc.cn/rest/weather?stationid=YVItN（郑州）"],
        ["主数据覆盖", "tempchart 提供 11-09~11-16（8 天历史）+ 11-17~11-22（6 天预报）"],
        ["交叉验证", "11-16 逐小时实况（passedchart 24 点）最高 11.2℃ == tempchart 11.2℃，证明 tempchart 是观测而非模式"],
        ["第三方回退", "官方接口不含 11-01~11-08 → 用历史天气网 lishi.tianqi.com 补齐，逐行标注「第三方回退」"],
        ["天气现象缺口", "官方 tempchart 的 day_text/night_text 在历史日为 9999（缺），故 11-09~11-15 写「官方未公开」，不填推测"],
        ["11-16 天气", "官方 predict.detail：夜间「小雨」，降水 1.7mm"],
        ["分段平均不可合并", "两段来源不同，平均气温必须分段算：11-01~08 第三方 / 11-09~16 中央气象台"],
        ["抓取时间", "2026-11-16 23:5x；请求数：NMC 3（province/weather/校验），历史天气网 1"],
    ]
    for r in rows:
        note.append(r)
    for c in note[1]:
        c.font = Font(bold=True)
    note.column_dimensions["A"].width = 24
    note.column_dimensions["B"].width = 100

    out = OUT_DIR / "郑州天气_2026-11-01至11-16.xlsx"
    wb.save(out)
    print(f"\n已导出：{out}")
    (OUT_DIR / "_zz_weather_rows.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=1), "utf-8")
    return out


if __name__ == "__main__":
    main()
