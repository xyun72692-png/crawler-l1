# -*- coding: utf-8 -*-
"""确认 mock 的 /v5/pN 每页条数（A5 阈值 15 = 3 页 × 5 条）"""
import subprocess
import urllib.request

PY = r"D:\agent-work\venv\Scripts\python.exe"
MOCK = r"D:\agent-work\tests\mock_site.py"

p = subprocess.Popen([PY, MOCK, "--port", "0", "--robots", "none"],
                     stdout=subprocess.PIPE, text=True, encoding="utf-8")
line = p.stdout.readline()
port = int(line.strip().split("=")[1])
try:
    for path in ("/v5/p1.html", "/v5/p2.html", "/v5/p3.html", "/v5/p4.html"):
        html = urllib.request.urlopen(
            "http://127.0.0.1:%d%s" % (port, path), timeout=3).read().decode("utf-8")
        print(path, "->", html.count('class="item"'), "条")
finally:
    p.terminate()
    p.wait(timeout=5)