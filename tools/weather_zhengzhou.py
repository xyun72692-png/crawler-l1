# -*- coding: utf-8 -*-
"""
郑州 2026-11-01 ~ 11-16 天气汇总（16 天）

数据来源（全部实测抓取，脚本内置已抓样本，0 请求）：
  ① 历史天气网 lishi.tianqi.com/zhengzhou/202611.html      → 11-01 ~ 11-10（最高/最低/天气/风向风力）
  ② 中国天气网 d1.weather.com.cn calendar_new（101180101）   → 11-11 ~ 11-15 实况观测；11-16 当日预报
  ③ Open-Meteo archive API（ERA5 模式）                      → 16 天全量，作第三方对照

用法：
    python tools\\weather_zhengzhou.py            # 打印 + 导出 xlsx
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

WMO = {0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
       51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 61: "小雨", 63: "中雨",
       65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 81: "强阵雨",
       82: "暴雨", 95: "雷阵雨"}


def load_tianqi():
    """① 历史天气网 11-01 ~ 11-10"""
    p = PROBE / "tianqi_202611.txt"
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
            "week": m.group(2).strip(),
            "high": int(divs[1].replace("℃", "")),
            "low": int(divs[2].replace("℃", "")),
            "weather": divs[3],
            "wind": divs[4],
            "src_temp": "历史天气网",
            "src_wx": "历史天气网",
        }
    return rows


def load_nmc():
    """② 中国天气网日历（实况 + 当日预报）"""
    raw = (PROBE / "nmc_calendar.txt").read_text("utf-8", errors="replace")
    m = re.search(r"var\s+fc40\s*=\s*(\[.*\])\s*;?\s*$", raw, re.S)
    data = json.loads(m.group(1))
    rows = {}
    for d in data:
        date = d.get("date", "")
        if not date.startswith("202611"):
            continue
        day = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        cla = d.get("cla", "")
        hi = d.get("maxobs") or d.get("max") or ""
        lo = d.get("minobs") or d.get("min") or ""
        if not (str(hi).strip() and str(lo).strip()):
            continue
        try:
            hi_i, lo_i = int(float(hi)), int(float(lo))
        except (TypeError, ValueError):
            continue
        rows[day] = {
            "week": "星期" + d.get("wk", ""),
            "high": hi_i, "low": lo_i,
            "weather": d.get("w1") or "",
            "wind": "",
            "src_temp": "中国天气网实况" if cla == "obs" else "中国天气网当日预报",
            "src_wx": "中国天气网" if d.get("w1") else "",
        }
    return rows


def load_openmeteo():
    """③ Open-Meteo（第三方对照）"""
    d = json.loads((PROBE / "openmeteo.json").read_text("utf-8"))
    daily = d["daily"]
    rows = {}
    for i, t in enumerate(daily["time"]):
        rows[t] = {
            "high": round(daily["temperature_2m_max"][i], 1),
            "low": round(daily["temperature_2m_min"][i], 1),
            "rain": daily["precipitation_sum"][i],
            "code": daily["weather_code"][i],
            "wind": daily["wind_speed_10m_max"][i],
        }
    return rows


def main():
    tq = load_tianqi()
    nmc = load_nmc()
    om = load_openmeteo()

    dates = [f"2026-11-{d:02d}" for d in range(1, 17)]
    final = []
    for day in dates:
        rec = {"date": day}
        base = tq.get(day) or nmc.get(day)
        if not base:
            rec["missing"] = True
            final.append(rec)
            continue
        rec.update(base)
        # 天气现象缺失时用 Open-Meteo 天气码折算（明确标注为推测）
        if not rec.get("weather"):
            code = om.get(day, {}).get("code")
            rec["weather"] = f"{WMO.get(code, '未知')}（推测）" if code is not None else ""
            rec["src_wx"] = "Open-Meteo 天气码折算（推测）"
        o = om.get(day, {})
        rec["om_high"] = o.get("high")
        rec["om_low"] = o.get("low")
        rec["om_rain"] = o.get("rain")
        rec["om_wind"] = o.get("wind")
        rec["diff_high"] = round(rec["high"] - o["high"], 1) if o.get("high") is not None else None
        rec["diff_low"] = round(rec["low"] - o["low"], 1) if o.get("low") is not None else None
        final.append(rec)

    # 打印
    print(f"{'日期':<12}{'星期':<8}{'最高':>5}{'最低':>6}{'天气':<14}{'风向风力':<14}{'来源'}")
    print("-" * 88)
    for r in final:
        if r.get("missing"):
            print(f"{r['date']:<12}{'（缺）':<8}")
            continue
        print(f"{r['date']:<12}{r.get('week',''):<8}{r['high']:>4}℃{r['low']:>5}℃"
              f"{r.get('weather',''):<14}{r.get('wind',''):<14}{r.get('src_temp','')}")

    highs = [r["high"] for r in final if not r.get("missing")]
    lows = [r["low"] for r in final if not r.get("missing")]
    print("-" * 88)
    print(f"16 天极值：最高 {max(highs)}℃ / 最低 {min(lows)}℃ | "
          f"平均高 {sum(highs)/len(highs):.1f}℃ 平均低 {sum(lows)/len(lows):.1f}℃")

    # 导出 xlsx
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "郑州11月1-16日天气"
    head = ["日期", "星期", "最高温(℃)", "最低温(℃)", "温差(℃)", "天气", "风向风力",
            "温度来源", "天气来源", "对照:高(℃)", "对照:低(℃)", "对照:降水(mm)",
            "对照:风速(km/h)", "高差", "低差"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
        c.alignment = Alignment(horizontal="center")

    for r in final:
        if r.get("missing"):
            ws.append([r["date"], "", "", "", "", "（数据缺失）"])
            continue
        ws.append([r["date"], r.get("week", ""), r["high"], r["low"],
                   r["high"] - r["low"], r.get("weather", ""), r.get("wind", ""),
                   r.get("src_temp", ""), r.get("src_wx", ""),
                   r.get("om_high"), r.get("om_low"), r.get("om_rain"),
                   r.get("om_wind"), r.get("diff_high"), r.get("diff_low")])

    widths = [12, 10, 11, 11, 9, 16, 14, 18, 22, 11, 11, 13, 15, 8, 8]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    note = wb.create_sheet("数据来源")
    note.append(["来源", "覆盖日期", "用途", "说明"])
    for c in note[1]:
        c.font = Font(bold=True)
    note.append(["历史天气网 lishi.tianqi.com", "11-01 ~ 11-10", "主数据",
                 "站点历史页 ul.thrui 表格，含最高/最低/天气/风向风力"])
    note.append(["中国天气网 d1.weather.com.cn", "11-11 ~ 11-16", "主数据",
                 "calendar_new 日历接口（郑州 101180101），11-11~15 为观测实况，11-16 为当日预报"])
    note.append(["Open-Meteo archive (ERA5)", "11-01 ~ 11-16", "对照列",
                 "欧洲模式重分析网格数据（34.76N/113.58E），与气象站观测存在系统性偏差，仅作交叉校验"])
    note.append(["", "", "", "抓取时间：2026-11-16 23:3x；请求数 3（天气网 1 + 中国天气网 1 + Open-Meteo 1）"])
    for i, w in enumerate([34, 16, 10, 70], start=1):
        note.column_dimensions[chr(64 + i)].width = w

    out = OUT_DIR / "郑州天气_2026-11-01至11-16.xlsx"
    wb.save(out)
    print(f"\n已导出：{out}")
    return out


if __name__ == "__main__":
    main()