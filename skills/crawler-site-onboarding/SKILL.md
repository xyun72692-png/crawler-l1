---
name: crawler-site-onboarding
description: 用户要求爬某个网站/抓数据/导表格/更新某站数据时使用：在 D:\agent-work 的通用爬虫上接入新站点或跑已有站点，走完整流程（侦察 → SPA 分层判定 → 写配置 → 试跑 1 页 → 附件 → 导出 xlsx → 基线门禁）。含 robots/限速/SSRF/附件安全/去重/哈希/文件名全部既定规矩。
---

# 爬虫接站与运营（通用流程）

> 现行基线 **`crawlers\_baseline_v14_13_21`**：**81 条受管 / 330 项测试**（六套件）；站点模块 **26 个**（含 quotes 练习站与测试夹具），`sites/_common.py` 与 `gate.py` 是公共库不计入。
> 请求闸门（12 次/分 · 单任务 200 请求 · 30 分钟）v12 起就有，忘配 `delay` 也不会超速；详见第 10 节。
> 基线链：v12(64) → v13_1(37) → v14(38) → v14_1(40) → v14_2(44) → v14_3(66) → v14_3_1(68) → v14_7(73) → v14_8(74) → **v14_9(74) → v14_12(75) → v14_12_1(75) → v14_13(77) → v14_13_1(77) → v14_13_2(78) → v14_13_3(78) → v14_13_4(80) → v14_13_7(80) → v14_13_11(80) → v14_13_17(80) → v14_13_18(80) → v14_13_19(80)**。

工作区固定：`D:\agent-work`，解释器固定 `D:\agent-work\venv\Scripts\python.exe`（装包必须 `--only-binary=:all:`）。
每次开跑前都带 `$env:PYTHONIOENCODING='utf-8'`，否则中文日志在控制台会炸。

## -1. 开工前必读 + 完成的定义（2026-11-17 加：知识搬出记忆后的可发现性保证）

### 开工前必读三处（不读就动手 = 流程错误）

| 顺序 | 读什么 | 为什么 |
|---|---|---|
| ① | `crawlers/sites/<name>.py` 的 **docstring + CONFIG** | 该站的全部 HOW（选择器、参数码表、page_end、transport、dedup_key、数据质量缺陷）。**比记忆更全更新** |
| ② | `docs/知识归属.md` §5 | 引擎级踩坑与已定决策（断点失效、sitemap 该不该做、PDF 试看判据、U+2028 撕行） |
| ③ | `docs/Rule0-不碰清单.md` | 该站是否已被判为 blocked；命中就**直接拒，不是"能不能绕"** |

接新站（无模块）时跳过 ①，直接读 ②③ 再进 §1 侦察。

### 完成的定义（7 项，缺一项都不算做完）

跑出数据 ≠ 完成。以下全绿才算：

1. **代码**：`crawlers/sites/<name>.py`，`terms_status` 显式写（Rule 0 静态检查看不见 dict 继承）
2. **笔记**：该站 HOW 全部写进模块 docstring（不是写进记忆、不是写进对话）
3. **决策**：踩到的坑/为什么这样做 → `docs/`；不能碰 → `docs/Rule0-不碰清单.md`
4. **测试**：新增/改动跑六套件，`verify_baseline --strict --check-source` 必须 rc=0（漂移清单 = 本轮改过的文件）
5. **台账**：动了受管文件 → 按「改默认 BASE → make_baseline → snapshot → verify+compare」重冻，并更新 `docs/版本台账.md`
6. **对齐**：`git add` 本轮文件 → commit → `git push origin main` → **`git rev-list --left-right --count HEAD...origin/main` 必须 `0 0`**（不靠人记，靠命令验）
7. **记忆**：只加"触发条件 + 动作 + 去哪查"；**参数表/版本号/测试数一律不进记忆**

### 一条判据（判断该写哪）

> 这条知识改了，是「代码要改」还是「人要重新判断」？
> 代码要改 → 进模块；人要重新判断 → 进 docs；什么时候该做什么 → 进本技能；其余不进记忆。

## 0. 硬闸：先判型，再谈接站（2026-11-17 加，因同类翻车两次）

**任何爬取任务的第一步不是侦察站点，是判定"信息性质"。** 读一眼 `~/.agents/skills/crawler-source-discovery/SKILL.md` 的 **§二·补 第 0 步：判型**：

| 型 | 判据 | 动作 |
|---|---|---|
| **A 单点权威** | 只有一个机构在产生 | **天气、法规、汇率、统计年鉴、开放数据** → 1~2 个一手源，找到就停，**不要走本技能的接站流程** |
| B 多源长尾 | 成千上万主体发布 | 招聘、租房、招投标 → 才用本技能 |
| C 账号在环 | 数据在平台内 | 先问账号 |
| D 开放 API | 已有接口 | 直接调接口 |

**A/D 型任务的正确动作**（反例记录：2026-11-16 抓郑州天气，跳过判型 → 连试 6 个门户站 → 得出结论"官方无数据"，实际中央气象台 1 个请求就够）：
- 天气：中央气象台 `nmc.cn/rest/province/<省码>` 取 stationid → `nmc.cn/rest/weather?stationid=<id>`（详见 crawler-source-discovery §天气标准动作）
- 法规：国务院/司法部/地方公报；汇率：中国外汇交易中心；统计：国家统计局
- **禁止**"为了多源验证去扫历史天气网/2345/天气后报"——那是聚合门户，不是一手源

判完型再往下看本节其余内容；B 型才需要"侦察 → 配置 → 试跑"这套。

## 0.1 先问清楚 4 件事（不要猜）

1. 目标网址（列表页 URL）
2. 要哪些字段
3. 要不要附件文件
4. 要多少（页数 / 条数）

用户答不上来就先"侦察"再问，不要瞎写选择器。

## 1. 侦察（10 分钟，别跳）

```powershell
# robots 先看：能不能抓、有没有 Crawl-delay、API 是否被禁
Invoke-WebRequest "<站点>/robots.txt" | Select-Object -Expand Content

# 列表页结构
& $py -c "import requests,sys; print(requests.get('LIST_URL',timeout=20).text[:4000])"
```

看三件事：列表条目在哪个标签里、详情链接长什么样、有没有分页（页码 or 下一页链接）。

## 2. 写站点模块 `crawlers\sites\<name>.py`

只写两样东西：`CONFIG` 和 `parse_list(html, page_url)`，需要详情再写 `parse_detail(html)`。
引擎（crawler.py）负责：限速、重试、robots、断点、去重、附件、报告。

```python
CONFIG = {
    "job": "<name>",
    "url_template": "https://x.com/list?page={page}",   # 或 "page_url"（单页）
    "paginate": "number",          # "number" | "next"（next 需 parse_next）
    "page_start": 1, "page_end": 5,
    "delay_min": 0.8, "delay_max": 1.5,
    "timeout": 20, "retries": 2, "backoff": 2.0,
    "respect_robots": True,
    "dedup_key": "detail_url",     # ← 必须按站点语义选，见下面"去重键"
    "detail": {"enabled": True, "delay_min": 0.8, "delay_max": 1.5,
               "timeout": 20, "retries": 1, "backoff": 2.0,
               "max_fail_ratio": 0.5, "required": ["title"],
               "respect_robots": True},
    "attachments": {"enabled": True, "dir": r"D:\agent-work\data\attachments",
                    "max_files_per_record": 5,
                    "max_file_bytes": 50 * 1024 * 1024,
                    "max_total_bytes": 500 * 1024 * 1024,
                    "respect_robots": True, "check_dns": True,
                    "allow_private_hosts": False,
                    "delay_min": 1.0, "delay_max": 2.0},
    "out_dir": r"D:\agent-work\data\raw", "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests", "report_dir": r"D:\agent-work\out\reports",
}

def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for a in soup.select("列表条目选择器 a"):
        rows.append({"title": a.get_text(strip=True),
                     "detail_url": urljoin(page_url, a["href"])})
    return rows

def parse_detail(html):
    soup = BeautifulSoup(html, "lxml")
    box = soup.select_one("正文容器")
    return {"body": box.get_text("\n", strip=True) if box else "",
            "attachments": [...]}     # 见"附件"一节
```

接口站（JSON）不用写 parse_list：改 `"response": "json"` + `CONFIG["json"]`
（`list_path` / `field_map` / `ok_path`+`ok_value` / `total_path` / `next_path` / `cursor_path`）。

## 3. 去重键（最容易搞错的一步）

- 一条记录一个唯一地址 → `detail_url`
- 同一页面下多条（一个公告多个附件、一个作者多句话）→ 用"业务键哈希"，别用 detail_url
  （实测：quotes 站用 detail_url 会把 100 条砍成 50 条）
- 键为空会被判 `dedup_key_empty` → partial，这是提醒你键选错了

## 4. 先跑 1 页，别直接全站

```powershell
cd D:\agent-work
$env:PYTHONIOENCODING='utf-8'
& .\venv\Scripts\python.exe crawlers\crawler.py --site <name> --pages 1 --job <name>_try1
```

看报告 `out\reports\report-<job>-*.json` 的 `status` / `stats` / `anomalies`。
`success` 才继续；`partial` 必须读 anomalies 找原因，不许"看着差不多就往下跑"。

## 4.5 页数口径与"页大小探测"（先做这两个再谈全量）

### 总页数：不要靠拍的
页面右上角常有 `<span>1</span>/949页`。站点模块加一行：

```python
"total_pages_pattern": r"</span>\s*/\s*(\d+)\s*页",
```

引擎行为（已实现，见 `declared_total_pages()`）：
- 从**本轮第一个真正抓到的页面**解析 M（续跑跳过第 1 页也能读到）
- `page_end = min(配置值, M)`；报告新增 `pages_declared / pages_planned / pages_effective / coverage / truncated`
- 默认上限被 M 截断且没显式 `--pages` → `partial / page_range_truncated`（rc=3）；显式 `--pages` → success 但 coverage 会显示
- 解析不到 → 按配置跑 + 一条 anomaly，不拦

### 页大小（pagesize 这类参数）：先探测，别猜
```powershell
& $py scripts\probe_pagesize.py --site <name> --param pagesize --value 50 --dry-run   # 先看 URL
& $py scripts\probe_pagesize.py --site <name> --param pagesize --value 50 --json
```
≤4 请求、间隔 5~6 秒、先查 robots 与冷却；三档结论 `effective / ineffective / unknown`。
**实测：温州人才网 pagesize 无效**（5 条→5 条，只有分页控件字节差）。

站点真用 page_size 时：写进 CONFIG 后 state 会记 `page_size`；**值一变就清 `pages_done`、保留 `seen_keys`**（页码与内容对应关系变了）。

## 5. 附件（要文件时）

`parse_detail` 返回 `attachments: [{"url":..., "name":...}]`，引擎负责：
- robots：按 origin 缓存；404=允许；401/403/5xx/超时=拒绝，**绝不当允许**
- 重定向**逐跳预检**：内网/被禁地址在发请求之前就拦下
- 文件名：URL 的文档扩展名优先（名字 `.doc`+URL `.docx`→`.docx`；名字 `.pdf`+URL `.php`→保留 `.pdf`）
- 落盘 `<dir>\<job>\<记录哈希>\<文件名>`，同名 `_1` 退避，绝不覆盖
- 记 `bytes` / `sha256` / `content_type`；`sniff_magic` 按扩展名校验文件头
- 上限三件套，超限只记链接；累计配额**跨页**累计

**robots 禁止的附件不自己决定抓不抓**：日志会打"要不要继续抓由你决定"，必须原样转告用户并等他定。

## 6. 导出表格

```powershell
& .\venv\Scripts\python.exe crawlers\clean.py --job <job> --site <name> --format xlsx,csv
```

- job 名带后缀（A/B 试跑）时一定加 `--site`，否则状态映射加载不到模块。
- `attachments` 会转成 JSON 字符串 + `attachments_count` / `attachments_ok` 两列（否则 xlsx 写不出来）。

## 6.5 交付：从原始数据到「三层投递清单」（数据→可用，0 请求）

抓完只是原料。**真正交付给用户的是筛过的清单**，而且这一步常常比抓取更容易做错。

### 日期口径（唯一最容易错的地方）

`published` 有**三种形态**，必须分开算，不许混成一个"未知"桶：

| 形态 | 例子 | 处理 |
|---|---|---|
| 绝对日期 | `2026-06-09` | 解析成日期算 `age_days` |
| **相对时间** | `2小时前` / `3天前` | **N天前=age N；N小时前=age 0**（它们是最新的，不是未知！） |
| 空 | `""` | 才进"日期缺失"桶 |

- **基准日必须写死**（用报告 `finished_at` 的日期），**不要 `now()`**——否则明天再跑结果就变，无法复现。
- 分桶惯例：**A ≤30 天 / B 31~90 / C >90 / D 空**。
- 自查：如果 A 层比预期少了一截，八成是把相对时间算成未知了（实测踩过：86 变 62）。

### 去重

- 键 = `公司名 + 岗位名`（两边都去空白、全角括号转半角）；
- 保留 `published` 最新的一条，另记「同岗位条数」；
- **只在 A/B 层内去重**；C 层（老广告）**不去重**，它用于"哪些公司常年招同一个岗位"的画像。

### 地区分组

`region` 分四组：**本地（如乐清）** / **市区**（鹿城·瓯海·龙湾·洞头）/ **其他县市** / **其他**。
理由：用户第一眼看的就是"在不在我这儿"，别让他自己在字符串里找。

### 产物结构（5 个 sheet）

| Sheet | 内容 |
|---|---|
| ⓪统计 | 输入文件、分桶计数、去重前后、A 层地区与薪资分布 |
| ①A-可直接投 | ≤30 天，按「年龄升序 → 薪资下限降序」（薪资解析失败的排最后） |
| ②B-备选 | 31~90 天，同列同排序 |
| ③C-仅公司画像 | >90 天，不排序，加备注「发布过久，不建议投」 |
| ④D-日期缺失 | 精简列 |

### 脚本放哪

放 `tools\`（**不在基线扫描范围**，不会造成漂移）；**不要放 `scripts\`，也不要改 `clean_jobs_*.py`**——
那些在 v7 基线里，改一个字 `verify_baseline --strict` 立刻漂移。

### 交付前必须报的三件事（实测得来的教训）

1. **"在架"≠"在招"**：502 条里只有 86 条是 30 天内的，345 条超 90 天（最早 5 月）。筛选条件（如 `jobtag=147`）只保证标签，不保证新鲜。
2. **金融/保险销售要单独标**：A 层 85 条里 24 条是证券/保险"顾问"，薪资常是提成上限。
3. **本地岗位占比很低**：全温州池子里乐清只占 3.5%（44/502）。想找本地岗，用 `WZ_CITY` 单独抓，别指望从大盘里筛。

参考实现：`D:\agent-work\tools\build_delivery_list.py`（0 请求，只读一个 jsonl）。

### 两个已踩过的坑

- **子表必须复用 `HEAD` 常量**：`row_of()` 固定返回 13 列，手写 7 列表头不会报错，只会静默错位（"薪资"列显示地区、"详情链接"列显示学历）。验收要查"表头列数 + 关键列内容形态"。
- **golden 只用于解析器回归**，别把筛选逻辑塞进 golden（筛选规则会变，解析结果不该变）。

## 6.6 改解析器/抽公共模块时：先做 golden（不然改错了没护栏）

330 项测试（六套件：test_crawler 217 / test_discover 32 / test_identify 21 / test_transport 23 / test_rule0 17 / test_render_batch 20）里绝大多数跑 mock，**测不到真实站点的解析器**。所以动 `parse_list` 或正则之前：

```powershell
& $py tools\parse_golden.py          # 用【改之前】的代码生成 tools\golden\*.json
# …改…
& $py tools\parse_golden.py --check  # 必须 0 差异
```

- golden 里存：样本名、站点、字节数、page_url、正则原文、声明总页数、卡片数、**每条记录全字段（按 key 排序）**
- 5 个真实样本对应测试用例 **139–143**；用例 139 额外断言正则**单反斜杠**（防"双重转义静默失效"复发）
- **golden 出现任何差异 → 立刻停，报告；不要"顺手修一修"**——那是行为变更，不属于重构范围
- 抽公共模块只抽**真正重复**的：`sites/_common.py` 里放 `TOTAL_PAGES_PATTERN` + `parse_total_pages()` + `pick()`；
  差异大的解析器（如 wzrc 有 `area_in_title`、yqwzrc 没有）**不要强行合并**
- `_common.py` 以下划线开头，**不计入"站点模块 N 个"**

## 7. 收尾门禁（改过代码就跑，顺序不能反）

```powershell
& $py tests\test_crawler.py *> logs\_crawler_tests_latest.txt   # 期望 217/217
# 只跑这一套属于漏检：另外五套也要跑（合起来 330 项）
& $py tests\test_discover.py; & $py tests\test_identify.py; & $py tests\test_transport.py
& $py tests\test_rule0.py;    & $py tests\test_render_batch.py
& $py tests\verify_baseline.py --strict          # 副本完好 = 80/80 rc=0
& $py tests\baseline_compare.py                  # 行为没变 = 49 项全过
& $py tests\test_baseline_guard.py               # 16/16
```
`baseline_snapshot.py` 会覆盖指纹，**只在确认接受新数字后**跑。
**对外发布前**必须 clone 一份到临时目录、用同一 venv 跑完六套；本机绿不算数。
当前活跃基线 **`crawlers\_baseline_v14_13_21`**：**81 条受管 / 330 项测试**；v1~v14_13_21 全部保留，绝不覆盖（v11 曾被误覆盖，见 `_DAMAGED.txt`）。
改 `baseline_snapshot.py` / `verify_baseline.py` 的默认 BASE 后**必须重新冻结**，否则 `--strict` 会报漂移。
冻结四步：**切默认 BASE（verify_baseline.py + baseline_snapshot.py 两处）→ 重跑 make_baseline_vN.py → baseline_snapshot.py → verify/compare/guard**（少一步就漂；漏第 2 步会报 3 个脚本漂移）。

## 8. 硬规矩（违反就出事）

- **不许并发**：单线程。间隔在 v12 起交给**闸门**管（12 次/分天花板 + 4.8~6.5 秒抖动），
  站点 `delay` 只当微抖动（0.3~0.8）；被限流过的站可继续用 `--delay 5 7`，闸门不会因此放宽
- **请求密度硬规则（v12 实现，不再是纪律）**：**≤12 次/分钟** 且 **单任务 ≤200 个请求** 且 **≤30 分钟**。
  实测（n=2）：约 9 次/分钟连发 111 个不触发（2026-11-11）；约 21 次/分钟、累计约 150 触发 IP 级封禁（2026-11-10）。
  预算语义：第 200 个放行、第 201 个抛；**作业上每批 ≤198 页**（199 页+robots 恰好用满，一次重试就没余量）。
  闸门停 → `partial / request_budget_exceeded`（有数据）或 `failed`（没数据），断点保留可续跑
- **不许删数据**：只移动/归档；重跑用 `--job` 分文件
- **不许把"没验过"说成"已验证"**：报告 `status` 是什么就说什么
- **交付前先看新鲜度**：抓到的条数 ≠ 可用条数；按 `published` 分桶后再报数字（见 6.5）
- 断点：数字分页记 `pages_done`，next 记 `urls_done`+`next_url`，两套不混用
- 真实站点只在阶段完成/验收时打；日常回归只用 `tests\mock_site.py` + `samples\`
- 附件/详情失败必须能在报告 `anomalies` 里查到原因，不许静默跳过

## 8.5 v14 才有的五件事（v12 时代的文档里没有）

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
数据其实完好。读 jsonl 一律 read_text().split("\n")；引擎和 clean.py 用 for line in f: 所以安全。
```

## 8.6 A5：滚动时间窗的 window 模式（v14.12.1）

适用：`settr=3` + `sort=rtime` 这类**滚动时间窗**，不是所有站。

```python
"coverage_mode": "window",
"refresh_pages": 3,
"refresh_stop_after_dups": 15,
```

行为（写死）：

- window 模式**每轮开跑清空 `pages_done`**，`seen_keys` 不清；
- 每轮只抓前 `refresh_pages` 页（默认 3 页）；跨天、同天第二次跑都会重抓；
- 连续 15 条都见过（3 页 × 5 条/页）→ `stop_reason=refresh_no_new`，仍是 `success`，不是 partial；
- `full` 模式完全不看时间维度，保持断点续跑；window 不要配给一次性快照任务；
- 完整快照用 `wzrc_all`，日常更新用 `wzrc_inc` 的 window 模式。

验收：mock 209（跨天）/210（full 对照）/211（同天二跑）/212（满页 15 条提前停）；
真实站 `wzrc_inc_a5test` 首跑 3 页/11 条，二跑 `pages_ok=3 / pages_skipped=0 / new=0`。

---

## 8.7 robots 四态（v14.13，会改变行为）

```
404                      -> absent      放行
401/403/5xx/其它非 200    -> denied      拒绝
200 且正文以 < 开头       -> unparsable  拒绝（fail-closed）
200 且 content-type=html 但正文含 robots 指令 -> ok（实测有服务器标错类型）
200 空 / 纯注释           -> ok
```

四个消费点必须一致：`crawler.load_robots`（主页面）、`crawler.origin_robots`（附件）、
`render_batch.robots_allows`（旧实现连 403 都放行）、`tools/probe_one.py`。
报告字段：`robots.status / bytes / groups`。

判据是「长相」不是「体积」：实测语料 23 个主机里 5 个 robots 是 HTML，
含两个政府站和一个 **552 字节**的小 HTML —— 用「>10KB 才算异常」会漏。

## 8.8 传输层：cffi vs plain（v14.4 起）

| 站型 | transport | 请求头 |
|---|---|---|
| 要跟 WAF 打交道（商业平台/招聘大站） | `"cffi"` | `identity.headers()` 全套 |
| 政务、企业官网、无风控 | `plain` | 4 个基础头（**刻意**，不是忘了接） |

现役 cffi：`foodlaw` / `foodmate` / `wzrc_all` / `wzrc_inc`。

切 cffi 的验收（缺一不可）：

```
① 同页 plain/cffi 解析结果零差异（条数/字段集/逐条内容）
② gate.requests_used 两边相等（证明逐跳都过闸）
③ 报告 transport 真写成 cffi（不是配了没生效）
④ soft_block.group 没被改动
```

注意：cffi 的 `Accept-Encoding` 多 `br`，**响应字节数会不同**——比解析结果，不比 raw bytes。

## 8.9 平台先验清单（v14.13.2）

`tools/geo/known_platforms.json`：踩过的平台记一笔，命中就不用再花请求试。
`discover.py` 的候选表会多一列 **「平台判定」**。

规则（写死）：

```
verified_at + ttl_days
  fresh   有效期内 → 直接给结论
  stale   过期     → 只打印"建议重验"，不删除、不当真理
confidence
  verified  实测过（有请求记录/报告）
  recorded  一句话记录，未逐条复验 → 输出标"记录级，未复验"
verdict
  blocked   允许 0 请求直接否
  usable    只给方向，放量前仍必须实探
域名只进 JSON，不进 .py
```

新增平台先验时：先跑 `identify.py` 或 `probe_one.py` 拿证据 → 写进 JSON →
`verified_at` 填当天 → 别把 `recorded` 写成 `verified`。

**Crawl-delay（v14.13.3）**：列表页/详情页/附件三处统一走 `polite_sleep()`，
取 `max(配置间隔, robots Crawl-delay)`；报告字段 `robots.crawl_delay_sec`。

## 8.10 74cms 家族（v14.13.4）

四个站共用一份解析器：`crawlers/sites/families/qscms74.py`

```python
parse_jobs(html, page_url, source_site, keep_area=False)
```

- `keep_area=True`：保留「鹿城区 | 」前缀到 `area_in_title`，`region` 回退到它（wzrc 系）
- `keep_area=False`：剥离前缀后丢弃（乐清分站）
- 站点模块只剩 3 行调用；筛选参数、冷却组、cooldown 都留在各自 CONFIG

**改这个家族模块的硬规矩**：

```
1. 先跑 golden：tests/data/qscms74_golden.json（4 站 × 5 条，含字段顺序）
2. 改完跑 test_crawler 6e；必须 diff=无
3. golden 出现任何差异 → 停，逐字段看，不许"顺手修一修"
```

新增同族站（第 5 个 74cms）：写站点 CONFIG + 3 行 `parse_list`，
先抓 1 页补进 golden，再跑 6e。

## 8.11 仓库可交付性：本机绿 ≠ 别人 clone 绿（v14.13.8 / v14.13.9）

这条不是接站流程，但**动过基线或测试就必须知道**，否则会把"本机绿"当成"可交付"。

```
1) .gitattributes 必须有：* text=auto eol=lf + 二进制例外（png/xls/xlsx/pdf/zip…）
   为什么：Git for Windows 的 system 级 core.autocrlf=true，别人 clone 后 .py/.json
   全变 CRLF（gate.py 7,313 → 7,520 B），verify 报「快照已损坏（改坏 43）」。
   本机 core.autocrlf=false 只是本地 config，不随仓库走，靠它等于没修。
   别用 * -text（字节同样稳，但 diff 变 Binary files differ，公开仓库没法 review）。

2) 测试夹具必须入库：tests/data/（当前 53 个文件 / 约 5.8 MB 公开页面快照）。
   .gitignore 里写 /data/ 要**锚根**——写成 data/ 会把 tests/data/ 一起吞，
   后果是 clone 后 test_identify 直接 FileNotFoundError（21 项全灭）、6e 读不到 golden，
   只剩 305/327。

3) 测试里不许有绝对路径：一律 ROOT = Path(__file__).resolve().parents[1]。
   写死 D:\agent-work 的后果不是报错，而是"在本机 clone 里跑其实读原仓库文件"——假绿。

4) 清理一次性脚本时保住基线内文件：tools/_murmur3.py 在 manifest 里，
   批量 git rm tools/_*.py 要排除它，否则 verify 直接红。
```

**克隆验收口径（唯一可信的验法）**：

```bash
git clone <repo> && cd <repo>          # 别在本机改 autocrlf，故意保持 true
python tests/test_crawler.py           # 217
python tests/test_discover.py          # 32
python tests/test_identify.py          # 21
python tests/test_transport.py         # 23
python tests/test_rule0.py             # 17
python tests/test_render_batch.py      # 20
python tests/verify_baseline.py --strict --check-source   # 必须 rc=0
```

六套 330 + verify rc=0 才算"仓库可交付"。
`baseline_compare` / `test_baseline_guard` 依赖 `data/`、`out/`、`logs/` 本地产物，
clone 里**按设计跑不了**，报「缺少源文件」属预期，别当 bug。

## 8.12 脱敏与发布：打码要打全，历史要重建（v14.13.12 / v14.13.14）

要把仓库公开、或把样本交给别人时，**这两件事必须一起做**，只做一半等于没做。

```
一、打码范围（漏过的那次：只扫手机，漏掉全部座机）
   E:\ 手机  1[3-9]\d{9}
   E:\ 座机  0\d{2,3}-\d{7,8}        ← 0577-/0571-/0535- 这类，一个页面常有 5~9 处
   还有：邮箱、微信号、QQ 号、真实姓名（样本里如果出现）
   做法：等长替换，别破坏结构
        手机 → 13000000000        座机 → 同前缀 + 全 0（0577-00000000）
        用 1********** 也行，但下游若按"全数字"解析要先改

二、改完 tests/data 必须重生成 golden
   tests/data/*.html 是解析样本，golden 是它的解析结果
   只改 HTML 不改 golden → 用例 6e「真实样本与 golden 一致」直接红（不是 bug，是没做全）

三、基线的判断
   tests/data 与 docs 通常**不在** manifest 受管清单里 → 打码不必重冻基线
   但如果动到了 crawlers/**.py、tests/test_*.py、tools/**.py 就必须重冻（v14.x 递增）

四、历史：git log -S 能翻出旧字节（最关键的一条）
   打码只改新提交 → `git log -S<旧号码>` 照样命中旧 commit
   公开仓库两条路（私有仓库无所谓，可保留完整历史）：
     a) 重建干净历史：git checkout --orphan clean && git commit → 单提交，用这个做公开起点
     b) filter-repo --replace-text 映射文件 → 改写全部历史后 force push
   我们的做法：私有 my 保留完整历史；公开 crawler-l1 重建为单提交（tag v14.13.14）
```

**验收三条（必须全空才算干净）**：

```bash
git grep -I -E '1[3-9][0-9]{9}'                    # 真实手机号 → 0
git grep -I -E '[^0-9]0[0-9]{2,3}-[0-9]{7,8}[^0-9]' # 真实座机 → 只剩掩码值
git log --all -S'<旧号码>'                          # 公开仓库 → 命中 0
```

**误报要认**：图片资产名里会出现 11 位数字（`adminad/202007/15942590038tx7u.jpg`），
它长得像手机号但不是电话；这类不要改——改了 golden 会跟着变，白折腾。

**别把"我改了"当成"我改干净了"**：v14.13.11 那轮就只打了手机号 34 处，
座机 86 处一个没动，还漏了苍南一个客服电话（在 `alt` 属性和可见文本里），
最后是被"全仓扫描"逼出来的。**扫描脚本比人工检查可靠**。

## 8.13 v14.13.18/19 新增的四件东西（不学这一节会踩坑）

`
① python tests/run_all.py          一条命令跑完
     默认：六套 + verify（零外网、不需本机产物）
     --local：再加 baseline_compare / test_baseline_guard（缺 data/out/logs 时计「跳过」不算失败）
     --list / --only crawler,identify
     它跑完整计划时会顺手刷新 logs/_crawler_tests_latest.txt —— compare 的证据源，
     所以**别再用 	est_crawler.py > logs/_crawler_tests_latest.txt 那种老写法**（会让 compare 少 5 条结果）。

② CRAWLER_HOME / crawlers/paths.py   路径不再写死
     paths.HOME 默认项目根，set CRAWLER_HOME=E:\other\agent-work 可整体搬家。
     新写脚本一律用 paths.* 或 _Path(__file__).resolve().parents[1]，禁止再出现盘符。

③ _swallow(tag, exc)   静默异常统一入口
     19 处 except…pass 已改为 _swallow：计数进 stats.swallowed / stats.swallowed_critical，
     关键路径（页数解析/状态加载/软封/hash）额外写一行 [忽略] … 分支出错（已计数）。
     日志落点靠模块级 _ACTIVE_LOG 注入；**不注入时退回 print**。
     ⚠️ 别在 helper 里直接调 log() —— 模块作用域没有 log，NameError 会被 except 吞掉，
     表现就是「计数有、日志永远没有」（v14.13.18 就是这么错的，v14.13.19 才修）。

④ CI + pyproject
     .github/workflows/test.yml：ubuntu + windows 双平台，装 requirements.txt → 六套 → verify
     pyproject.toml：只列直接依赖（requests/bs4/lxml/openpyxl），可选组 render/transport/excel/dev
`

**两条用血换来的规矩：**

`
A. 冻基线必须同步改三处，少一处就「本机假绿、clone 必红」：
   ① verify_baseline.py / baseline_snapshot.py 的 BASE
   ② .gitignore 的 !crawlers/_baseline_vX 例外
   ③ 新基线目录本身要 git add
   v14.13.18 只做了 ①③、漏了 ②，结果 clone 里 verify rc=2、CI 必红 —— 而本机因为磁盘上
   两份基线都在，80/80 一切正常。**「本机绿」永远不能当「可交付」的证据。**

B. 验证「别人 clone 能不能跑」只能用 git clone，不能用 git archive | tar -x：
   Windows 的 tar 处理中文文件名会丢文件（probe_杭州_job.html、zjrs_*.xlsx 都丢过），
   于是 test_identify / test_discover 报「样本缺失」——那是工具问题，不是仓库问题。
`

## 9. 排查清单

| 现象 | 先看哪里 |
|---|---|
| 0 条记录 | 选择器；先跑 probe_spa.py 确认层级 |
| 页面只有 ~6KB 空壳 | 第 1 层：搜 pi、etch(、.json |
| 有 __NEXT_DATA__ | 第 2 层：从 script 标签抠 JSON |
| status=partial | 报告 `anomalies` 的 reason |
| 详情全失败 | 是否要先访问列表页拿 cookie；`abort_on` 是否被 403 触发 |
| 附件全 robots_denied | 该域 robots 真的禁；转告用户等决定 |
| 附件全 dns_resolve_failed | 域名解析不通；别当"允许" |
| 二跑全 noop | 正常；要重抓用新 `--job` 或 `--reset`（会警告） |
| `pages_declared` 一直是 None | 正则被写成 `\\s`（双重转义）静默失效；统一用 `_common.TOTAL_PAGES_PATTERN` |
| 解析结果和昨天不一样但代码没改 | 跑 `tools\parse_golden.py --check`，看是哪几个字段变了 |
| `--detail-urls` 报 `detail_urls_no_parser` | 该站没有 `parse_detail`（如 wzrc_all，列表已带全字段）→ 不该用两段式 |
| `--detail-urls` 报 `detail_urls_empty` | 清单是空的：`pick_details` 的筛选条件太窄，或第 1 段还没跑 |
| 两段式第 2 段报 `attachment_partial` | 有附件没下成（看 `anomalies`）；详情本身可能是 ok 的，两件事分开记 |
| doctor 说"卡片密度 WARN pages_ok=0" | v12.3 起改判 PASS「不适用」；还是 WARN 说明你跑的不是 repair-only（见 10.6） |
| 分类页 `page/24` 返回的 title/条数像首页 | **分页超界回落首页**（RiPro 站常见），必须用 title 含分类名判定有效页，否则首页数据污染进去 |

---

## 8.14 付费资源站（RiPro 系 + AList 试看库）—— 判型速查

遇到"学分/金币/充值中心 + 网盘分享下载"的站，先按这套 4 请求定性，别急着接。

**指纹**：`wp-content/themes/ripro-v2|ripro-chlid`；按钮 `class="click-pay-post" data-postid/data-nonce/data-price`；容器 `div.ripay-content`；价格塞在 `<style>` 里（`.heading{width:19学分;}`）。

**三条硬结论（2026-11-16 源码审计 + 实测）**：

1. **下载链路绕不过**。`inc/goto.php` 三层校验：`wp_verify_nonce(…,'zb_down')` → `get_post_status==publish` → `get_user_pay_post_status()` 查订单。nonce 不绑 post_id 是个瑕疵，但订单校验兜底。GitHub 上的 RiPro 仓库全是"自己开店"的主题源码，**不存在"爬别人站"的项目或教程**。
2. **AList 预览站 = 试看库，不是漏配**。`fs/list`/`fs/get` 确实无需登录就能拿直链，但内容是截断的：**件数/集数给全、每个文件只给 5%~30%**（实测 335页→16页、68集→每集4.0分钟(应13.2)、27包→每本9~13页）。
3. **判"完整"必须数页数或测时长**（pypdf / ffprobe），不能看体积、不能看 PDF 头尾结构、不能信文件名里的"完整版"——这三种都踩过，判断反了。

**别浪费请求的面**：`wp-json`（401）、`xmlrpc.php`（0 字节）、`*.bak`（301）、`cao_pay_post` 未登录（400 "0"）、`viewer.php?file=`（WAF 拦）、AList `fs/search`（500 未建索引）、AList `path=/..`（403）。

**分页坑**：页码超界返回 **200 + 首页内容**，不是 404。

**决策**：只要目录 → 接列表页（算 crawl-delay 预算）；要文件 → 直接比价，没有免费路径。

详见 `D:\agent-work\docs\site-notes-ripro-alist.md`（含源码校验链路、AList 实测表、探测结果表）。

---

## 10. 两段式（列表与详情分两段跑）

### 10.1 什么时候该用

| 用两段式 | 不要用 |
|---|---|
| **列表页没有正文/没有附件/没有薪资**，要进详情才拿全（公告站、法规站、招标公告…） | 列表页已经带全 18 个字段（如 wzrc_all）→ 详情段纯属浪费 |
| 只要其中**一小部分**记录的详情（按关键词/地区/薪资/时间筛） | 每条都要详情且量很小（<20 条）→ 一次跑完更省事 |
| 详情页慢、附件大，想**分批**做 | 站点没有 `parse_detail` |

判断依据一句话：**「详情请求数 × 单价」是否明显大于「筛选后只剩几条」**。foodlaw 全量 78 请求 → 筛后 30，值得；wzrc 列表全字段，不值得。

### 10.2 第 1 段：只抓列表

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:WZ_TAG='0'
& .\venv\Scripts\python.exe crawlers\crawler.py --site foodlaw --job foodlaw_list --detail-mode off --pages 25
```

- `--detail-mode off` **同时关掉开跑前的例行详情补抓**（v12.3 修的；以前关不掉，会偷偷补）
- 报告 `pages_total > 0`、`records_new > 0`，`detail_repair_planned` 不存在或为 0
- 这一段把 `title / 薪资 / 地区 / published / detail_url / attachments(链接)` 全部落盘

### 10.3 第 2 段前：生成清单

```powershell
& .\venv\Scripts\python.exe tools\pick_details.py --job foodlaw_list ^
    --keyword 抽检,限量 --region 温州 --salary-min 5000 --only-pending --limit 50 ^
    --out D:\agent-work\data\raw\_cand_foodlaw.txt
```

- **0 请求**，只读第 1 段的 jsonl
- `--only-pending`：只挑详情还没抓全的（`detail_fetch != ok`）
- 薪资解析认 `3K-5K/月` / `3000-5000元` / `1万-1.5万/月`；`面议` → 视为无下限
- 清单里**自动 URL 去重**；空清单会被第 2 段明确拒绝（`detail_urls_empty`）

### 10.4 第 2 段：只抓清单里的详情

```powershell
& .\venv\Scripts\python.exe crawlers\crawler.py --site foodlaw --job foodlaw_list ^
    --detail-urls D:\agent-work\data\raw\_cand_foodlaw.txt
```

行为（v12.3 实测口径）：

- **列表页一个请求都不发**；`--detail-urls` 模式下也**跳过例行补抓**（否则会变"全补一遍"）
- 清单里的 URL **一律处理**（含上次已成功的——那是你明确要求重抓）
- 清单外的记录**一条都不碰**
- 若站点启用了附件：**对选中记录下附件**，`rewrite_rows` 原子回写
- 清单里有数据文件之外的 URL → 计数 `detail_urls_missing`，不崩

### 10.5 验收（三条硬指标，缺一不可）

| 检查 | 期望 | 怎么看 |
|---|---|---|
| **`stats.pages_total == 0`** | 列表页 0 请求 | 报告 JSON |
| **`datafile.records_before_run == total_after_run`** | 行数没变（只补字段） | 报告 JSON |
| **`datafile.records_new_this_run == 0`** | 不是"新增"，是"补齐" | 报告 JSON |
| 详情计数 | `detail_repaired_ok` = 清单里补成功的条数 | 报告 JSON |
| 状态 | 全成功 → `success / details_repaired`；有失败 → `partial / detail_pending_remains` | 同上 |

### 10.6 附件失败必须报 partial

第 2 段只要有附件没下成（`attach_download_failed / type_rejected / too_large / quota / robots_denied / private_host / dns_failed / stage_failed`），
整轮就是 **`partial / attachment_partial`（rc=3）**，**不许报 success**。
判定用的是主流程同一组计数键，别另写一套。详情成功与附件失败**分开记账**（详情仍 `ok`）。

### 10.7 doctor 必须能全 PASS

```powershell
& .\venv\Scripts\python.exe crawlers\doctor.py --job foodlaw_list
```

- 两段式第 2 段报告：`status/reason` 应为 `PASS  success / details_repaired`（v12.3 起 doctor 认这个 reason）
- `卡片密度` 应为 `PASS 不适用（本次未抓列表页：两段式第 2 段 / 补抓 / 补附件）`——**不是 WARN**
- `数据行数` 应为 `PASS  N 行（账目 N+0=N）`
- 目标是**8 项全 PASS**，出现 FAIL 先看是不是账目没同步

### 10.8 前置条件：站点必须有 `parse_detail`

`--detail-urls` 需要 `sites/<name>.py` 里的 `parse_detail(html)`。没有就报 `failed / detail_urls_no_parser`——
这是**显式拒绝**，不是崩溃，也不是"可以忽略"。遇到它说明这个站不该用两段式（列表已经全字段）。

### 10.9 参考用例（回归时看这几条）

| 用例 | 覆盖 |
|---|---|
| 194 | 只抓清单、清单外不动、`pages_total=0` |
| 195 | `pick_details` 的关键词 + only-pending + 去重 |
| 196 | 清单含数据外 URL → `detail_urls_missing` 计数 |
| 197 | `--detail-mode off` 不跑例行补抓 |
| 198 | 第 2 段只给选中记录下附件 |
| 199 | 账目 `before=2/new=0/total=2` 且 doctor 数据行数 PASS |
| 200 | 空清单 → `detail_urls_empty` 且账目自洽 |
| 201 | 两段式报告 doctor `status/reason` PASS |
| 202 | 第 2 段附件失败 → `partial / attachment_partial`（test_crawler 现 208 项，202 只是其中一条） |