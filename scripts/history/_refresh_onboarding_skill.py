# -*- coding: utf-8 -*-
"""把 crawler-site-onboarding 技能从 v12 时代更新到 v14.7 现状。

只改事实性数字 + 补 v14 才有的五类能力；不改流程与纪律。
"""
from pathlib import Path

P = Path(r"C:\Users\HUAWEI\.agents\skills\crawler-site-onboarding\SKILL.md")
t = P.read_text(encoding="utf-8")
orig = t
n = 0


def rep(old, new, must=True):
    global t, n
    if old and old in t:
        t = t.replace(old, new, 1)
        n += 1
        return True
    if must:
        print("  !! 未匹配：", old[:60].replace("\n", " "))
    return False


# 1) 顶部基线口径
rep("""> 现行基线 **`crawlers\\_baseline_v12`（v12.3）**：**64 条受管 / 202 项测试**；站点模块 **20 个**（业务 7 + 假站 13），`sites/_common.py` 与 `gate.py` 是公共库不计入。
> v12 起有**请求闸门**（12 次/分 · 单任务 200 请求 · 30 分钟），忘配 `delay` 也不会超速；详见第 10 节。""",
    """> 现行基线 **`crawlers\\_baseline_v14_7`**：**73 条受管 / 308 项测试**（六套件）；站点模块 **24 个**（业务 10 + 假站 14），`sites/_common.py` 与 `gate.py` 是公共库不计入。
> 请求闸门（12 次/分 · 单任务 200 请求 · 30 分钟）v12 起就有，忘配 `delay` 也不会超速；详见第 10 节。
> 基线链：v12(64) → v13_1(37) → v14(38) → v14_1(40) → v14_2(44) → v14_3(66) → v14_3_1(68) → **v14_7(73)**。""")

# 2) 六套件口径
rep("138 项（现 202）测试里绝大多数跑 mock，**测不到真实站点的解析器**。所以动 `parse_list` 或正则之前：",
    "308 项测试（六套件：test_crawler 208 / test_discover 23 / test_identify 21 / test_transport 21 / test_rule0 17 / test_render_batch 18）里绝大多数跑 mock，**测不到真实站点的解析器**。所以动 `parse_list` 或正则之前：")

# 3) 门禁命令
rep("& $py tests\\test_crawler.py *> logs\\_crawler_tests_latest.txt   # 期望 202/202",
    """& $py tests\\test_crawler.py *> logs\\_crawler_tests_latest.txt   # 期望 208/208
# 只跑这一套属于漏检：另外五套也要跑（合起来 308 项）
& $py tests\\test_discover.py; & $py tests\\test_identify.py; & $py tests\\test_transport.py
& $py tests\\test_rule0.py;    & $py tests\\test_render_batch.py""")

# 4) 活跃基线与冻结步骤
rep("当前活跃基线 **`crawlers\\_baseline_v12`（v12.3）**：**64 条受管 / 202 项测试**；v1~v12 全部保留，绝不覆盖（v11 已被误覆盖，见 `_DAMAGED.txt`，别拿它当基准）。",
    "当前活跃基线 **`crawlers\\_baseline_v14_7`**：**73 条受管 / 308 项测试**；v1~v14_7 全部保留，绝不覆盖（v11 曾被误覆盖，见 `_DAMAGED.txt`）。")
rep("冻结三步：**切默认 BASE → 重跑 make_baseline_v12.py → baseline_snapshot.py → verify/compare/guard**（少一步就漂）。",
    "冻结四步：**切默认 BASE（verify_baseline.py + baseline_snapshot.py 两处）→ 重跑 make_baseline_vN.py → baseline_snapshot.py → verify/compare/guard**（少一步就漂；漏第 2 步会报 3 个脚本漂移）。")

# 5) 用例编号
rep("| 202 | 第 2 段附件失败 → `partial / attachment_partial` |",
    "| 202 | 第 2 段附件失败 → `partial / attachment_partial`（test_crawler 现 208 项，202 只是其中一条） |")

# 6) 追加 v14 能力节（放在"9. 排查清单"前面）
anchor = "## 9. 排查清单"
extra = """## 8.5 v14 才有的五件事（v12 时代的文档里没有）

```python
# ① 传输层三档（v14 阶段 1）：站点 CONFIG 加一行即可，其余逻辑全不动
"transport": "plain" | "cffi"        # plain=requests（默认）；cffi=curl_cffi impersonate（TLS 对齐 Chrome）
# 实测：foodmate 200/200、wzrc_all 46/46、foodlaw 20/20 逐条一致；附件 sha256 全同

# ② Rule 0（v14 阶段 2 前置）：每个站点必须标条款三态，忘标会被测试抓住
"terms_status": "allowed" | "blocked" | "unknown"
# unknown = 不抓 + 决策块 + rc=2 + 0 请求；blocked = 直接拒；allowed 才往下走

# ③ 渲染通道（v14 阶段 2）：tools/render_batch.py，一次启动 N 次导航
# 子资源默认拦 image/font/media，计数 subresources_blocked；导航计入闸门、子资源不计
# page_self_destructed = 站点自查调试器后自毁（jrzp 就是），属"站点拒绝"不是我们的 bug

# ④ 软封检测（v11 起）：CONFIG["soft_block"] = {enabled, canary_url, cooldown_sec, group}
# 同 group 共用冷却文件；load_cooldown 解析失败 → fail-closed 2 小时

# ⑤ 指纹排除（v14.5）：CONFIG["hash_exclude"] = ["published"]
# 只排除**该站**的易变字段，不要往全局 HASH_VOLATILE 里加（会把所有站都排掉）
```

**两种"看着像 SSR 其实不是"的站，接之前先分清**：

| 现象 | 真相 | 做法 |
|---|---|---|
| 列表页 70~80 KB，但 0 个详情链接 | 空壳 + JS 拉明文 JSON | 从页面 JS 里抠接口；`response="json"` 或 `response="html"` 自己 `json.loads` |
| 列表页 6 KB、正文 <300 字 | 纯 SPA 空壳 | 先找 XHR；找不到就按 Rule 0 停 |

**实测案例（2026-11-15，jlrc）**：岗位名**不在任何字段里**，藏在图片 URL 的文件名（`fileName=行业_大类,中类,岗位名+32位hash.png`）。这种就只能 `response="html"` + 自己在 `parse_list` 里剥——引擎 `field_map` 没有 transform 钩子。

**读 jsonl 的硬规矩（2026-11-15 踩过）**：

```
json.dumps(ensure_ascii=False) 不转义 U+2028/U+2029，
而 Python str.splitlines() 把它们当换行 → 4,683 行的文件被读成 4,695 行、"14 行坏行"。
数据其实完好。读 jsonl 一律 read_text().split("\\n")；引擎和 clean.py 用 for line in f: 所以安全。
```

---

"""
if anchor in t and "v14 才有的五件事" not in t:
    t = t.replace(anchor, extra + anchor, 1)
    n += 1
else:
    print("  !! 未找到插入锚点或已存在")

P.write_text(t, encoding="utf-8")
print("改动 %d 处，%d → %d 字符" % (n, len(orig), len(t)))