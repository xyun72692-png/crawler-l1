# -*- coding: utf-8 -*-
"""独立导出：中央气象台官方 7 天预报（11-16 ~ 11-22，页面同款数据）"""
import json
import pathlib

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

PROBE = pathlib.Path(r"D:\agent-work\data\raw\_probe_weather")
OUT = pathlib.Path(r"D:\agent-work\out")
WEEK = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}

d = json.loads((PROBE / "nmc_weather_zz.json").read_text("utf-8"))["data"]
real = d["real"]
pred = d["predict"]
tc = {x["time"].replace("/", "-"): x for x in d["tempchart"]}

print("实况发布时间:", real["publish_time"])
w = real["weather"]
print(f"当前实况: {w['temperature']}℃ / {w['info']} / 湿度{w['humidity']}% / 降水{w['rain']}mm / "
      f"{real['wind']['direct']}{real['wind']['power']} / 体感{w['feelst']}℃")
print("预报发布时间:", pred["publish_time"])
print()

rows = []
for x in pred["detail"]:
    day = x["date"]
    dw = (x.get("day") or {}).get("weather") or {}
    nw = (x.get("night") or {}).get("weather") or {}
    wd = (x.get("day") or {}).get("wind") or {}
    wn = (x.get("night") or {}).get("wind") or {}

    def g(v):
        return "" if str(v) in ("9999", "99999999", "None", "") else v

    t = tc.get(day, {})
    rows.append({
        "date": day,
        "day_wx": g(dw.get("info")),
        "day_t": g(dw.get("temperature")),
        "day_wind": f"{g(wd.get('direct'))}{g(wd.get('power'))}".strip(),
        "night_wx": g(nw.get("info")),
        "night_t": g(nw.get("temperature")),
        "night_wind": f"{g(wn.get('direct'))}{g(wn.get('power'))}".strip(),
        "hi": t.get("max_temp"),
        "lo": t.get("min_temp"),
        "rain": x.get("precipitation"),
    })

print(f"{'日期':<12}{'白天':<8}{'夜间':<8}{'最高':>6}{'最低':>6}{'降水':>6}  风")
print("-" * 80)
for r in rows:
    print(f"{r['date']:<12}{r['day_wx'] or '—':<8}{r['night_wx'] or '—':<8}"
          f"{r['hi'] if r['hi'] is not None else '—':>6}{r['lo'] if r['lo'] is not None else '—':>6}"
          f"{r['rain'] if r['rain'] is not None else '—':>6}  {r['day_wind']}")

# 导出
wb = Workbook()
ws = wb.active
ws.title = "官方7天预报"
ws.append(["日期", "白天天气", "白天风", "夜间天气", "夜间风",
           "最高温(℃)", "最低温(℃)", "降水量(mm)"])
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="1F7A4D")
    c.alignment = Alignment(horizontal="center")
for r in rows:
    ws.append([r["date"], r["day_wx"] or "（页面未显示）", r["day_wind"],
               r["night_wx"] or "（页面未显示）", r["night_wind"],
               r["hi"], r["lo"], r["rain"]])
for i, _w in enumerate([13, 14, 16, 14, 16, 12, 12, 13], start=1):
    ws.column_dimensions[chr(64 + i)].width = _w
ws.freeze_panes = "A2"

note = wb.create_sheet("实况与来源")
pairs = [
    ["项目", "内容"],
    ["来源", "中央气象台 www.nmc.cn/rest/weather?stationid=YVItN（郑州）"],
    ["页面", "https://www.nmc.cn/publish/forecast/AHA/zhengzhou.html"],
    ["预报发布", pred["publish_time"]],
    ["实况发布", real["publish_time"]],
    ["当前实况", f"{w['temperature']}℃ / {w['info']} / 湿度 {w['humidity']}% / "
                f"降水 {w['rain']}mm / {real['wind']['direct']}{real['wind']['power']} / "
                f"体感 {w['feelst']}℃"],
    ["日出日落", f"{real['sunriseSunset']['sunrise']} / {real['sunriseSunset']['sunset']}"],
    ["覆盖范围", "11-16 ~ 11-22（页面显示的 7 天：今天 + 未来 6 天）"],
    ["历史边界", "tempchart 另含 11-09~11-15 的温度，但历史日的天气现象字段 day_text/night_text 为 9999（缺）"],
    ["说明", "11-16 白天天气官方页面未显示（当天已过），只有夜间「小雨」；其余日期白天/夜间都有"],
]
for p in pairs:
    note.append(p)
for c in note[1]:
    c.font = Font(bold=True)
note.column_dimensions["A"].width = 16
note.column_dimensions["B"].width = 96

f = OUT / "郑州天气预报_NMC官方_11-16至11-22.xlsx"
wb.save(f)
print(f"\n已导出：{f}")
