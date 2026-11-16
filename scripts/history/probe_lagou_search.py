# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""连真 Chrome：① 看首页 __NEXT_DATA__ 结构（离线）② 导航到搜索页看是否要登录（1 请求）。"""
import json, os
from playwright.sync_api import sync_playwright

OUT = r"D:\agent-work\data\raw\_probe_lagou"
os.makedirs(OUT, exist_ok=True)
SEARCH = "https://www.lagou.com/wn/jobs?kd=java&city=%E5%85%A8%E5%9B%BD&pn=1"

def card_stats(pg):
    return pg.evaluate(r"""(() => {
      const t = document.body ? document.body.innerText : "";
      return {
        url: location.href, title: document.title,
        textLen: t.length,
        items: document.querySelectorAll('[class*=positionItem]').length,
        loginWords: ['登录后查看','请先登录','扫码登录','立即登录','登录查看更多'].filter(w=>t.includes(w)),
        head: t.slice(0, 180)
      };
    })()""")

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    pg = None
    for ctx in b.contexts:
        for x in ctx.pages:
            if "lagou.com" in x.url:
                pg = x
    if pg is None:
        raise SystemExit("NO_PAGE")

    # ① 首页 __NEXT_DATA__ 结构
    nd = pg.evaluate(r"""(() => {
      const d = window.__NEXT_DATA__;
      if (!d) return {none:true};
      const props = d.props || {};
      const out = {page: d.page, buildId: !!d.buildId, topKeys: Object.keys(d)};
      out.propKeys = Object.keys(props);
      const pp = props.pageProps || {};
      out.pagePropKeys = Object.keys(pp).slice(0, 40);
      const firstArr = Object.keys(pp).find(k => Array.isArray(pp[k]) && pp[k].length);
      if (firstArr) {
        out.arrayKey = firstArr;
        out.arrayLen = pp[firstArr].length;
        out.firstItem = JSON.stringify(pp[firstArr][0]).slice(0, 600);
      }
      out.html_len = d ? 0 : 0;
      return out;
    })()""")
    print("== HOME __NEXT_DATA__ ==")
    print(json.dumps(nd, ensure_ascii=False, indent=1)[:2500])
    print("== HOME CARDS ==")
    print(json.dumps(card_stats(pg), ensure_ascii=False)[:800])

    # ② 导航到搜索页
    try:
        pg.goto(SEARCH, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print("goto exc:", type(e).__name__, e)
    pg.wait_for_timeout(4000)
    print("== SEARCH PAGE ==")
    print(json.dumps(card_stats(pg), ensure_ascii=False, indent=1))
    html = pg.content()
    open(os.path.join(OUT, "real_chrome_search.html"), "w", encoding="utf-8").write(html)
    print("search_html_bytes:", len(html.encode("utf-8")))
    nd2 = pg.evaluate("(() => { const d=window.__NEXT_DATA__; if(!d) return null; const pp=(d.props||{}).pageProps||{}; return {keys:Object.keys(pp).slice(0,30)}; })()")
    print("search __NEXT_DATA__ keys:", json.dumps(nd2, ensure_ascii=False)[:800])
    b.close()
print("DONE")