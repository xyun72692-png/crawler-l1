# ⚠️ 实测结论（2026-11-14）：**本通道当前不可用，勿在生产启用。**
#    用 render_batch + 本模块跑 chinahzrc 列表页：导航 200，但页面随即把自身刷成 about:blank
#    （console.clear + 自毁），html 只剩 39 字节；headless 与 headed 两条通道都一样
#    → 属站点反自动化，按 Rule 0 红线**不升级对抗**，只保留代码与结论备查。
#    可用的仍是「首页 SSR 热门块」（见 sites/cangnan_home.py）。
# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[2])

"""jrzp 系列表页（SPA）—— **仅渲染列表层**，拿到 detail URL 就停。

为什么需要这条通道（v13 实测结论）：
  · 首页是 SSR（能抓，但只有 ~100 条热门块）
  · 列表页 /job.shtml 是 1,195 字节空壳，数据由 JS + /zpapi/api 拉取
  · 该接口带 AES/HMAC 签名 → **不逆向**（红线）
  → 唯一合规路径：用真浏览器渲染"列表这一层"，只取岗位链接；详情与附件回 plain

Rule 0：
  · terms_status = allowed（人工确认：公开岗位页允许访问）
  · robots 写了 `Disallow: /*.js*`，而渲染必须加载 JS
    → 走**点对点授权例外**（render_authorized），只在 `--allow-robots-js` 时生效，
      每次任务 ≤20 页，报告留痕 robots_override/scope/authorized_by/authorized_at
  · 不碰简历栏目、不碰签名接口
"""

from bs4 import BeautifulSoup

BASE = "https://www.chinahzrc.com"

CONFIG = {
    # Rule 0
    "terms_status": "allowed",
    "platform": "jrzp",
    "render_authorized": {"by": "user", "at": "2026-11-14", "max_pages": 20},

    "job": "jrzp_list",
    "url_template": BASE + "/job.shtml?page={page}",
    "paginate": "number",
    "page_start": 1,
    "page_end": 1,
    "delay_min": 3.0,
    "delay_max": 5.0,
    "timeout": 30,
    "retries": 1,
    "respect_robots": True,          # 列表页本身仍按 robots 判；JS 子资源走授权例外
    "dedup_key": "detail_url",

    # 渲染口径
    "render_ready_selector": "a[href*='/job']",
    "render_settle_ms": 800,

    "detail": {"enabled": False},
    "attachments": {"enabled": False},
    "out_dir": str(_HOME / "data" / "raw"),
    "log_dir": str(_HOME / "logs"),
    "state_dir": str(_HOME / "manifests"),
    "report_dir": str(_HOME / "out" / "reports"),
}


def parse_list(html, page_url=None):
    """渲染后 DOM 里取岗位：标题 + detail_url（最薄一层，不进详情）。"""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/job" not in href or not href.rstrip("/").endswith((".shtml", ".html")):
            continue
        title = a.get_text(" ", strip=True)
        if not (2 <= len(title) <= 40):
            continue
        url = href if href.startswith("http") else BASE + href
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "detail_url": url, "source": "jrzp_render"})
    return out