# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""更新能力报告：126 → 130、新增"第九道防线：筛选条件指纹"、同步桌面副本。"""
import hashlib
import shutil
from pathlib import Path

SRC = Path(str(_HOME / "docs" / "爬虫能力报告-完整版-20261111.md"))
DST = Path(r"C:\Users\HUAWEI\Desktop\爬虫能力报告-完整版-20261111.md")

s = SRC.read_text(encoding="utf-8")
before = s

# 1) 测试数 126 → 130（只改"当前值"语义的行）
s = s.replace("自动测试 **126 项**连续两轮全过", "自动测试 **130 项**连续两轮全过")
s = s.replace("# 126 项", "# 130 项")
s = s.replace("| **126 项自动测试** | 连续跑两轮 | ✅ 全过 |", "| **130 项自动测试** | 连续跑两轮 | ✅ 全过 |")
s = s.replace("126 项，任何一项红了都不许往下走。", "130 项，任何一项红了都不许往下走。")

# 2) 防线数量 8 → 9
s = s.replace("- 第 6 章：**风险防护**——8 道防线，每道防的是什么",
              "- 第 6 章：**风险防护**——9 道防线，每道防的是什么")
s = s.replace("| 站点有 IP 级频率限制 | 抓多了会被\"软封\"（回正常状态码 + 空内容） | 见第 6 章 8 道防线 |",
              "| 站点有 IP 级频率限制 | 抓多了会被\"软封\"（回正常状态码 + 空内容） | 见第 6 章 9 道防线 |")
s = s.replace("## 六、风险防护：8 道防线", "## 六、风险防护：9 道防线")

# 3) 新增第九道防线（插在 6.8 之后、第七章之前）
anchor = "---\n\n## 七、已知短板（按严重程度分级）"
assert anchor in s
new_section = '''### 6.9 第九道防线：筛选条件指纹（防"换了条件还用旧断点"）

**它防的是什么**：同一个任务名（`--job`），你换了筛选条件（比如从"近 3 天"改成"近 7 天"、
或换了区县 / 薪资档 / 行业），程序如果还用上一次的断点，就会认为"这几页已经抓过了"——
于是**一个请求都不发**，报告还会写 `success`、覆盖率 1.0。这是最难发现的一种假成功。

**怎么防的**：
- 每次运行都给当前的 URL 算一个"指纹"（URL 里的筛选参数，去掉页码部分，取 sha1 前 12 位）
- 指纹和上次不一样 → 清空页码断点（含"下一页"模式的断点）、清掉旧的总页数记录，**保留去重键**
- 报告里会留一条 `anomalies`：`筛选条件变更 xxx→yyy，已清 pages_done/urls_done/next_url/pages_declared`

**为什么要保留去重键**：去重键是"这条数据抓过没有"，跟页码无关，清掉会导致重复抓同一批数据。

**覆盖情况**：数字分页和"下一页/游标"分页都已覆盖（用例 127/128 测数字分页，129/130 测下一页模式）。

| 场景 | 该有的行为 | 用例 |
|---|---|---|
| 同一任务换筛选（数字分页） | 旧断点作废，重新抓 3 页，coverage=1.0 | 127 ✅ |
| 同一任务同筛选（数字分页） | 断点保留，第二跑全跳过（noop） | 128 ✅ |
| 同一任务换筛选（下一页模式） | `urls_done`/`next_url` 一起清，重新抓，不留旧 URL | 129 ✅ |
| 同一任务同筛选（下一页模式） | 断点保留，第二跑不新增 | 130 ✅ |

'''
s = s.replace(anchor, new_section + anchor, 1)

# 4) 修订记录补一条
tail_anchor = "| D 数字同步 | 122 → 126 | 对 | ✅ 已改（全文 4 处） |"
if tail_anchor in s:
    s = s.replace(tail_anchor,
                  tail_anchor + "\n"
                  "| E 断点筛选指纹 | —— | 新增第九道防线 | ✅ 已加（用例 127–130；测试 126 → 130） |", 1)

if s == before:
    print("!! 未命中任何替换，请检查")
else:
    SRC.write_text(s, encoding="utf-8", newline="\n")
    shutil.copyfile(SRC, DST)
    data = SRC.read_bytes()
    print("报告已更新：%d 字节 / %d 行 / MD5 %s"
          % (len(data), len(s.splitlines()), hashlib.md5(data).hexdigest()))
    print("桌面副本已同步：", DST.exists(), DST.stat().st_size)
    for i, line in enumerate(s.splitlines(), 1):
        if "126" in line:
            print("残留 126 → 第 %d 行：%s" % (i, line.strip()[:80]))