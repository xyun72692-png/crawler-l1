# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""连到已开的真 Chrome（CDP 9222），读拉勾页面 DOM。零新增网络请求（页面已加载）。"""
import json, os, sys
from playwright.sync_api import sync_playwright

OUT = r"D:\agent-work\data\raw\_probe_lagou"
os.makedirs(OUT, exist_ok=True)

JS = r"""(() => {
  const t = document.body ? document.body.innerText : "";
  const cls = new Map();
  document.querySelectorAll('[class]').forEach(e => {
    const c = (e.getAttribute('class')||'').split(/\s+/)[0];
    if (c) cls.set(c, (cls.get(c)||0)+1);
  });
  const top = [...cls.entries()].sort((a,b)=>b[1]-a[1]).slice(0,15);
  return {
    url: location.href,
    title: document.title,
    webdriver: navigator.webdriver,
    textLen: t.length,
    anchors: document.querySelectorAll('a').length,
    clsTop: top,
    head: t.slice(0, 600),
    loginWords: ['登录后查看','请先登录','扫码登录','立即登录'].filter(w=>t.includes(w)),
    scriptTags: document.querySelectorAll('script').length,
    nextData: !!window.__NEXT_DATA__,
    initial: Object.keys(window).filter(k=>/INITIAL|__NUXT|__APP/i.test(k)).slice(0,5)
  };
})()"""

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    print("browser:", b.browser_type.name, "contexts:", len(b.contexts))
    pages = []
    for ctx in b.contexts:
        pages += ctx.pages
    for pg in pages:
        print("  page:", pg.url[:100])
    tgt = None
    for pg in pages:
        if "lagou.com" in pg.url:
            tgt = pg
            break
    if tgt is None:
        print("NO_LAGOU_PAGE")
        sys.exit(1)
    tgt.wait_for_timeout(1500)
    info = tgt.evaluate(JS)
    print(json.dumps(info, ensure_ascii=False, indent=2)[:3500])
    html = tgt.content()
    with open(os.path.join(OUT, "real_chrome.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("html_bytes:", len(html.encode("utf-8")))
    b.close()
print("DONE")