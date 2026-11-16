# -*- coding: utf-8 -*-
"""
站点配置：quotes.toscrape.com（Scrapy 官方练习站，名言 + 作者 + 标签）

这个文件的存在就是为了证明一件事：
    换一个网站，只写这一个文件，不用碰 crawler.py。

字段：title(名言) / author(作者) / tags(标签) / detail_url(详情页) / tag_count
分页：/page/1/ ... /page/10/，每页 10 条，全部 100 条
"""

CONFIG = {
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "quotes",
    "url_template": "https://quotes.toscrape.com/page/{page}/",
    "page_start": 1,
    "page_end": 10,

    "delay_min": 1.2,
    "delay_max": 2.5,
    "timeout": 20,
    "retries": 3,
    "backoff": 2.0,

    "respect_robots": True,
    # 关键教训：这个站每条名言没有独立详情页，只有作者页。
    # 如果用 detail_url（作者页）当去重键，同一作者的多条名言会被当成重复丢掉
    # —— 实测 100 条只留下 50 条。所以这里用「作者 + 名言正文」的哈希做键。
    "dedup_key": "quote_key",

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
}

RATING_WORDS = {}   # quotes 站没有评分，clean.py 会跳过对应清洗


def parse_list(html, page_url):
    import hashlib
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    rows = []

    for q in soup.select("div.quote"):
        text_el = q.select_one("span.text")
        au_el = q.select_one("small.author")
        tags = [t.get_text(strip=True) for t in q.select("a.tag")]
        link = q.select_one("a[href]")

        text = text_el.get_text(" ", strip=True) if text_el else ""
        # 去掉两头的中英文引号（网站用 “” 包起来）
        text = text.strip("\u201c\u201d\"' ")
        author = au_el.get_text(strip=True) if au_el else ""

        # 去重键：作者 + 正文。同一作者的不同名言不会被误判重复
        key = hashlib.sha1((author + "|" + text).encode("utf-8")).hexdigest()[:16]

        rows.append({
            "quote_key": key,
            "title": text,
            "author": author,
            "tags": ",".join(tags),
            "tag_count": len(tags),
            "author_url": urljoin(page_url, link["href"]) if link and link.has_attr("href") else "",
        })

    return rows