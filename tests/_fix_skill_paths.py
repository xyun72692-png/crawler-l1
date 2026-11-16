# -*- coding: utf-8 -*-
"""修 image-generation 技能里的失效路径（桌面 junction 已不存在）。"""
from pathlib import Path

p = Path(r"C:\Users\HUAWEI\.agents\skills\image-generation\SKILL.md")
s = p.read_text(encoding="utf-8")
before = s
OLD_ROOT = "C:" + chr(92) + "Users" + chr(92) + "HUAWEI" + chr(92) + "Desktop" + chr(92) + "sd-local"
NEW_ROOT = "D:" + chr(92) + "sd-local" + chr(92) + "sd-local"
s = s.replace(OLD_ROOT, NEW_ROOT)
if "路径变更" not in s:
    head = "# 图片生成（本机 ComfyUI，已部署）"
    note = (head + chr(10) + chr(10)
            + "> **路径变更（2026-11-11 核实）**：桌面 `C:" + chr(92) + "Users" + chr(92)
            + "HUAWEI" + chr(92) + "Desktop" + chr(92) + "sd-local` 的 junction **已不存在**。"
            + chr(10)
            + "> 真实位置是 `D:" + chr(92) + "sd-local" + chr(92) + "sd-local`"
            + "（pic.ps1 / genimg.py / gallery 都在这里）。" + chr(10)
            + "> 桌面现在只剩 `.minecraft` 一个 junction。")
    s = s.replace(head, note, 1)
p.write_text(s, encoding="utf-8", newline="\n")
print("image skill changed:", before != s)
print("残留 Desktop 引用:", s.count("Desktop" + chr(92) + "sd-local"))

c = Path(r"C:\Users\HUAWEI\.agents\skills\crawler-site-onboarding\SKILL.md")
t = c.read_text(encoding="utf-8")
old = "- **不许并发**：单线程 + 1~2.5 秒间隔，别把人家站打挂"
new = ("- **不许并发**：单线程；间隔按站点定 —— 普通站 0.8~1.5 秒，"
       "被限流过的站（如 wzrc）3~5 秒 + retries 1；别把人家站打挂")
if old in t:
    t = t.replace(old, new, 1)
    c.write_text(t, encoding="utf-8", newline="\n")
    print("crawler skill interval updated")
else:
    print("crawler skill: 锚点未命中，跳过")