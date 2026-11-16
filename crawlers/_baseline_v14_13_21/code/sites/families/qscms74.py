# -*- coding: utf-8 -*-
"""站点模块家族：74cms（骑士人才系统）系列表页通用解析。

适用：wzrc_all / wzrc_inc / yqwzrc / yqwzrc_wage（同一套卡片结构）。

两处差异用参数表达，不复制解析器：
    keep_area=True   保留「地区 | 」前缀到 area_in_title，region 回退到它（wzrc 系）
    keep_area=False  剥离前缀后丢弃（乐清分站）
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_AREA_RE = re.compile(r"^\s*([^\s|｜]{1,8})\s*[|｜]\s*(.+)$")
_PREFIX_RE = re.compile(r"^[^|｜]{1,8}\s*[|｜]\s*")


def _pick(fields, key):
    return (fields.get(key) or "").strip()


def parse_jobs(html, page_url, source_site, keep_area=False):
    """解析 74cms 列表页，返回记录列表（字段顺序与旧实现一致）。"""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for card in soup.select("div.J_jobsList"):
        a = card.select_one(".td-j-name a")
        if not a or not a.get("href"):
            continue
        detail_url = urljoin(page_url, a["href"])

        raw_title = (a.get("title") or a.get_text(strip=True) or "").strip()
        area_in_title = ""
        title = raw_title
        if keep_area:
            m = _AREA_RE.match(raw_title)
            if m:
                area_in_title = m.group(1)
                title = m.group(2).strip()
        else:
            title = _PREFIX_RE.sub("", raw_title).strip()

        com_el = card.select_one(".td3 a")
        company = ""
        if com_el is not None:
            company = (com_el.get("title") or com_el.get_text(strip=True) or "").strip()

        sal_el = card.select_one(".td4")
        salary = sal_el.get_text(strip=True) if sal_el is not None else ""
        time_el = card.select_one(".td5")
        published = time_el.get_text(strip=True) if time_el is not None else ""

        fields = {}
        txt_el = card.select_one(".ltx .txt")
        if txt_el is not None:
            for seg in txt_el.get_text("|", strip=True).split("|"):
                seg = seg.strip()
                if "：" in seg or ":" in seg:
                    k, v = re.split(r"[:：]", seg, maxsplit=1)
                    fields[k.strip()] = v.strip()

        welfare = [dl.get_text(strip=True) for dl in card.select(".dlabs .dl")
                   if dl.get_text(strip=True)]

        row = {"title": title}
        if keep_area:
            row["area_in_title"] = area_in_title
        row.update({
            "company": company,
            "salary_raw": salary,
            "region": _pick(fields, "地点") or (area_in_title if keep_area else ""),
            "edu_req": _pick(fields, "学历"),
            "exp_req": _pick(fields, "经验"),
            "headcount": _pick(fields, "人数"),
            "job_nature": _pick(fields, "职位性质"),
            "published": published,
            "welfare": "|".join(welfare),
            "source_site": source_site,
            "detail_url": detail_url,
        })
        rows.append(row)
    return rows
