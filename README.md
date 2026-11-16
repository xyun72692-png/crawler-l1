# 通用网页数据采集引擎（L1 · 服务端渲染）

为「公开、分散、需要领域知识才能整理」的数据源设计的**单机爬虫引擎**。

不追求批量抓大平台，追求**抓下来的东西能被验证、能被复现、不给自己惹事**。

---

## 它是什么

一个通用引擎 + 一层薄薄的站点模块。引擎负责所有"每个站都一样"的脏活：

- `robots.txt` 四态判定（404 放行 / 401·403 拒绝 / **200 但内容是 HTML 判"无法确认"并直接拒** / 正常解析）
- 请求闸门：每个真实请求（含重定向每一跳）都过速率、预算、时长三道闸
- 断点续跑：页码断点 / next 链断点 / 筛选条件指纹（换了筛选自动作废旧断点）
- 去重：跨页、跨任务、按站点语义选去重键
- 详情页：robots、限速、重试退避、熔断、必填字段校验统一在引擎里
- 附件下载：逐跳 SSRF 校验、robots 按 origin 缓存、大小/数量/类型三重上限、文件头校验
- 报告：状态机（success / partial / failed / noop）+ 可读的 Markdown 报告

站点模块只写两个函数：`parse_list(html, page_url)` 和 `parse_detail(html)`。

---

## 能力矩阵（三态标注，不打包票）

| 形态 | 状态 | 说明 |
|---|---|---|
| 服务端渲染列表 + 数字分页 | ✅ | 真实站点验证过；含"页面总页数声明 → 夹紧/截断"语义 |
| 详情页二次抓取 | ✅ | 真实站点验证过，含失败补抓 |
| 附件下载（PDF / DOC / XLS / ZIP） | ✅ | 真实站点验证过；robots 逐跳、类型白名单、文件头校验 |
| 断点续跑 / 去重 / 筛选指纹 | ✅ | 真实站点验证过 |
| JSON 接口 | ⚠️ | 仅假站验证；真实站点目前用 HTML + 自行 `json.loads` |
| next 链 / 游标分页 | ⚠️ | 仅假站验证 |
| JS 渲染（Playwright / CDP） | ⚠️ | 工具在 `tools/render_batch.py`，**未接入主引擎** |
| 登录后页面 | ❌ | 设计上不做 |
| 签名 / 加密接口逆向 | ❌ | 明确不做（见下） |
| APP 抓包 | ❌ | 明确不做 |

> ⚠️ 的含义是"代码在、假站测过、真实站点没验过"。这一栏不到 ✅，README 就不会写 ✅。

---

## 快速开始

```powershell
git clone https://github.com/xyun72692-png/crawler-l1.git
cd crawler-l1

python -m venv venv
.\venv\Scripts\Activate.ps1        # PowerShell
# cmd.exe 用：venv\Scripts\activate.bat
pip install -r requirements.txt

# 六套回归测试全部跑本地假站，零外网请求
python tests/test_crawler.py
python tests/test_discover.py
python tests/test_identify.py
python tests/test_transport.py
python tests/test_rule0.py
python tests/test_render_batch.py
```

跑一个真实站点之前，先看一眼你要抓的站的 `robots.txt`——这是这个项目的第一个动作，不是最后一个。

---

## 设计约束：这四件事决定了代码长什么样

### 1. Rule 0 —— 只碰明确允许的

站点模块必须显式声明 `terms_status`。`robots.txt` 禁止 → **默认直接拒**。
唯一的例外是显式 `--ignore-robots`（只用于你已获得书面授权的站）：它会打终端告警，并把 `ignore_robots` 写进报告 `overrides`；**默认永远关闭**。
WAF 挑战页、HTML 冒充 robots、同字节数响应 → 按"无法确认"处理（fail-closed），不当成放行。

### 2. 请求闸门 —— 速度是硬约束

```
默认 4.8~6.5 秒/请求、12 次/分钟、单任务 200 次、单次运行 1800 秒
```

站点配置里的 `delay_min/delay_max` 只是**配置层**，实际节奏由闸门兜底。重定向的每一跳都计数——否则 302 会白嫖预算。

### 3. 一次抓不全就分次

断点是真相源，不是缓存。异常时当前页**不进**已完成集合，游标指回自己，下次重抓。宁可多一个请求，也不把"中断"固化成"抓完了"。

### 4. 不做清单（换来的东西比失去的多）

| 不做 | 原因 |
|---|---|
| 逆向签名参数（`__zp_stoken__` 这类） | 平台改一次跟一次，长期维持不住 |
| 破滑块 / 验证码 | 同上，且性质变了 |
| 代理池轮换 | 把"公开数据采集"变成"对抗 WAF" |
| WebGL / Canvas / 音频指纹伪造、设备 ID 伪造 | 军备竞赛，一人 + AI 维持不住 |
| 登录态采集 | 用你的账号抓 = 性质变化，robots 语义也失效 |

这些不是"做不到"，是**做下去这个项目的卖点会从"可验证"变成"能不能过反爬"**。

> **关于"最小去自动化痕迹"的说明**：本项目**做**三件小事——隐藏 `navigator.webdriver`、
> 去掉 `--enable-automation`、让 TLS 指纹与 UA 对齐到同一个 Chrome 版本；**不做** WebGL /
> Canvas / 音频指纹伪造、不做代理轮换、不做设备 ID 伪造。前者的目的只有一个：让程序访问
> 不因为"自动化标记"被 WAF 误判成攻击，**只用于已通过 robots 判定的站点**，不用于绕过
> 任何访问控制。

---

## 仓库结构

```
crawlers/
  crawler.py            引擎（单文件，约 4,300 行）
  gate.py               请求闸门
  robots_rules.py       robots 解析与四态判定
  identity.py           唯一身份源（UA / Sec-CH-UA / impersonate 同源校验）
  curl_adapter.py       传输层适配（curl_cffi，逐跳过闸门）
  rule0.py              Rule 0 静态检查
  sites/                站点模块（11 个业务 + 16 个假站夹具）
  _baseline_v14_13_16/  当前活跃的验收基线样例（其余历史版本未入仓库）
tools/                  数据源发现 / 平台判型 / 渲染 / 解析基准
tests/                  六套回归测试 + 基线快照与校验
docs/                   能力报告、方案文档、结构审计
```

---

## 验证体系

这个项目最花时间的不是写爬虫，是**让"抓完了"这句话可信**。

- 六套测试，全部跑本地假站（`tests/mock_site.py`），零外网
- 基线快照：`manifest.csv` 记录受管文件的 MD5，`verify_baseline.py` 逐项比对
- 状态机覆盖：`success / partial / failed / noop` 的 27 种组合全部有断言——否则重构改坏一条判定，测试仍可能全绿
- 反自证：绝不用"副本和自己比 MD5"，绝不"先改答案再考试"

### 克隆后能直接跑（零外网、不依赖本机抓取产物）

```bash
python tests/test_crawler.py        # 216 项
python tests/test_discover.py       #  32 项
python tests/test_identify.py       #  21 项
python tests/test_transport.py      #  21 项
python tests/test_rule0.py          #  17 项
python tests/test_render_batch.py   #  20 项
# 合计 329 项

python tests/verify_baseline.py --strict --check-source   # 以输出为准：应显示「副本完好」且 rc=0
```

### 本地回归门禁（需要本机已抓过的产物）

这三道依赖 `data/`、`out/`、`logs/` 里的历史产物，它们**按设计不入库**（体积大且含第三方站点内容）。
刚 clone 的仓库跑起来会明确报「缺少源文件」，那不是代码错。

```bash
python tests/baseline_compare.py       # 硬指标 49 项
python tests/test_baseline_guard.py    # 故障注入 16 项
```

### `tests/data/` 是什么

`tests/data/`（53 个文件 / 约 5.8 MB）是**公开页面的静态快照**，只用于解析器回归（离线、不发起任何请求）。
页面内容版权归各原站所有，不随本项目授权；保留它们是为了让别人 clone 之后能跑满 329 项。

### 行尾（重要）

仓库带 `.gitattributes`（`* text=auto eol=lf`）。Git for Windows 的 system 级 `core.autocrlf=true`
会让克隆出来的 `.py` 变 CRLF，基线 MD5 就对不上、`verify_baseline` 会报「改坏 43」。
有了 `.gitattributes`，克隆出来的字节与本机一致，门禁才成立。

---

## 作者声明

> 本项目由作者与 AI 协作完成。**作者没有编程基础**，能交付但不能保证及时维护。
> 关闭了 Issue，不是不接受意见，是不想让你等了三个月没有回音。
> 每一条设计取舍都在 `docs/` 里写了理由，包括做错的和改掉的部分。

---

## FAQ

**Q：和 Scrapy 有什么区别？**
A：Scrapy 是给你搭程序的框架；这个是给**AI 写、人来验**的引擎——站点模块只有两个函数，剩下的判定、断点、报告、验收全在引擎里。卖点是验证体系，不是吞吐量。

**Q：为什么不并发？**
A：目标场景是"一次性抓一份完整快照"。并发必然触发站点限流，换来的只是把自己的 IP 更快打上去。实测：某地方人才网连续约 150 次请求后全站返回假页，10 分钟不恢复。

**Q：能抓 BOSS / 智联 / 拉勾吗？**
A：不能，而且不是技术问题。这类站要么用签名参数（不做），要么 robots 明示 `Disallow: /*?*`（不碰）。文档里记了实测过程。

**Q：接一个新站要多久？**
A：能接的站（服务端渲染、robots 允许）通常 2~4 小时：侦察 → 判型 → 写 50~200 行模块 → 跑 1 页 → 验收。JS 渲染站要额外验证，且不保证成功。

**Q：抓下来的数据在哪？**
A：不在这个仓库里。`data/`、`out/`、`logs/` 全部被 `.gitignore` 排除——数据含第三方内容，不该随代码分发。

**Q：为什么有 `_add_xxx.py`、`_fix_xxx.py` 这种文件？**
A：这是项目演进的真实痕迹。作者不会手写代码，每次改动都是"生成一个补丁脚本 → 执行 → 验收"。保留它们是为了让每一步可回溯。

**Q：`_baseline_v2` 到 `_baseline_v14` 为什么不在仓库里？**
A：31 份基线快照共 28 MB，只把当前活跃的一份作为样例留下。其余在作者本地。

---

## 许可

MIT。使用时请遵守目标站点的 `robots.txt` 与服务条款——这个项目的全部设计都建立在这条前提上。