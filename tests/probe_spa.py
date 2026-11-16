# -*- coding: utf-8 -*-
"""
前两层能力探测：对一个站，判断该走"找接口"还是"抠内嵌 JSON"，还是必须上渲染。

只做两件事，不抓数据、不入库：
  1. 看 robots 允不允许抓这个路径
  2. 拿一次 HTML，做"空壳判定"和"内嵌 JSON / API 线索"扫描

用法：
    python tests\probe_spa.py https://example.com/list
"""
import json
import re
import sys
import urllib.robotparser
from urllib.parse import urlsplit

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DataCrawler/1.0"
TIMEOUT = 20

# 常见的内嵌数据 / 框架标记
EMBED_MARKERS = [
    "__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "window.__DATA__",
    "application/ld+json", "application/json", "data-server-rendered",
]
# 页面里可能出现的接口线索
API_PATTERNS = [
    r'["\'](/[a-zA-Z0-9_\-/]*api[a-zA-Z0-9_\-/]*)["\']',
    r'["\'](https?://[^"\']*api[^"\']*)["\']',
    r'["\']([^"\']*\.json(?:\?[^"\']*)?)["\']',
    r'fetch\(\s*["\']([^"\']+)["\']',
    r'axios\.\w+\(\s*["\']([^"\']+)["\']',
]


def robots_allows(sess, url):
    p = urlsplit(url)
    robots_url = "%s://%s/robots.txt" % (p.scheme, p.netloc)
    try:
        r = sess.get(robots_url, timeout=TIMEOUT)
    except Exception as e:
        return None, "robots 取不到（%s）" % type(e).__name__
    if r.status_code == 404:
        return True, "robots 404 = 未设限"
    if r.status_code != 200:
        return False, "robots HTTP %d（保守视为不允许）" % r.status_code
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    ok = rp.can_fetch(UA, url)
    delay = None
    try:
        delay = rp.crawl_delay(UA) or rp.crawl_delay("*")
    except Exception:
        pass
    return ok, ("robots 允许" if ok else "robots 禁止") + (
        "，Crawl-delay=%s" % delay if delay else "")


def main():
    if len(sys.argv) < 2:
        print("用法: python tests\\probe_spa.py <URL> [URL2 ...]")
        return 2
    sess = requests.Session()
    sess.headers["User-Agent"] = UA

    for url in sys.argv[1:]:
        print("=" * 74)
        print("URL:", url)
        ok, why = robots_allows(sess, url)
        print("robots:", why)
        if ok is False:
            print("→ 不抓，直接结束（要不要绕由用户决定）")
            continue

        try:
            r = sess.get(url, timeout=TIMEOUT)
        except Exception as e:
            print("请求失败:", type(e).__name__, e)
            continue

        html = r.text or ""
        print("HTTP %d  字节 %d  Content-Type %s"
              % (r.status_code, len(html), r.headers.get("Content-Type")))

        # 1) 空壳判定：正文文本太少 / 明确的框架挂载点
        body_text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
        body_text = re.sub(r"<[^>]+>", " ", body_text)
        body_text = re.sub(r"\s+", " ", body_text).strip()
        print("去掉脚本后的可见文本: %d 字符" % len(body_text))
        print("框架挂载点:", "有" if re.search(r'id="(app|root|__next)"', html) else "无")

        # 2) 内嵌 JSON 线索
        found = [m for m in EMBED_MARKERS if m in html]
        print("内嵌数据标记:", found or "无")

        # 3) 接口线索
        apis = []
        for pat in API_PATTERNS:
            for m in re.findall(pat, html):
                if isinstance(m, tuple):
                    m = m[0]
                if m not in apis and len(apis) < 12:
                    apis.append(m)
        print("接口线索:", apis or "无")

        # 4) 结论
        if found and len(body_text) < 800:
            print("→ 判定：第 2 层（抠内嵌 JSON）")
        elif apis:
            print("→ 判定：第 1 层（照着线索找接口）")
        elif len(body_text) < 300:
            print("→ 判定：空壳，且无线索 → 才需要第 3 层（渲染）")
        else:
            print("→ 判定：服务端渲染，直接抓 HTML 就行（不需要 1/2/3 层）")


if __name__ == "__main__":
    sys.exit(main())