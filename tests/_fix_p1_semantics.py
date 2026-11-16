# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""修正提案1语义（v2：锚点按实际文本重写）。"""
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# 1) 支持检测 + coverage_mode
sub('''def declared_total_pages(payload, page_url, site_mod=None):''',
    '''def total_pages_supported(site_mod=None):
    """这个站点到底有没有配"总页数声明"的来源？没配就静默跳过，不写 anomaly。"""
    if CONFIG.get("total_pages_pattern"):
        return True
    return site_mod is not None and hasattr(site_mod, "parse_total_pages")


def coverage_mode():
    """'full'（默认，要求抓完整个结果集）/ 'window'（只维护最近窗口，覆盖不全属正常）"""
    v = (CONFIG.get("coverage_mode") or "full").strip().lower()
    return v if v in ("full", "window") else "full"


def declared_total_pages(payload, page_url, site_mod=None):''',
    "1) 支持检测")

# 2) 循环里：未配置静默跳过 + M 语义反向
sub('''            if paginate == "number" and ctx.get("pages_declared") is None and not _m_tried:
                _m_tried = True
                M = declared_total_pages(payload if mode_resp == "html" else None, url, site_mod)
                if M:
                    planned = CONFIG["page_end"]
                    eff = min(planned, M)
                    ctx["pages_declared"] = M
                    ctx["pages_effective"] = eff
                    if eff < planned:
                        ctx["truncated"] = True
                        CONFIG["page_end"] = eff
                        work = [(p, u) for (p, u) in work if p <= eff]
                        log("页面声明共 %d 页 < 计划 %d 页 → 本次只抓到第 %d 页"
                            % (M, planned, eff))
                    else:
                        log("页面声明共 %d 页（计划 %d 页）→ 按计划继续" % (M, planned))
                else:''',
    '''            # 语义（2026-11-11 修正）：
            #   M ≤ 计划 → 夹紧到 M，这是"抓全了"，truncated=False
            #   M > 计划 → 本次只覆盖一个窗口，truncated=True（报不报 partial 看状态块）
            # 站点没配 pattern / parse_total_pages → 静默跳过，不记 anomaly
            if (paginate == "number" and mode_resp == "html"
                    and ctx.get("pages_declared") is None and not _m_tried
                    and total_pages_supported(site_mod)):
                _m_tried = True
                M = declared_total_pages(payload, url, site_mod)
                if M:
                    planned = CONFIG["page_end"]
                    ctx["pages_declared"] = M
                    if M <= planned:
                        CONFIG["page_end"] = M
                        work = [(p, u) for (p, u) in work if p <= M]
                        ctx["pages_effective"] = M
                        ctx["truncated"] = False
                        log("页面声明共 %d 页 ≤ 计划 %d 页 → 夹紧到 %d 页（视为抓全）"
                            % (M, planned, M))
                    else:
                        ctx["pages_effective"] = planned
                        ctx["truncated"] = True
                        log("页面声明共 %d 页 > 计划 %d 页 → 本次只覆盖前 %d 页"
                            % (M, planned, planned))
                else:''',
    "2) M 语义反向")

# 3) 续跑从 state 读 M
sub('''    ctx["pages_effective"] = CONFIG["page_end"]
    ctx["pages_declared"] = None''',
    '''    ctx["pages_effective"] = CONFIG["page_end"]
    # 续跑时上一次已经知道 M，就不必再从页面读（那一页可能全被跳过）
    ctx["pages_declared"] = st.get("pages_declared") or None''',
    "3) 续跑读 M")

# 4) 两处 pages_done 落盘时顺便记 M
sub('''                if paginate == "number":
                    pages_done.add(page)
                    st["pages_done"] = sorted(pages_done)
                else:''',
    '''                if paginate == "number":
                    pages_done.add(page)
                    st["pages_done"] = sorted(pages_done)
                    if ctx.get("pages_declared"):
                        st["pages_declared"] = ctx["pages_declared"]
                else:''',
    "4a) 落盘 M（去重跳过分支）")

sub('''            if paginate == "number":
                pages_done.add(page)
                st["pages_done"] = sorted(pages_done)
            else:''',
    '''            if paginate == "number":
                pages_done.add(page)
                st["pages_done"] = sorted(pages_done)
                if ctx.get("pages_declared"):
                    st["pages_declared"] = ctx["pages_declared"]
            else:''',
    "4b) 落盘 M（正常完成分支）")

# 5) coverage 用 pages_done
sub('''    _M = ctx.get("pages_declared")
    if _M:
        ctx["coverage"] = round(min(1.0, float(pages_ok) / float(_M)), 3)
    else:
        ctx["coverage"] = None''',
    '''    _M = ctx.get("pages_declared")
    if _M:
        # 口径：已完成的页数 / 站点声明总页数（不是"有数据的页数"）。
        # 续跑第二跑 pages_ok=0（全被跳过），但那不代表没覆盖。
        _done = len(pages_done) if paginate == "number" else len(urls_done)
        ctx["coverage"] = round(min(1.0, float(_done) / float(_M)), 3)
    else:
        ctx["coverage"] = None''',
    "5) coverage 口径")

# 6) 状态判定：window 模式不算 partial
sub('''    if ctx.get("truncated"):
        if getattr(args, "pages", None) is not None:
            log("注意：本次只覆盖 %s（声明 %s 页，--pages 限定了 %s 页）"
                % (ctx.get("coverage"), _M, getattr(args, "pages", None)))
        else:
            log("注意：配置页数 %s 大于站点声明的 %s 页 → 判为 partial（没抓完整个结果集）"
                % (ctx.get("pages_planned"), _M))
            return finalize("partial", "page_range_truncated", 3)''',
    '''    if ctx.get("truncated"):
        if getattr(args, "pages", None) is not None:
            log("注意：本次只覆盖 %s（声明 %s 页，--pages 限定了 %s 页）"
                % (ctx.get("coverage"), _M, getattr(args, "pages", None)))
        elif coverage_mode() == "window":
            log("注意：window 模式（只维护最近窗口）→ 覆盖 %s / 声明 %s 页，按正常收工"
                % (ctx.get("coverage"), _M))
        else:
            log("注意：计划页数 %s 小于站点声明的 %s 页 → 判为 partial（没抓完整个结果集）"
                % (ctx.get("pages_planned"), _M))
            return finalize("partial", "page_range_truncated", 3)''',
    "6) window 状态")

P.write_text(s, encoding="utf-8", newline="\n")
print("crawler.py 语义修正完成")