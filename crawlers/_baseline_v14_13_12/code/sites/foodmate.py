# -*- coding: utf-8 -*-
"""
食品伙伴网 · 食品人才中心（foodmate.cn）—— DESTOON B2B 模板。

关键事实（都实测过，别改）：
  · robots: `# Robots For DESTOON B2B`，**Disallow: /*search*** → 地区/筛选**只能本地做**
  · 编码: **GB2312/GBK**（UTF-8 读会乱码；引擎会走 apparent_encoding = GB2312）
  · 列表页: /job/index-htm-page-N.html，**每页 20 条**（20 个不同 show-id）
  · 列表项自带：标题 / 城市 / 经验 / 学历 / 薪资 / 公司 / 性质 / 规模 → **不必进详情**
  · 规模：245 页 × 20 ≈ 4,900 条

卡片结构：
  div.search_job_list > div.jobshow
    ├ a.yunjoblist_newname_a            （标题 + show-N.html）
    ├ div.yunjoblist_newxz              （薪资）
    ├ div.search_job_left_siaber
    │   └ div.company_det_city em.com_search_job_em a  ×3  （城市 / 经验 / 学历）
    └ div.company_det_c_name
        ├ a.search_job_com_name         （公司，title 属性是全名）
        └ div.company_det_city          （性质 | 规模）
"""

import re
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1]))
from identity import UA as _IDENTITY_UA  # noqa: E402  ← 唯一身份源


from bs4 import BeautifulSoup
from urllib.parse import urljoin

CONFIG = {
    "name": "foodmate",
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "foodmate",
    "base_url": "https://www.foodmate.cn/job/",
    "url_template": "https://www.foodmate.cn/job/index-htm-page-{page}.html",
    "paginate": "number",
    "page_start": 1,
    "page_end": 1,                 # 试跑 1 页；全量请显式 --pages（245）
    "response": "html",
    "delay_min": 3.0,
    "delay_max": 5.0,
    "timeout": 25,
    "retries": 1,
    "respect_robots": True,
    # v14.4：TLS 指纹对齐（A/B 已验证结果一致：foodmate 200/200、wzrc 46/46、foodlaw 20/20）
    "transport": "cffi",
    "dedup_key": "detail_url",
    "ua": _IDENTITY_UA,
    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
    # 详情：列表已含四列，详情只按需（两段式）补 JD
    "detail": {"enabled": False},
    "attachments": {"enabled": False},
}


def parse_total_pages(html, page_url=None):
    """从分页链接里取最大页码（`index-htm-page-245.html`）→ 245。"""
    nums = [int(x) for x in re.findall(r"index-htm-page-(\d+)\.html", html or "")]
    return max(nums) if nums else None


def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for card in soup.select("div.search_job_list > div.jobshow"):
        a = card.select_one("a.yunjoblist_newname_a")
        if not a or not a.get("href"):
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue

        sal_el = card.select_one("div.yunjoblist_newxz")
        salary = sal_el.get_text(" ", strip=True) if sal_el else ""

        # 城市 / 经验 / 学历：第一个 company_det_city 里的 3 个 em>a
        region = exp = edu = ""
        left = card.select_one("div.search_job_left_siaber")
        if left is not None:
            metas = [x.get_text(strip=True) for x in left.select("div.company_det_city em a")]
            if len(metas) >= 1:
                region = metas[0]
            if len(metas) >= 2:
                exp = metas[1]
            if len(metas) >= 3:
                edu = metas[2]

        com_a = card.select_one("a.search_job_com_name")
        company = ""
        company_url = ""
        if com_a is not None:
            company = (com_a.get("title") or com_a.get_text(strip=True) or "").strip()
            company_url = urljoin(page_url, com_a.get("href") or "")

        nature = headcount = ""
        cname = card.select_one("div.company_det_c_name div.company_det_city")
        if cname is not None:
            parts = [x.strip() for x in cname.get_text("|", strip=True).split("|") if x.strip()]
            parts = [x for x in parts if x != "|"]
            if parts:
                nature = parts[0]
            if len(parts) >= 2:
                headcount = parts[-1]

        rows.append({
            "title": title,
            "salary_raw": salary,
            "region": region,
            "exp_req": exp,
            "edu_req": edu,
            "company": company,
            "company_url": company_url,
            "job_nature": nature,
            "headcount": headcount,
            "published": "",              # 列表页不提供发布时间
            "welfare": "",                # 列表页不提供福利标签
            "source_site": "食品伙伴网·食品人才中心",
            "detail_url": urljoin(page_url, a["href"]),
        })

    # 同页去重（同一 show-id 可能被多链接指向）
    seen, out = set(), []
    for r in rows:
        if r["detail_url"] in seen:
            continue
        seen.add(r["detail_url"])
        out.append(r)
    return out