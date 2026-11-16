# -*- coding: utf-8 -*-
"""吉林人才网 —— 吉林省人才市场官方站（省级公共就业平台）

站点形态（2026-11-15 实测，5 个请求摸清）：
    列表页 wwbc_result.html 是**空壳**（78 KB 但 0 个岗位链接），
    真实数据来自明文 JSON 接口：
        GET https://hr.jlrc.com.cn/api/admin/sysEnt/getAllPortalJobPage
            ?jobName=&entName=&size=50&current=1
        → {"code":0,"data":{"records":[...19 字段...],"total":4684,"pages":94}}

为什么这里用 response="html" 而不是 "json"：
    岗位名**不在任何字段里**。站方把"行业_大类,中类,岗位名+32位hash.png"
    塞进 jobQrcode（一个 OSS 图片地址）的文件名，前端 JS 用 substring 现切。
    jobName 字段是职位分类编码（如 "463,464,473"），不是岗位名。
    引擎的 field_map 只能直接取值、没有 transform 钩子，所以这里自己吃 JSON 字符串再剥离。
    代价：引擎的 json_total 校验用不上（那是 json 模式才有），改为自己实现 parse_total_pages。

robots（2026-11-15）：
    www.jlrc.com.cn/robots.txt → 404（对象存储 NoSuchKey）→ 按项目规则视为未设限
    hr.jlrc.com.cn/robots.txt  → 404（nginx）→ 同上

已知数据质量问题（不要当"干净源"用）：
    · 4,684 条里混着外省岗位（抽样见 辽宁沈阳、安徽芜湖）
    · 大量「薪资不限 / 学历无要求 / jobDesc 是模板话术」
    · 所以必须按 workLocationName 过一遍地理过滤，别整库交付

Rule 0：官方公共就业平台的公开岗位页，人工确认可访问（terms_status=allowed）。
"""

import json
import re
from urllib.parse import unquote

API = "https://hr.jlrc.com.cn/api/admin/sysEnt/getAllPortalJobPage"
SITE = "https://www.jlrc.com.cn"
PAGE_SIZE = 50          # 站方 pagesize 固定 10，接口支持自定义（实测 50 有效，pages=94）
HASH_TAIL = re.compile(r"[0-9a-fA-F]{32}\.\w+$")

CONFIG = {
    "terms_status": "allowed",
    "job": "jlrc",
    "response": "html",            # ← 见文件头：要在 parse_list 里剥离岗位名
    "url_template": API + "?jobName=&entName=&size=%d&current={page}" % PAGE_SIZE,
    "paginate": "number",
    "page_start": 1,
    "page_end": 20,                # 安全上限；真实页数由 parse_total_pages 给的 M 夹紧
    "page_size": PAGE_SIZE,

    "delay_min": 3.0,
    "delay_max": 5.0,
    "timeout": 25,
    "retries": 1,
    "backoff": 2.0,

    "respect_robots": True,
    # 岗位分类编码会随"职位表刷新"整体重排，但它不是内容；不排除会导致 hash 全变
    "hash_exclude": ["job_code"],

    # 一条 API 记录一个唯一 id；detail_url 是拼出来的展示页，站方并不提供稳定详情页，
    # 所以去重键用原始 id（source_api_id），不用 detail_url（拼的 URL 可能失效）。
    "dedup_key": "source_api_id",

    "detail": {"enabled": False},
    "attachments": {"enabled": False},

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def _job_name(qr):
    """从 jobQrcode 的文件名里剥出岗位名。

    形如 .../nolog?fileName=房地产_建筑,工程管理,建筑施工项目经理<32位hash>.png
    → 取最后一段，去掉末尾的 hash + 扩展名。
    """
    if not qr or "fileName=" not in qr:
        return ""
    tail = unquote(qr.split("fileName=", 1)[1])
    parts = [p.strip() for p in tail.split(",") if p.strip()]
    if not parts:
        return ""
    last = parts[-1]
    last = HASH_TAIL.sub("", last)
    # 没有 hash 尾巴时，至少去掉图片扩展名
    if last.lower().endswith((".png", ".jpg", ".jpeg")):
        last = last.rsplit(".", 1)[0]
    return last.strip()


def _parse(payload):
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    try:
        return json.loads(payload)
    except Exception:
        return None


def parse_list(payload, page_url):
    """把一页 JSON 摊成记录。解析失败返回 []（引擎会记"空页/解析异常"）。"""
    j = _parse(payload)
    if not j or not isinstance(j, dict):
        return []
    data = j.get("data") or {}
    recs = data.get("records") or []
    rows = []
    for x in recs:
        if not isinstance(x, dict):
            continue
        rid = str(x.get("id") or "").strip()
        rows.append({
            "title": _job_name(x.get("jobQrcode")),          # 岗位名（从 OSS 文件名剥）
            "company": (x.get("entName") or "").strip(),
            "salary": (x.get("salaryRangeName") or "").strip(),
            "education": (x.get("educationName") or "").strip(),
            "major": (x.get("major") or "").strip(),
            "location": (x.get("workLocationName") or "").strip(),
            "treatment": (x.get("jobTreatment") or "").strip(),
            "headcount": x.get("employQuantity"),
            "desc": (x.get("jobDesc") or "").strip()[:500],
            "job_code": (x.get("jobName") or "").strip(),     # 职位分类编码，不是岗位名
            "ent_id": str(x.get("entId") or ""),
            "uniscid": (x.get("uniscid") or "").strip(),
            "qrcode_url": (x.get("jobQrcode") or "").strip(),
            "source_api_id": rid,
            "detail_url": "",                                 # 站方无稳定详情页，留空不造假
        })
    return rows


def parse_total_pages(html, page_url):
    """从接口的 total 算总页数（引擎按 (html, page_url) 两参调用）。

    total=4684 / size=50 → 94 页。取不到就返回 None（引擎按配置页数跑）。
    """
    j = _parse(html)
    if not j or not isinstance(j, dict):
        return None
    data = j.get("data") or {}
    try:
        total = int(data.get("total") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)