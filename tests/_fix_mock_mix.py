# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""状态断言用夹具：给 mock 加 /mix 路由（p1 正常、p2 及以后一律 500）。"""
from pathlib import Path

M = Path(str(_HOME / "tests" / "mock_site.py"))
s = M.read_text(encoding="utf-8")

if "/mix/p" in s:
    print("已存在 /mix 路由，跳过")
    raise SystemExit(0)

anchor = '        # ---- 提案5：页大小探测用（size= 控制卡片数；MOCK_PS_BROKEN=1 时第 2 页与第 1 页重复）----'
assert anchor in s, "锚点缺失"

route = '''        # ---- 状态断言用：p1 正常，p2 及以后一律 500（造"部分失败/全失败"）----
        if path.startswith("/mix/p") and path.endswith(".html"):
            try:
                n = int(path[len("/mix/p"):-len(".html")])
            except ValueError:
                self._send(404, b"bad page")
                return
            k = bump(path)
            sys.stderr.write("[mock] mix p%d hit %d\\n" % (n, k))
            if n <= 1:
                self._send(200, build_page(n).encode("utf-8"))
            else:
                self._send(500, b"server error")
            return

'''
s = s.replace(anchor, route + anchor, 1)
M.write_text(s, encoding="utf-8", newline="\n")
print("mock_site.py 已加 /mix 路由")