#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 sites/registry.json：JSON 结构 / 字段齐全 / status 取值 / site_module 文件真实存在。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "sites" / "registry.json"
BASE = ROOT / "crawlers"          # site_module 的基准目录
FIELDS = "name url region kind level robots scale status site_module last_run note".split()
STATUSES = {"已接入", "待接入", "blocked", "不相关"}

try:
    data = json.loads(REG.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"[FAIL] JSON 解析失败: {exc}")
    sys.exit(1)
if not isinstance(data, list):
    print(f"[FAIL] 顶层不是数组，而是 {type(data).__name__}")
    sys.exit(1)

errors = []
for i, row in enumerate(data, 1):
    if not isinstance(row, dict):
        errors.append(f"#{i} 不是对象")
        continue
    errors += [f"#{i} {row.get('name', '?')} 缺字段: {f}" for f in FIELDS if f not in row]
    if row.get("status") not in STATUSES:
        errors.append(f"#{i} {row.get('name', '?')} status 非法: {row.get('status')!r}")
    mod = row.get("site_module")
    if mod and not (BASE / mod).exists():
        errors.append(f"#{i} {row.get('name', '?')} site_module 文件不存在: {mod}")

counts = Counter(row.get("status") for row in data if isinstance(row, dict))
print("status 计数: " + " / ".join(f"{k} {counts[k]}" for k in sorted(counts, key=str)))
print(f"合计 {len(data)} 条")
if errors:
    print(f"[FAIL] {len(errors)} 处问题:")
    for err in errors:
        print("  -", err)
    sys.exit(1)
print("[OK] 全部校验通过")
sys.exit(0)