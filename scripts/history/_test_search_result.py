# -*- coding: utf-8 -*-
"""验证 --search-result 的嵌套解析与 0 条报错。"""
import json
import subprocess
from pathlib import Path

AGENT = Path(r"D:\agent-work")
PY = str(AGENT / "venv" / "Scripts" / "python.exe")
FIX = AGENT / "logs"
FIX.mkdir(exist_ok=True)

nested = {
    "code": 0,
    "data": {
        "results": [
            {"title": "官方站A", "url": "https://a.example.com/index"},
            {"title": "官方站B", "link": "https://b.example.com/list"},
            {"deep": {"items": [{"href": "https://c.example.com/jobs"}]}},
        ]
    },
}
p1 = FIX / "_search_nested.json"
p1.write_text(json.dumps(nested, ensure_ascii=False), encoding="utf-8")

empty = {"code": 0, "data": {"total": 0, "records": []}}
p2 = FIX / "_search_empty.json"
p2.write_text(json.dumps(empty, ensure_ascii=False), encoding="utf-8")

for name, path in (("嵌套结构", p1), ("解析出 0 条", p2)):
    r = subprocess.run(
        [PY, "tools/discover.py", "--region", "浙江", "--mode", "wide",
         "--goal", "jobs", "--search-result", str(path), "--skip-syntax",
         "--limit", "20", "--out", str(FIX / "_t_search_out.csv")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(AGENT))
    out = (r.stdout or "") + (r.stderr or "")
    print("=" * 60)
    print("案例：%s   rc=%d" % (name, r.returncode))
    for line in out.splitlines():
        if "检索" in line or "!!" in line or "候选" in line:
            print("   ", line.strip()[:100])