# -*- coding: utf-8 -*-
"""
苍南人才网（cangnanrc.com）—— **只抓首页 SSR**（方案 A）。

为什么只抓首页：
  · robots 的 `User-agent: *` 段禁了 `/*.js*`，而列表页 /job.shtml 是 1,139 字节 JS 空壳
    → 翻页必然加载 JS，属踩线；首页是服务端直出，不在任何 Disallow 里。
  · robots 还点名禁 `Python-requests`（引擎用的库），所以能抓的面越小越好。

首页实际有两块职位数据（都已结构化验证）：
  A) `li.jobList` × 40 家公司 → 99 个岗位，**只有 岗位名 + 公司名**，没有薪资/地区/学历
  B) `ul.bangongshiJob li.card` × 8 → **字段齐全**：岗位 / 薪资 / 福利标签 / 公司 / 地区 / 经验 / 学历

所以这份数据的定位：
  · B 块可以直接进筛选（有薪资、有福利标签，`周末双休` 这种标签能被 weekend_state 识别）
  · A 块只能当"线索表"——要薪资得逐条开 /job{id}.shtml 详情页（另算成本）
  用 record_type 字段把两者分开，避免后续把"无线索表"误当"可筛数据"。
"""

import re
import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1]))
from identity import UA as _IDENTITY_UA  # noqa: E402  ← 唯一身份源


from bs4 import BeautifulSoup
from urllib.parse import urljoin

CONFIG = {
    # Rule 0（v14）：条款已人工确认；该站只抓首页 SSR（robots 禁 /*.js*，列表页是 JS 空壳）
    "terms_status": "allowed",
    "platform": "jrzp",
    "name": "cangnan_home",
    "base_url": "https://www.cangnanrc.com/",
    "url_template": "https://www.cangnanrc.com/",
    "paginate": "number",
    "page_start": 1,
    "page_end": 1,                                   # 首页只有一页
    "response": "html",
    "delay_min": 3.0,
    "delay_max": 5.0,
    "timeout": 20,
    "retries": 1,
    "respect_robots": True,
    "dedup_key": "detail_url",
    "ua": _IDENTITY_UA,
    "out_dir": r"D:\agent-work\data\raw",
    "state_dir": r"D:\agent-work\manifests",
    "log_dir": r"D:\agent-work\logs",
    "report_dir": r"D:\agent-work\out\reports",
}


def _row(**kw):
    base = {
        "title": "", "company": "", "company_url": "",
        "salary_raw": "", "region": "", "edu_req": "", "exp_req": "",
        "published": "", "welfare": "", "record_type": "",
        "source_site": "苍南人才网(jrzp城市站)",
        "detail_url": "",
    }
    base.update(kw)
    return base


def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []

    # ---------- B 块：字段齐全的「最新职位」
    for li in soup.select("ul.bangongshiJob li.card"):
        a = li.select_one(".contentTop .left a.position")
        if not a or not a.get("href"):
            continue
        title = (a.get("title") or a.get_text(strip=True) or "").strip()
        sal_el = li.select_one(".contentTop .left p")
        salary = sal_el.get_text(strip=True) if sal_el else ""
        fuli = [x.get_text(strip=True) for x in li.select("ul.fuli span.ts") if x.get_text(strip=True)]
        com_a = li.select_one(".contentButtom a.right")
        company = (com_a.get("title") or com_a.get_text(strip=True) or "").strip() if com_a else ""
        company = re.sub(r"\s+", "", company)
        company_url = urljoin(page_url, com_a["href"]) if com_a and com_a.get("href") else ""

        region = exp = edu = ""
        p = li.select_one(".contentButtom p.left")
        if p is not None:
            parts = [x.strip() for x in p.get_text("|", strip=True).split("|") if x.strip() and x.strip() != "|"]
            parts = [x for x in parts if x != "|"]
            if parts:
                region = parts[0]
            if len(parts) >= 2:
                exp = parts[1]
            if len(parts) >= 3:
                edu = parts[2]

        rows.append(_row(
            title=title, company=company, company_url=company_url,
            salary_raw=salary, region=region, edu_req=edu, exp_req=exp,
            welfare="|".join(fuli), record_type="最新职位(字段齐全)",
            detail_url=urljoin(page_url, a["href"]),
        ))

    # ---------- A 块：只有 岗位名 + 公司名的「热招职位」
    for li in soup.select("li.jobList"):
        com_a = li.select_one("p a[title]")
        company = (com_a.get("title") or com_a.get_text(strip=True) or "").strip() if com_a else ""
        company_url = urljoin(page_url, com_a["href"]) if com_a and com_a.get("href") else ""
        for a in li.select("a.zaizhaoZhiwei"):
            href = a.get("href") or ""
            if "/job" not in href:
                continue
            title = (a.get("title") or a.get_text(strip=True) or "").strip()
            if not title:
                continue
            rows.append(_row(
                title=title, company=company, company_url=company_url,
                record_type="热招职位(无薪资字段)",
                detail_url=urljoin(page_url, href),
            ))

    # 同一 detail_url 只留字段更全的那条
    best = {}
    for r in rows:
        k = r["detail_url"]
        cur = best.get(k)
        if cur is None:
            best[k] = r
        else:
            score = lambda x: sum(1 for f in ("salary_raw", "region", "edu_req", "exp_req", "welfare") if x[f])
            if score(r) > score(cur):
                best[k] = r
    return list(best.values())


def parse_total_pages(html, page_url=None):
    """首页只有一页：显式返回 1。

    注意签名必须是 (html, page_url) —— 引擎是按两参调用的
    （declared_total_pages: site_mod.parse_total_pages(payload, page_url)），
    只写一个参数会抛 TypeError，被吞掉后变成「读不到总页数」的 anomaly。
    """
    return 1