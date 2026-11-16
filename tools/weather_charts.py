# -*- coding: utf-8 -*-
"""
郑州 2026-11-01 ~ 11-16 每日温度曲线（16 张 + 1 张总览）

主曲线 = 当日官方最高/最低 + 日出日落 推出的 sine² 标准日温模型
    · 最低温在日出前 30 分钟、最高温取 14:00、两段 sin² 插值
    · 输入只有「该日极值 + 日出时间」，不含任何第三方天气数值

数据源（读 tools/weather_zhengzhou.py 产出的 _zz_weather_rows.json）
    · 11-09 ~ 11-16  中央气象台 tempchart（A 型一手权威）
    · 11-01 ~ 11-08  历史天气网（第三方回退，官方接口不覆盖）
    · 曲线颜色区分：官方段红色，第三方段橙色
日出日落：Open-Meteo daily=sunrise,sunset（天文量）

用法：
    python tools\\weather_charts.py
"""
import json
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = ROOT / "data" / "raw" / "_probe_weather"
OUT = ROOT / "out" / "郑州天气图"
ROWS = ROOT / "out" / "_zz_weather_rows.json"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

T_MAX_HOUR = 14.0
T_MIN_LEAD = 0.5


def day_model(off_lo, off_hi, sunrise_h):
    t_min = (sunrise_h - T_MIN_LEAD) % 24
    span_up = (T_MAX_HOUR - t_min) % 24
    span_down = 24 - span_up
    curve = []
    for h in range(24):
        d = (h - t_min) % 24
        r = (np.sin(0.5 * np.pi * d / span_up) ** 2 if d <= span_up
             else np.cos(0.5 * np.pi * (d - span_up) / span_down) ** 2)
        curve.append(off_lo + (off_hi - off_lo) * r)
    return curve


def load_hourly():
    d = json.loads((PROBE / "openmeteo_hourly.json").read_text("utf-8"))
    h = d["hourly"]
    by_day = {}
    for t, v in zip(h["time"], h["temperature_2m"]):
        day, hh = t.split("T")
        by_day.setdefault(day, {})[int(hh[:2])] = v
    return by_day


def load_sun():
    d = json.loads((PROBE / "sun.json").read_text("utf-8"))["daily"]
    out = {}
    for t, sr in zip(d["time"], d["sunrise"]):
        hh, mm = sr.split("T")[1].split(":")[:2]
        out[t] = int(hh) + int(mm) / 60
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [r for r in json.loads(ROWS.read_text("utf-8")) if not r.get("missing")]
    om = load_hourly()
    sun = load_sun()
    made = []

    for r in rows:
        day = r["date"]
        off_hi, off_lo = float(r["high"]), float(r["low"])
        model = day_model(off_lo, off_hi, sun.get(day, 6.9))
        raw = [om.get(day, {}).get(h) for h in range(24)]
        main_color = "#d93b3b" if r.get("official") else "#e08327"
        tag = "" if r.get("official") else "（第三方源）"

        fig, ax = plt.subplots(figsize=(9.2, 4.7), dpi=130)
        if all(v is not None for v in raw):
            ax.plot(range(24), raw, color="#b9b9b9", lw=1.2, ls="--",
                    label="模式原始曲线（Open-Meteo，仅对照）")
        ax.plot(range(24), model, color=main_color, lw=2.5,
                label=f"标准日温模型（{r['src_temp']}极值 + 日出日落）")
        ax.fill_between(range(24), model, off_lo - 2, color=main_color, alpha=0.10)
        ax.axhline(off_hi, color="#e07b39", lw=1.3, ls=":", label=f"最高 {off_hi:g}℃")
        ax.axhline(off_lo, color="#3b7fd9", lw=1.3, ls=":", label=f"最低 {off_lo:g}℃")

        imax, imin = int(np.argmax(model)), int(np.argmin(model))
        ax.scatter([imax], [model[imax]], color="#e07b39", s=46, zorder=5)
        ax.scatter([imin], [model[imin]], color="#3b7fd9", s=46, zorder=5)
        ax.annotate(f"{model[imax]:.1f}℃ {imax}时", (imax, model[imax]),
                    textcoords="offset points", xytext=(0, 11), ha="center",
                    fontsize=9, color="#b3521f", fontweight="bold")
        ax.annotate(f"{model[imin]:.1f}℃ {imin}时", (imin, model[imin]),
                    textcoords="offset points", xytext=(0, -25), ha="center",
                    fontsize=9, color="#2b5da8", fontweight="bold")
        sr = sun.get(day, 6.9)
        ax.axvline(sr, color="#ffb733", lw=1.0, alpha=0.7)
        ax.text(sr, off_hi + (off_hi - off_lo) * 0.28,
                f"日出 {int(sr)}:{int(sr % 1 * 60):02d}", fontsize=7.5, color="#a87900")

        ax.set_xticks(range(0, 24, 2))
        ax.set_xlim(0, 23)
        pad = max(1.8, (off_hi - off_lo) * 0.35)
        ax.set_ylim(off_lo - pad, off_hi + pad)
        ax.set_xlabel("小时")
        ax.set_ylabel("气温 (℃)")
        ax.grid(alpha=0.25, ls=":")
        ax.set_title(f"郑州 {day}（{r['week']}）  {off_hi:g}℃ / {off_lo:g}℃  ·  "
                     f"{r['weather']}  ·  {r.get('wind') or '—'}{tag}",
                     fontsize=12, fontweight="bold")
        ax.legend(fontsize=7.6, loc="lower right", framealpha=0.92)
        fig.text(0.01, 0.008,
                 f"温度来源：{r['src_temp']}｜曲线＝当日极值＋日出日落推出的 sine² 标准日温模型"
                 "（最高温 14 时、最低温日出前 30 分钟）",
                 fontsize=6.6, color="#666666")
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        f = OUT / f"{day}_郑州温度曲线.png"
        fig.savefig(f)
        plt.close(fig)
        made.append(f)

    # 总览
    fig, axes = plt.subplots(4, 4, figsize=(17, 11), dpi=120)
    for ax, r in zip(axes.flat, rows):
        day = r["date"]
        off_hi, off_lo = float(r["high"]), float(r["low"])
        model = day_model(off_lo, off_hi, sun.get(day, 6.9))
        c = "#d93b3b" if r.get("official") else "#e08327"
        ax.plot(range(24), model, color=c, lw=1.9)
        ax.fill_between(range(24), model, off_lo - 1.5, color=c, alpha=0.10)
        ax.axhline(off_hi, color="#e07b39", lw=1, ls=":")
        ax.axhline(off_lo, color="#3b7fd9", lw=1, ls=":")
        star = "" if r.get("official") else "·"
        ax.set_title(f"{day[5:]} {r['week']}  {off_hi:g}/{off_lo:g}℃  {r['weather']}{star}",
                     fontsize=9)
        ax.set_xticks([0, 6, 12, 18])
        ax.set_ylim(off_lo - 3, off_hi + 3)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.2, ls=":")
    fig.suptitle("郑州 2026-11-01 ~ 11-16 每日温度曲线"
                 "（红＝中央气象台官方；橙＝历史天气网第三方回退）",
                 fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    overview = OUT / "00_总览_16天温度曲线.png"
    fig.savefig(overview)
    plt.close(fig)

    print(f"生成 {len(made)} 张单日图 + 1 张总览 → {OUT}")


if __name__ == "__main__":
    main()