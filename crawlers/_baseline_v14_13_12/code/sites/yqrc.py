# -*- coding: utf-8 -*-
"""
站点配置：乐清人才网（www.yqrc.com）双休职位列表

列表：https://www.yqrc.com/job?welfare=5&page=N
      welfare=5 = 双休标签；salary=1..11 = 薪资档；jobarea1=330382xx = 乡镇街道
      实测：?welfare=5 共 11 页，每页 20 条（约 220 条）

robots.txt：内容为 "User-agent: *\\nDisallow:"（规则为空 = 全部允许）

列表卡片 div.jobs-item 已包含判断三条件所需的全部字段（职位名/地区/学历/
经验/薪资/时间/公司/福利标签），因此【不抓详情页】，列表级即可完成筛选。

字段位置（勘察实测，2026-11-10）：
    div.jobs-item__main__title__name[title]          职位名
    a.jobs-item__main__title[href]                   详情链接 jobinfo_*.html
    .jobs-item__main__attribute__item--region span   地区（可多个，顿号分隔）
    .jobs-item__main__attribute__item（非 region）     依次为 学历 / 经验
    .jobs-item__salary__label                        薪资原文（如 9K~1.5万元/月）
    .jobs-item__salary__time                         发布时间（如 2小时前）
    a.jobs-item__company__name__label[title]         公司名
    .jobs-item__company__welfare span[title]         福利标签
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ._common import TOTAL_PAGES_PATTERN

BASE = "https://www.yqrc.com"
WELFARE_DOUBLE_WEEKEND = 5

CONFIG = {
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "yqrc",
    "url_template": BASE + "/job?welfare=5&page={page}",
    "paginate": "number",
    "page_start": 1,
    "page_end": 11,

    "delay_min": 1.2,
    "delay_max": 2.5,
    "timeout": 25,
    "retries": 2,
    "backoff": 2.0,

    "respect_robots": True,
    # v14.5：published 常见"30分钟前"这种相对时间，会随抓取时刻变；
    # 它不属于内容变化，排除出 content_hash（P1 会补 published_at 绝对时间）
    "hash_exclude": ["published"],
    "dedup_key": "detail_url",
    # 页面里 <span>1</span>/M页 → 声明总页数（读不到就按配置跑）
    "total_pages_pattern": TOTAL_PAGES_PATTERN,   # 唯一副本见 _common.py

    "detail": {"enabled": False},
    "attachments": {"enabled": False},

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def _attr_text(card):
    """返回卡片里非 region 的属性文本列表：[学历, 经验]"""
    out = []
    for item in card.select(".jobs-item__main__attribute__item"):
        cls = item.get("class") or []
        if any("region" in c for c in cls):
            continue
        for sp in item.select("span"):
            sp_cls = sp.get("class") or []
            if any("split-line" in c for c in sp_cls):
                continue
            t = sp.get_text(strip=True)
            if t:
                out.append(t)
    return out


def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for card in soup.select("div.jobs-item"):
        a = card.select_one("a.jobs-item__main__title")
        if not a or not a.get("href"):
            continue
        detail_url = urljoin(page_url, a["href"])

        name_el = card.select_one(".jobs-item__main__title__name")
        title = ""
        if name_el is not None:
            title = (name_el.get("title") or name_el.get_text(strip=True) or "").strip()
        if not title:
            title = a.get_text(strip=True)

        region = ""
        region_el = card.select_one(".jobs-item__main__attribute__item--region")
        if region_el is not None:
            sp = region_el.select_one("span")
            target = sp if sp is not None else region_el
            region = (target.get("title") or target.get_text(strip=True) or "").strip()

        attrs = _attr_text(card)
        edu_req = attrs[0] if len(attrs) >= 1 else ""
        exp_req = attrs[1] if len(attrs) >= 2 else ""

        sal_el = card.select_one(".jobs-item__salary__label")
        salary = sal_el.get_text(strip=True) if sal_el is not None else ""
        time_el = card.select_one(".jobs-item__salary__time")
        published = time_el.get_text(strip=True) if time_el is not None else ""


        com_el = card.select_one("a.jobs-item__company__name__label")
        company = ""
        if com_el is not None:
            company = (com_el.get("title") or com_el.get_text(strip=True) or "").strip()

        welfare = []
        for sp in card.select(".jobs-item__company__welfare span"):
            t = (sp.get("title") or sp.get_text(strip=True) or "").strip()
            if t:
                welfare.append(t)

        rows.append({
            "title": title,
            "company": company,
            "salary_raw": salary,
            "region": region,
            "edu_req": edu_req,
            "exp_req": exp_req,
            "published": published,
            "welfare": "|".join(welfare),
            "source_site": "乐清人才网",
            "detail_url": detail_url,
        })
    return rows