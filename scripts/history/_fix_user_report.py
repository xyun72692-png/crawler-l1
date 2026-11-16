# -*- coding: utf-8 -*-
"""清理人话版 18.3 的旧表格残留（补丁只换了标题，旧表还在）。"""
from pathlib import Path

DESK = Path(r"C:\Users\HUAWEI\Desktop")
DOCS = Path(r"D:\agent-work\docs")

STALE = """| 路 | 花多少 | 怎么做 |
|---|---|---|
| ① 翻页脚/友链 | 1~2 个请求 | 同类站爱互相挂链接，**友链就是现成的同类站清单** |
| ② 猜域名 | **0 个请求** | 按命名规律批量试（如"城市拼音 + rc.com"），只看域名解不解析得出来 |
| ③ 比"指纹" | 每站 1 个请求 | 看图标文件、robots 文件是不是一模一样 → 是，就是同一家做的 |
| ④ 找接口 | 1~2 个请求 | 很多站的列表其实是"调接口"拼出来的，**接口地址就写在网页源码里** |

打个比方：④ 就像发现门后面有条传送带——不用一箱一箱搬，直接接上就行。

**新顺序**：先做 ⓪①（几乎不花钱、命中率最高），再走 ②③（免费但要碰运气），最后才考虑 ④ ⑤ 或者用浏览器渲染（最贵）。"""

NEW = """**一句话记法**：先搜（⓪）→ 再查名录（①）→ 顺着友链猜（②③）→ 最后才是指纹和接口（④⑤）。"""


def fix(p: Path):
    t = p.read_text(encoding="utf-8")
    if STALE not in t:
        print("   ！未找到残留段，跳过", p.name)
        return
    t = t.replace(STALE, NEW, 1)
    p.write_text(t, encoding="utf-8")
    print("   已清理:", p.name, len(t), "字符")


for folder in (DESK, DOCS):
    for p in folder.iterdir():
        if p.suffix == ".md" and "给你的版本" in p.name:
            fix(p)