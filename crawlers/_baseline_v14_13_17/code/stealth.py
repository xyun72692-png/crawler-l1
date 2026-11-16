# -*- coding: utf-8 -*-
"""渲染通道的最小去自动化痕迹（v14 阶段 2 前置）。

**定位：薄封装，不是 stealth 全家桶。**
只做三件必须做的事（对应 §4.1.1 的 ①④⑤）：

  1. 启动参数去掉 Playwright 默认注入的 `--enable-automation`，
     并关掉 Blink 的 AutomationControlled 特性 → `navigator.webdriver` 不再被置真
  2. init script 兜底：把 `navigator.webdriver` 定义成 false（双保险，防某些版本又设回去）
  3. 补齐 `navigator.languages`（无 locale 覆盖时由浏览器自身给出，这里只做兜底）

不做（明确不碰）：WebGL 指纹伪造、Canvas 噪声、字体枚举、CDP 残留清理、
                指纹随机化、代理/时区伪造。这些属于对抗升级，方案第七节已列为"不做"。

上游如果以后要换成 playwright-stealth（2.0.3 / MIT / 19 个补丁），
只要把 `INIT_SCRIPT` 换掉、`LAUNCH_ARGS` 保留即可，调用方不用改。
"""

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",   # 减少跨域 iframe 差异
]

IGNORE_DEFAULT_ARGS = ["--enable-automation"]

INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
if (!navigator.languages || navigator.languages.length === 0) {
  Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
}
"""


def launch_kwargs(channel=None, headless=True):
    """给 `p.chromium.launch(**...)` 用。"""
    kw = {"headless": headless,
          "args": list(LAUNCH_ARGS),
          "ignore_default_args": list(IGNORE_DEFAULT_ARGS)}
    if channel:
        kw["channel"] = channel
    return kw


def prepare_context(ctx):
    """给 `browser.new_context(...)` 出来的上下文补 init script。"""
    try:
        ctx.add_init_script(INIT_SCRIPT)
    except Exception:
        pass
    return ctx