# -*- coding: utf-8 -*-
"""修两处补丁错误：① 18.4.3 旧表格重复 ② 反例把 zjrc.com 误写成 zjhr.com。"""
from pathlib import Path

DESK = Path(r"C:\Users\HUAWEI\Desktop")
DOCS = Path(r"D:\agent-work\docs")

OLD_1843 = """#### 18.4.3 其余四路的细节

| 路径 | 成本 | 做法 | 适用 |
|---|---|---|---|
| **① 页脚/友链** | 0~2 请求 | 抓一个已知站首页，按出现次数排外链域名 | 同类站互挂友链的领域 |
| **② 域名语法 + DNS** | **0 HTTP** | 按命名规律生成候选（`{city}rc.com` / `wz{abbr}rc.com`），批量解析 | 站群型平台 |
| **③ 平台指纹** | 0~1 请求/站 | 第三方资源域名、robots MD5、favicon 字节 | 判断"是不是同一家" |
| **④ 明文接口** | 1~2 请求 | 从页面 `script` 的 `url` + `queryData`、或 XHR 日志里找接口 | 列表是 JS 渲染的站 |

**顺序已改（2026-11-15）**：⓪ 检索 → ① 官方名录 → ②③（免费）→ ④⑤（便宜/贵）。原「顺序不能反」作废，原因见上方 18.4。"""

NEW_1843 = """**注（2026-11-15）**：旧版把页脚/域名/指纹/接口编成 ①~④，现在重新编号为 ②~⑤，
⓪ 检索 与 ① 官方名录 插到最前。路径本身没变，变的是**顺序和优先级**。"""

BAD_CASE = """  zjhr.com   浙江省公共就业服务平台  —— 被枚举出来了，但 "zj" 被判成「镇江」，落 B 档扔掉
  zjhr.com   还漏了另一层原因：5 种后缀模板全带城市名，没有 {省}hr 这一档，**它根本生成不出来**
  js365job.com 江苏"就在江苏"智慧就业服务平台 —— 244 个候选里压根没有"""

GOOD_CASE = """  zjrc.com    浙江人力资源大市场 —— 被枚举出来了，但 "zj" 被判成「镇江」，判 B 档扔掉
  zjhr.com    浙江省公共就业服务平台 —— 5 种后缀模板全带城市名，没有 {省}hr 这一档，它根本生成不出来
  js365job.com 江苏"就在江苏"智慧就业服务平台 —— 244 个候选里压根没有"""


def fix(p: Path):
    t = p.read_text(encoding="utf-8")
    n = 0
    if OLD_1843 in t:
        t = t.replace(OLD_1843, NEW_1843, 1)
        n += 1
    if BAD_CASE in t:
        t = t.replace(BAD_CASE, GOOD_CASE, 1)
        n += 1
    if n:
        p.write_text(t, encoding="utf-8")
    print("%-70s 修 %d 处  %d 字符" % (p.name, n, len(t)))


for folder in (DESK, DOCS):
    for p in folder.iterdir():
        if p.suffix == ".md" and "完整版" in p.name:
            fix(p)