# -*- coding: utf-8 -*-
"""手动复现用例 149：造坏 registry，跑 check_registry.py，看它到底输出什么。"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

AGENT = Path(r"D:\agent-work")
PY = str(AGENT / "venv" / "Scripts" / "python.exe")
SB = AGENT / "logs" / "_c149_manual"

if SB.exists():
    shutil.rmtree(SB)
for sub in ("tools", "sites", "crawlers"):
    (SB / sub).mkdir(parents=True, exist_ok=True)
shutil.copy2(AGENT / "tools" / "check_registry.py", SB / "tools" / "check_registry.py")

FIELDS = "name url region kind level robots scale status site_module last_run note".split()


def frow(**kw):
    base = {f: None for f in FIELDS}
    base.update(kw)
    return base


bad = [
    {"name": "缺字段站", "url": "https://a.example"},
    frow(name="状态非法站", url="https://b.example", status="已接入但没真接"),
    frow(name="模块不存在站", url="https://c.example", status="已接入",
         site_module="sites/nope.py"),
]
(SB / "sites" / "registry.json").write_text(
    json.dumps(bad, ensure_ascii=False, indent=2), encoding="utf-8")

r = subprocess.run([PY, str(SB / "tools" / "check_registry.py")],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", cwd=str(SB))
print("rc =", r.returncode)
print("---- stdout ----")
print(r.stdout)
print("---- stderr ----")
print(r.stderr)
out = (r.stdout or "") + (r.stderr or "")
print("---- 关键词命中 ----")
for k in ("缺字段", "status 非法", "site_module 文件不存在"):
    print("  %-24s %s" % (k, k in out))