#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T2 批量渲染工具（v14 阶段 2）。

定位：**只渲染"列表层"**——拿到 detail URL 就停；详情与附件回 plain 通道。

口径（与方案 §4.0 一致，写死）：
  · 导航（page.goto）计入 gate：1 次 = 1；子资源**不计入** 12 次/分与 200 预算
  · 但另有双上限：单页子资源 ≤80（超了记 anomaly 并停该站）、整任务累计 ≤4000
  · 默认拦 image/font/media（不拦 CSS/JS——CSS 影响可见性判断）
  · Rule 0 先行：terms_status 必须 allowed；robots 禁 JS 时只有拿到点对点授权才放行
  · 浏览器**一次启动 N 次导航**（不是 100 页启 100 次）
  · 落盘：渲染后的 HTML 存 data/raw/_rendered/<job>/pN.html，记录写 data/raw/<job>.jsonl
  · 报告：复用 crawler.write_report，格式与引擎一致（能喂 doctor）

用法：
    python tools/render_batch.py --site jrzp_list --pages 1 --allow-robots-js
    python tools/render_batch.py --site mockrender --pages 2 --headed
"""

import argparse
import importlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "crawlers"))
sys.dont_write_bytecode = True

import crawler          # noqa: E402  复用 Logger / write_report / content_hash
import gate as gate_mod  # noqa: E402
import identity         # noqa: E402
import robots_rules     # noqa: E402
import rule0            # noqa: E402
import stealth          # noqa: E402

MAX_SUB_PER_PAGE = 80
MAX_SUB_TOTAL = 4000
BLOCK_TYPES = ("image", "font", "media")


# --------------------------------------------------------------------------- #
# 浏览器
# --------------------------------------------------------------------------- #
def launch_browser(pw, headed=False):
    for ch in ("chrome", "msedge", None):
        try:
            b = pw.chromium.launch(**stealth.launch_kwargs(channel=ch, headless=not headed))
            return b, (ch or "bundled")
        except Exception:
            continue
    raise RuntimeError("没有可用的浏览器通道（chrome / msedge / bundled）")


class PageMeter:
    """统计一次导航的子资源数量（不计入 gate 预算，但有硬上限）。"""

    def __init__(self, page):
        self.total = 0
        self.per_page = 0
        page.on("request", self._on_req)

    def _on_req(self, req):
        if req.is_navigation_request():
            return
        self.total += 1
        self.per_page += 1

    def reset_page(self):
        self.per_page = 0



_ROBOTS_CACHE = {}


def robots_allows(url, cfg, log, gate):
    """列表页能不能抓。按 origin 缓存 robots（只取 1 次）。

    2026-11-15：与 crawler.load_robots 对齐成四态（旧实现把"取不到/解析失败"
    当未设限，结果 403 和 WAF 页都被读成全放行）：
      404=未设限 / 401,403,5xx,异常=拒绝 / 200+HTML=unparsable 拒绝 / 200 正常=按规则
    """
    if not cfg.get("respect_robots", True):
        return True
    parts = urlsplit(url)
    origin = "%s://%s" % (parts.scheme, parts.netloc)
    if origin not in _ROBOTS_CACHE:
        import requests
        try:
            gate.before(parts.hostname or "")
            r = requests.get(origin + "/robots.txt", headers=identity.headers(),
                             timeout=cfg.get("timeout", 20))
            _ROBOTS_CACHE[origin] = (robots_rules.classify_robots(
                r.status_code, r.headers.get("content-type"), r.text or ""), r.text or "")
        except Exception as e:
            _ROBOTS_CACHE[origin] = ("denied", "")
            log("  robots 取不到（%s）→ 视为不允许" % type(e).__name__)
    kind, text = _ROBOTS_CACHE[origin]
    if kind == "absent":
        return True
    if kind == "denied":
        log("  robots 不可读（denied）→ 视为不允许：%s" % url)
        return False
    if kind == "unparsable":
        log("  robots 返回的不是 robots 文本（unparsable）→ 视为不允许：%s" % url)
        return False
    try:
        allowed, rule, line = robots_rules.decide(text, identity.UA, url)
        if not allowed:
            log("  robots 禁止：%s  ← %s（第 %s 行）" % (url, rule, line))
        return bool(allowed)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="T2 批量渲染（列表层）")
    ap.add_argument("--site", required=True, help="crawlers/sites/<name>.py")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--page-from", type=int, default=1, dest="page_from")
    ap.add_argument("--job", default=None)
    ap.add_argument("--allow-robots-js", action="store_true", dest="allow_robots_js")
    ap.add_argument("--terms-status", default=None,
                    choices=["unknown", "allowed", "blocked"],
                    help="Rule 0：临时覆盖站点条款状态")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--block-resources", action="store_true", dest="block_resources",
                    default=True)
    ap.add_argument("--keep-resources", action="store_true",
                    help="不拦图片/字体/媒体（用于必须加载完整资源才能判可见性的站）")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    # ---- 站点配置 ----
    try:
        mod = importlib.import_module("sites." + args.site)
    except ImportError as e:
        print("找不到站点模块 sites/%s.py: %s" % (args.site, e))
        return 1
    # 直接改引擎的 CONFIG（不是复制）：write_report 读的是 crawler.CONFIG，
    # 复制一份会导致报告目录/字段与运行口径不一致。
    CONFIG = crawler.CONFIG
    CONFIG.update(mod.CONFIG)
    if args.job:
        CONFIG["job"] = args.job
    # 目录环境变量覆盖（与引擎同规则）：测试隔离靠这个
    for cfg_key, env_key in (("out_dir", "CRAWLER_OUT_DIR"),
                             ("log_dir", "CRAWLER_LOG_DIR"),
                             ("state_dir", "CRAWLER_STATE_DIR"),
                             ("report_dir", "CRAWLER_REPORT_DIR")):
        v = os.environ.get(env_key)
        if v:
            CONFIG[cfg_key] = v
    job = CONFIG["job"]
    page_start = args.page_from
    page_end = page_start + args.pages - 1

    os.makedirs(CONFIG["out_dir"], exist_ok=True)
    os.makedirs(CONFIG["log_dir"], exist_ok=True)
    os.makedirs(CONFIG["report_dir"], exist_ok=True)
    rendered_dir = Path(CONFIG["out_dir"]) / "_rendered" / job
    rendered_dir.mkdir(parents=True, exist_ok=True)

    log = crawler.Logger(os.path.join(CONFIG["log_dir"], "render-%s.log" % job))
    out_file = os.path.join(CONFIG["out_dir"], "%s.jsonl" % job)

    # ---- Rule 0：条款三态 ----
    terms = rule0.terms_gate(CONFIG, getattr(args, "terms_status", None))
    ov = rule0.build_override(CONFIG, args.allow_robots_js)
    ctx = {
        "job": job, "run_id": "%s-render-%s" % (job, time.strftime("%Y%m%d-%H%M%S")),
        "t_start": time.time(), "t_end": None, "stat": {}, "anomalies": [],
        "per_page": {}, "field_list": [], "out_file": out_file,
        "records_before": 0, "total_in_file": 0, "mode": "render",
        "status": "unknown", "reason": "",
        "terms_status": (CONFIG.get("terms_status") if terms["ok"] else "blocked"),
        **rule0.override_report_fields(ov),
    }
    if not terms["ok"]:
        block = rule0.decision_block(urlsplit(str(CONFIG.get("url_template", ""))).netloc,
                                     terms["signal"], terms["evidence"],
                                     "本次未发出任何请求")
        log(block)
        print(block)
        ctx.update({"status": terms["status"], "reason": terms["reason"], "t_end": time.time()})
        crawler.write_report(ctx)
        return 2

    if args.allow_robots_js and not ov["enabled"]:
        print("Rule 0 例外未生效：%s" % ov.get("why", ""))
    if ov["enabled"]:
        log("Rule 0 例外生效：scope=%s by=%s at=%s max_pages=%d"
            % (ov["scope"], ov["authorized_by"], ov["authorized_at"], ov["max_pages"]))
        page_end = min(page_end, page_start + ov["max_pages"] - 1)

    # ---- 闸门（只数导航）----
    g = gate_mod.build_from_config(CONFIG, log)
    gate_mod.set_gate(g)

    # ---- 逐页 robots（列表页本身）----
    from urllib.parse import urljoin

    seen_keys, rows = set(), []
    stats = ctx["stat"]
    for k in ("navigations", "subresources", "pages_ok", "pages_failed", "records_new"):
        stats[k] = 0

    sub_total = 0
    stop_reason = ""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, channel = launch_browser(pw, headed=args.headed)
        log("浏览器通道：%s ｜ 真实版本：%s" % (channel, browser.version))
        ctx_kwargs = identity.for_playwright_actual(browser.version)
        context = browser.new_context(**ctx_kwargs)
        stealth.prepare_context(context)

        blocked = {"n": 0}
        if not args.keep_resources:
            def _route(route, request):
                if request.resource_type in BLOCK_TYPES:
                    blocked["n"] += 1
                    return route.abort()
                return route.continue_()
            context.route("**/*", _route)

        page = context.new_page()
        meter = PageMeter(page)

        for pno in range(page_start, page_end + 1):
            url = CONFIG["url_template"].format(page=pno)
            # robots：列表页本身是否允许
            if not robots_allows(url, CONFIG, log, g):
                stop_reason = "robots_denied_at_page_%d" % pno
                break
            try:
                g.before(urlsplit(url).hostname or "")
            except Exception as e:
                log("闸门停止：%s" % e)
                stop_reason = "gate_stop_at_page_%d" % pno
                break

            meter.reset_page()
            t0 = time.time()
            try:
                resp = page.goto(url, wait_until="domcontentloaded",
                                 timeout=args.timeout * 1000)
            except Exception as e:
                stats["pages_failed"] = stats.get("pages_failed", 0) + 1
                ctx["anomalies"].append({"page": pno, "anomaly": "goto_failed",
                                          "error": "%s: %s" % (type(e).__name__, str(e)[:160])})
                log("第 %d 页打不开：%s" % (pno, str(e)[:120]))
                stop_reason = "goto_failed_at_page_%d" % pno
                break
            # 给前端一点时间把列表画出来（不无限等）
            try:
                page.wait_for_selector(CONFIG.get("render_ready_selector") or "a", timeout=6000)
            except Exception:
                pass
            page.wait_for_timeout(int(CONFIG.get("render_settle_ms", 400)))
            html = page.content()
            # 站点反自动化：页面把自己刷成 about:blank / 空 DOM（实测常见：console.clear + location 重定向）
            if len(html) < 200 and page.url.startswith("about:"):
                ctx["anomalies"].append({"page": pno, "anomaly": "page_self_destructed",
                                         "final_url": page.url, "bytes": len(html)})
                log("第 %d 页被站点自毁（final=%s，%d 字节）→ 判定反自动化，按红线停，不升级对抗"
                    % (pno, page.url, len(html)))
                stop_reason = "page_self_destructed_at_page_%d" % pno
                break
            (rendered_dir / ("p%d.html" % pno)).write_text(html, encoding="utf-8")

            stats["navigations"] += 1
            sub_total += meter.per_page
            stats["subresources"] = sub_total
            if meter.per_page > MAX_SUB_PER_PAGE:
                ctx["anomalies"].append({"page": pno, "anomaly": "too_many_subresources",
                                         "count": meter.per_page})
                log("第 %d 页子资源 %d > %d → 该站渲染代价过高，停"
                    % (pno, meter.per_page, MAX_SUB_PER_PAGE))
                stop_reason = "too_many_subresources_at_page_%d" % pno
                break
            if sub_total > MAX_SUB_TOTAL:
                log("累计子资源 %d > %d → 停整批" % (sub_total, MAX_SUB_TOTAL))
                stop_reason = "subresource_quota_exceeded"
                break

            try:
                items = mod.parse_list(html, url) or []
            except Exception as e:
                stats["pages_failed"] = stats.get("pages_failed", 0) + 1
                ctx["anomalies"].append({"page": pno, "anomaly": "parse_error",
                                         "error": "%s: %s" % (type(e).__name__, e)})
                log("第 %d 页解析失败：%s" % (pno, e))
                continue

            new = 0
            for it in items:
                key = str(it.get(CONFIG.get("dedup_key") or "detail_url") or "")
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                it["_render"] = {"job": job, "page": pno, "channel": channel,
                                 "subresources": meter.per_page}
                rows.append(it)
                new += 1
            stats["pages_ok"] = stats.get("pages_ok", 0) + 1
            stats["records_new"] = len(rows)
            ctx["per_page"][int(pno)] = new          # 引擎要求：值是条数（int）
            ctx.setdefault("per_page_detail", {})[int(pno)] = {
                "items": len(items), "new": new,
                "subresources": meter.per_page,
                "bytes": len(html), "sec": round(time.time() - t0, 1)}
            log("第 %d 页：%d 条（新增 %d）｜子资源 %d｜%d 字节｜%.1fs"
                % (pno, len(items), new, meter.per_page, len(html), time.time() - t0))

        context.close()
        browser.close()

    # ---- 落盘 ----
    if rows:
        with open(out_file, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ctx["field_list"] = sorted({k for r in rows for k in r})
    ctx["total_in_file"] = len(rows)
    ctx["t_end"] = time.time()
    ctx["status"] = "success" if rows and not stop_reason else ("partial" if rows else "failed")
    ctx["reason"] = stop_reason or ("ok" if rows else "no_records")
    ctx["stat"]["subresources_blocked"] = blocked["n"]
    ctx["stat"]["resource_blocking"] = (not args.keep_resources)
    ctx["stat"]["per_page_detail"] = ctx.get("per_page_detail", {})
    ctx["stat"]["subresources_per_page"] = round(
        stats["subresources"] / max(stats["navigations"], 1), 1)
    md, js = crawler.write_report(ctx)
    log("报告  %s" % md)
    log("状态  %s / %s" % (ctx["status"], ctx["reason"]))
    log("=" * 62)
    log.close()
    print(json.dumps({k: ctx[k] for k in ("job", "status", "reason")}, ensure_ascii=False))
    print("渲染页数 %d ｜ 子资源 %d（均 %.1f/页）｜ 记录 %d"
          % (stats["navigations"], stats["subresources"],
             stats["subresources_per_page"], len(rows)))
    return 0 if ctx["status"] == "success" else 3


if __name__ == "__main__":
    sys.exit(main())