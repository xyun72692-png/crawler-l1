# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""验证 clean.py 的三种导出格式内容一致。"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd

OUT = str(_HOME / "out")


def latest(pat):
    files = sorted(glob.glob(os.path.join(OUT, pat)))
    return files[-1] if files else None


p_x = latest("quotes_clean_*.xlsx")
p_c = latest("quotes_clean_*.csv")
p_j = latest("quotes_clean_*.json")

print("xlsx:", os.path.basename(p_x))
print("csv :", os.path.basename(p_c))
print("json:", os.path.basename(p_j))
print("")

dx = pd.read_excel(p_x, engine="openpyxl")
dc = pd.read_csv(p_c, encoding="utf-8-sig")
with open(p_j, encoding="utf-8") as f:
    dj = json.load(f)

print("xlsx shape :", dx.shape)
print("csv  shape :", dc.shape)
print("json count :", len(dj), "条, 首条键数 =", len(dj[0]))
print("三者行数一致:", dx.shape[0] == dc.shape[0] == len(dj))
print("三者列名一致:", list(dx.columns) == list(dc.columns) == list(dj[0].keys()))
print("")

# CSV 是否有 BOM
with open(p_c, "rb") as f:
    head3 = f.read(3)
print("csv 带 UTF-8 BOM:", head3 == b"\xef\xbb\xbf")
print("csv 中文列头   :", ", ".join(list(dc.columns)[:4]))
print("json 中文原样  :", dj[0]["author"], "|", dj[0]["title"][:36])
print("csv 中文原样   :", dc.iloc[0]["author"], "|", str(dc.iloc[0]["title"])[:36])