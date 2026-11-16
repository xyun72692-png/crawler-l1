# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""
站点配置：食品伙伴网 法规中心（手机版）国家法规列表

列表：https://law.foodmate.net/mobile/index.php?moduleid=23&catid=39&page=N
详情：https://law.foodmate.net/mobile/index.php?moduleid=23&itemid=XXXXXX

⚠ 关键约束（勘察时实测）：
    详情页必须【先访问过列表页、拿到 cookie u_mobile】才能打开。
    用全新 Session 直接请求详情页会挂起，25 秒 / 45 秒都超时；
    先请求一次列表页后，同一个 Session 里详情页 0.8 秒返回。
    所以 detail_hook 必须复用主引擎的 sess（它已经访问过列表页）。

⚠ robots.txt：
    Disallow: /api/ /install/ /member/ /skin/ /template/ /upgrade/ /*search*
    本模块只请求 /mobile/index.php?moduleid=23... 和详情页，均在允许范围内。
    有效性状态是 /skin/ 下的图片，被 robots 禁止，所以【不下载图片】，
    只取文件名做映射。

有效性状态图片映射（基于 40 条样本统计，与下方 STATUS_MAP 一致）：
    xxyx.gif  现行有效     —— 30 条；生效日期全部 ≤ 今天（发布=生效 25 条）
    jjss.gif  即将实施     —— 5 条；生效日期全部 > 今天
    jdxwj.gif 现行有效     —— 5 条；发布=生效 5/5、废止日期全为「暂无」、
                            属性 5/5 都是「计划规划」
                            数据层面就是现行有效；图标文字本身没亲眼确认过
                            （/skin/ 被 robots 禁止下载），所以 status_confirmed=False

⚠ 状态映射有两处，别搞混：
    1) 抓取时：parse_detail() 按上面的 STATUS_MAP 写一份快照进 jsonl
       （valid_status / status_confirmed）
    2) 导出时：clean.py 的 enrich_status() 再按同一份 STATUS_MAP 重算，
       并额外给一个只看日期的 status_derived
    最终 xlsx/csv 以 clean.py 的结果为准；jsonl 里那份是"抓取当时的快照"，
    保留它才能事后看出"当时是怎么判断的、后来规则有没有改过"。
"""

import random
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

SITE = "https://law.foodmate.net"
LIST_PAGE = SITE + "/mobile/index.php?moduleid=23&catid=39"
TZ = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")

CONFIG = {
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "foodlaw",
    "url_template": SITE + "/mobile/index.php?moduleid=23&catid=39&page={page}",
    "page_start": 1,
    "page_end": 1,          # 先用 page=1（20 条）验收，通过再改 2

    "delay_min": 0.8,
    "delay_max": 1.5,
    "timeout": 25,
    "retries": 2,
    "backoff": 2.0,

    "respect_robots": True,
    # v14.4：TLS 指纹对齐（A/B 已验证结果一致：foodmate 200/200、wzrc 46/46、foodlaw 20/20）
    "transport": "cffi",
    "dedup_key": "detail_url",

    # 详情阶段（阶段1 通用化后的配置；引擎负责流程，这里只声明参数）
    "detail": {
        "enabled": True,
        "delay_min": 0.8,
        "delay_max": 1.5,
        "timeout": 25,
        "retries": 2,
        "backoff": 2.0,
        "abort_on": [401, 403, 429, 451],
        "max_fail_ratio": 0.5,
        "required": ["publish_date", "status_img"],
        "respect_robots": True,
    },
    # 附件下载（阶段4 接入）：foodlaw 的附件在正文里，常跨域到 file*.foodmate.net
    "attachments": {
        "enabled": True,
        "dir": str(_HOME / "data" / "attachments"),
        "max_files_per_record": 5,
        "max_file_bytes": 50 * 1024 * 1024,
        "max_total_bytes": 500 * 1024 * 1024,
        "timeout": 60,
        "retries": 2,
        "respect_robots": True,
        "check_dns": True,
        "allow_private_hosts": False,
        # 生产站点显式收紧：只收文档类扩展名 + 校验文件头，
        # 不依赖"默认黑名单"（黑名单永远漏）
        "ext_allow": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"],
        "sniff_magic": True,
        "delay_min": 1.0,
        "delay_max": 2.0,
    },

    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}

# 图片文件名 -> (中文状态, 是否已确认)
#
# 判定依据（40 条样本统计）：
#   xxyx.gif  30 条：发布=生效 25 条；生效日期全部 ≤ 今天；属性分散（通告公告/法律/行政法规/通知/意见/议案）
#            → 现行有效
#   jjss.gif   5 条：发布=生效 0 条；生效日期全部 > 今天
#            → 即将实施
#   jdxwj.gif  5 条：发布=生效 5/5；生效日期全部 ≤ 今天；废止日期全部「暂无」；属性 5/5 全是「计划规划」
#            → 数据层面就是「现行有效」。图标与 xxyx 不同、且高度绑定「计划规划」属性，
#              推测是站方给计划规划类文件用的专用图标。
#              图标文字本身没亲眼确认（/skin/ 被 robots 禁），所以 confirmed=False。
STATUS_MAP = {
    "xxyx.gif": ("现行有效", True),
    "jjss.gif": ("即将实施", True),
    "jdxwj.gif": ("现行有效", False),
}
STATUS_DEFAULT = ("未知", False)


# =====================================================================
# 列表页解析
# =====================================================================
def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "moduleid=23" not in href or "itemid=" not in href:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue

        li = a.find_parent("li")
        short_date = ""
        if li:
            sp = li.find("span")
            if sp:
                short_date = sp.get_text(strip=True)

        rows.append({
            "title": title,
            "detail_url": urljoin(page_url, href),
            "list_date": short_date,      # 只有 MM-DD，仅供核对，不作为发布日期
        })

    return rows


# =====================================================================
# 详情页解析
# =====================================================================
def parse_detail(html):
    """
    详情页字段都是 <div><b>标签：</b>值</div> 的固定结构。
    有效性状态是 <img class="bz_xxzt" src=".../xxyx.gif">。

    约定（阶段1 通用化）：这个函数是【纯解析】，不发请求、不 sleep、不管状态码。
    引擎会负责那些。返回的 dict 里键名就是最终字段名，唯独 "title" 会被引擎
    写成 detail_title（避免覆盖列表页标题）。

    valid_status / status_confirmed 也在这里算 —— 它只依赖 status_img 和本模块的
    STATUS_MAP，不需要网络，所以属于"解析"的一部分，引擎不需要认识这些业务词。
    """
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.select_one("h1")
    title = h1.get_text(strip=True) if h1 else ""
    if not title and soup.title:
        title = soup.title.get_text(strip=True).split("_政策法规")[0]

    content = soup.select_one("div.content") or soup
    fields = {}
    for div in content.find_all("div", recursive=False):
        b = div.find("b")
        if not b:
            continue
        label = b.get_text(strip=True).rstrip("：:").strip()
        val = div.get_text(" ", strip=True).replace(b.get_text(strip=True), "", 1).strip()
        fields[label] = val

    img = content.select_one("img.bz_xxzt")
    status_img = ""
    if img and img.get("src"):
        status_img = img["src"].rsplit("/", 1)[-1]

    # 附件：正文里指向真实文件的链接（pdf/doc/xls/zip...）。
    # 注意 /rule/down.php?itemid=xxx 那种是"下载计数页"不是文件本身，不收。
    ATT_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")
    attachments = []
    for a in content.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower().split("?")[0]
        if not low.startswith(("http://", "https://")):
            continue
        if not low.endswith(ATT_EXT):
            continue
        url_name = low.rsplit("/", 1)[-1]
        text = a.get_text(strip=True)
        # 链接文字常常只是"附件："这类，看不出是什么文件 → 用 URL 里的真实文件名
        name = text if (text and text.lower().endswith(ATT_EXT)) else url_name
        if any(x["url"] == href for x in attachments):
            continue
        attachments.append({"url": href, "name": name})

    status_text, confirmed = STATUS_MAP.get(status_img, STATUS_DEFAULT)

    return {
        "title": title,
        "publish_date": fields.get("发布日期", ""),
        "status_img": status_img,
        "effective_date": fields.get("生效日期", ""),
        "abolish_date": fields.get("废止日期", ""),
        "issuer": fields.get("发布单位", ""),
        "doc_no": fields.get("发布文号", ""),
        "attr": fields.get("属性", ""),
        "valid_status": status_text,
        "status_confirmed": confirmed,
        "attachments": attachments,
    }


# =====================================================================
# detail_hook 已删除（2026-11-10 阶段1 验收通过）
#
# 原来这里有一段 100 行的 detail_hook：自己限速、自己请求、自己判状态码、
# 自己记时间戳。它和 foodlaw 的业务字段混在一起，换站要整段复制，而且
# 没有重试、没有 robots 检查。
#
# 现在这些全部由 crawler.py 的 crawl_details_generic() 负责，本文件只留
# parse_detail()（纯解析）。
#
# 删之前做过两道验收：
#   1) tests/compare_detail_paths.py：真站 40 条 × 13 字段，新旧零差异
#   2) tests/test_parse_detail_offline.py：离线 HTML 逐字段一致
# 旧实现完整保存在 crawlers/_baseline_v1/code/sites/foodlaw.py，需要对照可查。
# =====================================================================
