# -*- coding: utf-8 -*-
"""
国学资源网 · 易学-六爻 分类
列表页即带齐大部分字段：标题 / 编号 / 页数 / 文件大小 / 学分 / 格式 / 该资源的预览分享码
robots：主站 crawl-delay=15（引擎取 max 自动遵守）；本分类页未被任何 Disallow 命中
"""
import re
from urllib.parse import urljoin

CONFIG = {
    "job": "gxzy_liuyao",
    "url_template": "https://www.guoxueziyuan.com/yixue/liuyao/page/{page}",
    "first_url": "https://www.guoxueziyuan.com/yixue/liuyao",
    "paginate": "number",
    "page_start": 1,
    "page_end": 23,          # 实测末页 = 23（22×21+10 = 472 条）；page/24 起回落首页，必须刹住
    "delay_min": 1.0,
    "delay_max": 2.0,
    "timeout": 25,
    "retries": 2,
    "backoff": 2.0,
    "respect_robots": True,
    "terms_status": "allowed",
    "dedup_key": "res_id",
    "transport": "plain",
    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}

RE_ART = re.compile(r"<article\b.*?</article>", re.S)
RE_URL = re.compile(r'<h2 class="entry-title"><a href="([^"]+)"')
RE_TITLE = re.compile(r'<h2 class="entry-title"><a[^>]*>\s*([^<]+?)\s*</a>', re.S)
RE_ID = re.compile(r"编号：\s*(\d+)")
RE_CREDIT = re.compile(r'meta-shhop-icon-left">\s*(\d+)\s*学分')
RE_SIZE = re.compile(r"文件大小：\s*([^<]*?)(?:\s{2,}其它|\s*其它：|$)", re.S)
RE_EXCERPT = re.compile(r'<div class="entry-excerpt">(.*?)</div>', re.S)
RE_PREVIEW = re.compile(r"https://yulan\.95959\.com/s/([A-Za-z0-9]+)")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_size(text):
    """从「335页，207.2 MB」/「共68个文件，1.65 GB」里拆页数与体积"""
    text = (text or "").strip()
    pages = None
    m = re.search(r"(\d+)\s*页", text)
    if m:
        pages = int(m.group(1))
    files = None
    m = re.search(r"共\s*(\d+)\s*个文件", text)
    if m:
        files = int(m.group(1))
    mb = None
    m = re.search(r"([\d.]+)\s*MB", text, re.I)
    if m:
        mb = _num(m.group(1))
    else:
        m = re.search(r"([\d.]+)\s*GB", text, re.I)
        if m:
            v = _num(m.group(1))
            mb = round(v * 1024, 1) if v is not None else None
    return pages, files, mb


def parse_list(html, page_url):
    rows = []
    for art in RE_ART.findall(html):
        m_url = RE_URL.search(art)
        m_id = RE_ID.search(art)
        if not (m_url and m_id):
            continue
        title = (RE_TITLE.search(art).group(1) if RE_TITLE.search(art) else "").strip()
        excerpt = RE_EXCERPT.search(art)
        size_text = RE_SIZE.search(excerpt.group(1)).group(1) if excerpt and RE_SIZE.search(excerpt.group(1)) else ""
        size_text = re.sub(r"\s+", " ", size_text)
        size_text = re.sub(r"\s*其它.*$", "", size_text).strip(" ，,")
        pages, files, mb = parse_size(size_text)
        credit = RE_CREDIT.search(art)
        preview = RE_PREVIEW.search(art)

        low = (title or "") + size_text
        if "视频" in low or "集" in size_text:
            fmt = "视频"
        elif "音频" in low or "录音" in low or ".mp3" in low.lower():
            fmt = "音频"
        elif files:
            fmt = "多文件合辑"
        else:
            fmt = "文档"

        rows.append({
            "res_id": m_id.group(1),
            "title": title,
            "credits": int(credit.group(1)) if credit else None,
            "size_text": size_text,
            "pages": pages,
            "files": files,
            "size_mb": mb,
            "format": fmt,
            "preview_share": preview.group(1) if preview else "",
            "detail_url": urljoin(page_url, m_url.group(1)),
        })
    return rows