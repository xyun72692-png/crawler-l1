# 一次性侦察脚本（归档于 v14.13.16）
# 未经引擎闸门（robots 判定 / 限速 / 报告），不要复用；
# 需要正式抓取请写 crawlers/sites/<name>.py 交给引擎。
# -*- coding: utf-8 -*-
"""真 Chrome 里验 3 件事：robots.txt 能否读到 / 第 2、3 页能否翻（是否吃滑块）。间隔 6s。"""
import json, os, time
from playwright.sync_api import sync_playwright

OUT = r"D:\agent-work\data\raw\_probe_lagou"
os.makedirs(OUT, exist_ok=True)
BASE = "https://www.lagou.com/wn/jobs?kd=java&city=%E5%85%A8%E5%9B%BD&pn={}"

def stat(pg, tag):
    d = pg.evaluate(r"""(() => {
      const t = document.body ? document.body.innerText : "";
      let n = 0, total = null;
      try {
        const nd = window.__NEXT_DATA__;
        const init = nd && nd.props && nd.props.pageProps && nd.props.pageProps.initData;
        const pr = init && init.content && init.content.positionResult;
        if (pr && pr.result) { n = pr.result.length; total = pr.totalCount; }
      } catch (e) {}
      return {url: location.href, title: document.title, textLen: t.length,
              jsonJobs: n, totalCount: total,
              captcha: /访问验证|滑动|TraceID/.test(t),
              pageNoHint: (t.match(/职位（[^）]*）/) || [null])[0]};
    })()""")
    print(f"[{tag}]", json.dumps(d, ensure_ascii=False))
    return d

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    pg = None
    for ctx in b.contexts:
        for x in ctx.pages:
            if "lagou.com" in x.url:
                pg = x
    if pg is None:
        raise SystemExit("NO_PAGE")

    # ① robots.txt
    try:
        r = pg.goto("https://www.lagou.com/robots.txt", wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_timeout(1500)
        txt = pg.evaluate("document.body ? document.body.innerText : ''")
        print(f"[robots] status={r.status if r else '?'} len={len(txt)}")
        print("  head:", txt[:300].replace("\n", " "))
        open(os.path.join(OUT, "robots_via_browser.txt"), "w", encoding="utf-8").write(txt)
    except Exception as e:
        print("[robots] EXC", type(e).__name__, e)
    time.sleep(6)

    # ② pn=2  ③ pn=3
    for pn in (2, 3):
        try:
            r = pg.goto(BASE.format(pn), wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(3500)
            d = stat(pg, f"pn={pn} http={r.status if r else '?'}")
            if d["jsonJobs"]:
                ids = pg.evaluate("""(() => {
                  const nd = window.__NEXT_DATA__;
                  const pr = nd.props.pageProps.initData.content.positionResult.result;
                  return pr.slice(0,3).map(j => j.positionId + ':' + j.positionName);
                })()""")
                print("   ids:", json.dumps(ids, ensure_ascii=False))
        except Exception as e:
            print(f"[pn={pn}] EXC", type(e).__name__, e)
        time.sleep(6)
    b.close()
print("DONE")