# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""报告第 5 行与第 847 行：引擎行数/模块数/假站数 改为当前值（3647 / 20 / 13）。"""
import hashlib
import shutil
from pathlib import Path

SRC = Path(str(_HOME / "docs" / "爬虫能力报告-完整版-20261111.md"))
DST = Path(r"C:\Users\HUAWEI\Desktop\爬虫能力报告-完整版-20261111.md")

s = SRC.read_text(encoding="utf-8")
before = s

old5 = ("**当前规模**：引擎 **3642 行**，站点模块 **18 个**"
        "（业务站 7 个，其中 quotes 是练习站不算真实站；测试用假站 11 个），"
        "自动测试 **138 项**连续两轮全过")
new5 = ("**当前规模**：引擎 **3647 行**，站点模块 **20 个**"
        "（业务站 7 个，其中 quotes 是练习站不算真实站；测试用假站 13 个），"
        "自动测试 **138 项**连续两轮全过")
assert old5 in s, "第 5 行未命中"
s = s.replace(old5, new5, 1)

old847 = ("| A1 规模数字 | 引擎 3544 行 / 18 模块 / 126 项（当时值，现 130） | "
          "模块数它说对了（18 = 业务 7 + 假站 11，我原来漏数 3 个）；"
          "行数它核对时 3544，**现为 3642**；测试 126 ✓ | ✅ 已改（用当前值） |")
new847 = ("| A1 规模数字 | 引擎 3544 行 / 18 模块 / 126 项（codex 核对时的值） | "
          "模块数当时它说对了（18 = 业务 7 + 假站 11，我原来漏数 3 个）；"
          "**当前值为 3647 行 / 20 模块（假站 13 个）/ 138 项测试**"
          "（2026-11-11 补 8 条状态断言后 +2 个假站、+8 条用例）| ✅ 已改（用当前值） |")
assert old847 in s, "第 847 行未命中"
s = s.replace(old847, new847, 1)

if s == before:
    print("!! 未命中")
else:
    SRC.write_text(s, encoding="utf-8", newline="\n")
    shutil.copyfile(SRC, DST)
    d = SRC.read_bytes()
    print("报告已更新: %d 行 / %d 字节 / MD5 %s"
          % (len(s.splitlines()), len(d), hashlib.md5(d).hexdigest()))
    for i, line in enumerate(s.splitlines(), 1):
        if i in (5, 847):
            print("L%d: %s" % (i, line[:120]))