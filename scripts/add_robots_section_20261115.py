# -*- coding: utf-8 -*-
"""把 robots 全情况清单插进人话版第六章「第一道：robots 检查」之后。"""
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

DOCS = Path(r"D:\agent-work\docs")
DOC = DOCS / "爬虫能力说明-给你的版本-20261112.md"
BAK = DOCS / "_backup_20261115"

ANCHOR = '**重要澄清**：robots 只管"哪些网址允许抓"，**不管"多久抓一次"**。robots 允许 ≠ 可以高频抓。'

BLOCK = """

#### robots 的全部情况（遇到具体站对不上号，查这张表）

上面五条是结论，下面是完整版。判断一个站能不能抓，**先看它回了什么，再看里面写了什么**，两步。

**第一步：拿到 robots.txt 那一刻（服务器怎么回的）**

| 拿到什么 | 常见长相 | 什么意思 | 它会怎么做 | 能不能抓 |
|---|---|---|---|---|
| **200** | 一串 `User-agent` / `Disallow` | 有规则 | 加载，之后每个网址都按它判 | 按规则 |
| **404** | 页面不存在 | **没写 robots = 没设限** | 全部放行 | ✅ 抓 |
| **401** | 要登录/要认证 | 规则不给你看 | 当"不允许" | ❌ 停 |
| **403** | 拒绝 | 明确不给你看 | 当"不允许"，**不重试** | ❌ 停 |
| **5xx** | 502/503/504 | 服务器故障 | 等 1 秒重试 1 次，还失败就停 | ❌ 停 |
| **429** | 请求太多 | 限流 | **不重试，直接停** | ❌ 停 |
| **超时/连不上** | — | 网络问题 | 同上重试 1 次 | ❌ 停 |
| **200 但内容是网页** | 一个 404 页被当成 200 返回 | 站点配置有问题 | 解析出 0 条规则 → 无规则 = 全部放行 | ⚠️ **会误放行** |

**这一列的规矩只有一条：404 = 放行，其它一切异常 = 不许。** 宁可少抓，不误抓。

最后一行是**已知缺口**（江苏 `js365job` 那种站，把"没这个文件"包装成 200 返回）。现在的代码看到 200 就当"有规则"，结果是"规则是空的 → 全放行"。这条口径还没修，遇到这类站要人工确认一次。

**第二步：内容里到底写了什么**

| # | 写法 | 例子 | 意思 | 能抓吗 |
|---|---|---|---|---|
| 1 | 空文件 / 只有 `#` 注释 | `# nothing` | 没有任何限制 | ✅ 全放行 |
| 2 | `Disallow:` 后面什么都不写 | 乐清人才网就是这样 | 等于没限制 | ✅ 全放行 |
| 3 | `Disallow: /` | 很常见 | 全站禁止 | ❌ 一条都不抓 |
| 4 | `Disallow: /admin/` | 后台目录 | 禁这个目录 | ✅ 其他地方能抓 |
| 5 | `Disallow: /job` | ⚠️ 最容易理解错 | **按前缀匹配**：`/job` `/jobs` `/jobinfo` `/job123` **全禁** | 看具体路径 |
| 6 | `Disallow: /job/*` | 通配 | `/job/` 下面全部 | ❌ 禁 |
| 7 | `Disallow: /*.js` | 禁 js | 所有 `.js` 结尾的网址 | 见下面「禁止 js」 |
| 8 | `Disallow: /*.js$` | `$` = 必须正好结尾 | `/a.js` 禁，但 `/a.js?v=1` **不禁** | 看具体网址 |
| 9 | `Disallow: /*?*` | 拉勾网就是这样 | **所有带 `?` 的网址**，等于禁掉全部搜索页和筛选页 | ❌ 等于全禁 |
| 10 | `Allow: /job/public/` 配 `Disallow: /job/` | 白名单 | 谁更长谁赢，更长的 Allow 放行 | ✅ 这个子目录能抓 |
| 11 | 单独一组 `User-agent: 某某爬虫` | 拉勾点名封 `Jobuispider` | 只对那个标志生效 | 我们用的是 Chrome 标志，走 `*` 那组 |
| 12 | `Crawl-delay: 10` | — | 每次至少隔 10 秒 | ✅ 能抓，但间隔取「你的配置」和「它要的」里更慢的 |

**写了但我们不认的两种**（知道就行，不影响正确性）：

| 指令 | 意思 | 现状 |
|---|---|---|
| `Request-rate: 1/10s` | 每秒最多几次 | ❌ 不识别（只认 `Crawl-delay`） |
| `Sitemap: https://…` | 站点地图 | ❌ 不读（引擎没有 sitemap 功能） |

**「禁止 js」到底是什么样子**

有三种写法，禁的都是 **js 文件本身**，不是页面：

```
Disallow: /*.js          ← 禁所有 js 文件
Disallow: /static/js/    ← 禁整个 js 目录
Disallow: /*.js$         ← 只禁"正好以 .js 结尾"的
```

所以对两种抓法的影响**完全不同**：

| 你怎么抓 | 会不会去要 js | 这条规则的影响 |
|---|---|---|
| **直接抓网页**（现在的主力方式） | **根本不要 js** | **零影响**。只发 1 个网页请求，js 一个都不碰 |
| **开真浏览器渲染** | **会自动加载全部 js/css/图片** | **影响致命**。浏览器一开就会去要 js，而那个 js 被禁了 |

这就是为什么渲染工具里有一条检查：**渲染前先看 robots，禁了 `*.js` 就直接不渲染**（探测和渲染都被拦，实际网页请求数 0）。

比"禁 js"更隐蔽的一种是 `Disallow: /*?*` —— 它禁的不是 js，是**所有带问号的网址**。而翻页全靠 `?page=2` 这种，等于把整套抓法禁掉了。

**判定规则（四条，记住就能自己推）**

```
① 只看网址里 ? 前面那段 + ? 后面那段，不看域名
② 把所有规则当"正则"去匹配，找出匹配上的
③ 匹配上的里面，取最长的那条（更具体的赢）
④ 一样长 → Allow 赢；一条都没匹配上 → 允许
```

第 ③ 条最容易踩：`Disallow: /job/` 和 `Allow: /job/public/` 同时存在时，`/job/public/a.html` 两条都能匹配，**更长的 Allow 赢 → 放行**。

**三个真实例子（都是我们真跑过的）**

```
① 温州人才网 wzrc.net
   GET /robots.txt → 404
   → 没设限，全部放行 → 后来抓了 3,828 条

② 乐清人才网 yqrc.com
   User-agent: *
   Disallow:
   → Disallow 后面是空的 = 不限制任何路径 → 全部放行

③ 拉勾网 lagou.com（2026-11-15 实测，85 字节全文）
   User-agent: Jobuispider
   Disallow: /

   User-agent: *
   Disallow: /*?*
   Disallow: /gongsi/v1/
   → 第一组点名封"职位爬虫"；第二组 /*?* 封掉所有带参数的网址
   → 而搜索、翻页、筛选全靠参数 → 站方等于明说"不接受抓取"
   → 结论：不是"难爬"，是"站方已明确拒绝"。按 18.9 的不碰清单处理
```

拉勾这个例子值得记住：**技术上能进站**（有头真 Chrome 能打开，数据就在页面里），**但人家写了告示**。这不是"爬不爬得动"的问题。

**自己查一个站，三步（第 1 步只要 1 个请求）**

```powershell
# 第 1 步：看它回了什么（最重要）
curl.exe -s -o - -w "`n[HTTP %{http_code} / %{size_download} 字节]`n" https://目标站/robots.txt

# 第 2 步：只挑出关键规则
curl.exe -s https://目标站/robots.txt | Select-String -Pattern "Disallow|Allow|Crawl-delay"

# 第 3 步：拿不准就把规则贴出来，让引擎判一遍（不发网络请求，0 成本）
```

第 1 步看到什么，对应怎么做：

| 看到 | 判断 |
|---|---|
| `[HTTP 404]` | 没设限，放心抓 |
| 一堆 `User-agent` | 有规则，重点看有没有 `Disallow: /` 和 `/*?*` |
| `<html>` 开头但状态 200 | 伪装的空 robots（见上面「已知缺口」），人工确认一次 |
| `[HTTP 403]` | 站方连规则都不给看，放弃 |

**一句话**：robots 只有两种结局 —— 要么它说"随便"，要么它说"不行"。中间那些通配、前缀、白名单，只是"哪些算不行"的更细说法。
"""


def main():
    src = DOC.read_text(encoding="utf-8")
    n = src.count(ANCHOR)
    if n != 1:
        print("[FAIL] 锚点命中 %d 次（应为 1），不写回" % n)
        return 1
    out = src.replace(ANCHOR, ANCHOR + BLOCK, 1)

    BAK.mkdir(parents=True, exist_ok=True)
    bak = BAK / ("plain_before_robots_%s.md" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DOC, bak)

    DOC.write_text(out, encoding="utf-8", newline="\n")
    raw = DOC.read_bytes()
    print("[OK] 已插入 robots 全情况")
    print("     字节 %d | 行 %d | MD5 %s"
          % (len(raw), raw.count(b"\n"), hashlib.md5(raw).hexdigest().upper()))
    print("     备份 %s" % bak.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())