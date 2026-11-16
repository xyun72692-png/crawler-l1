# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""提案1：总页数发现（M）+ 报告字段 + 截断状态；page_size state 记录。"""
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# ---------------- 1) 解析函数 ----------------
sub('''def probe_canary(sess, log, sb, parse_html):''',
    '''def declared_total_pages(payload, page_url, site_mod=None):
    """
    从**服务器渲染的第一页 HTML**里读"共 M 页"。

    优先级：
      1. 站点模块提供 parse_total_pages(html, page_url) → 用它的返回值
      2. CONFIG["total_pages_pattern"] 正则（第 1 个分组）
    取不到 / 解析失败 / 值不合理（<1）→ 返回 None（调用方按配置页数继续跑）。

    为什么要读它：配置里的页数是拍脑袋的。
      配多了 → 后面全是空页 → 假告警（partial/empty_page_seen）
      配少了 → 只抓一部分却报 success → 假成功（更危险）
    """
    if not payload or not isinstance(payload, str):
        return None
    pat = CONFIG.get("total_pages_pattern") or ""
    if site_mod is not None and hasattr(site_mod, "parse_total_pages"):
        try:
            m = site_mod.parse_total_pages(payload, page_url)
            if m:
                return int(m)
        except Exception:
            pass
    if not pat:
        return None
    try:
        mo = re.search(pat, payload)
        if not mo:
            return None
        m = int(mo.group(1))
        return m if m >= 1 else None
    except Exception:
        return None


def probe_canary(sess, log, sb, parse_html):''',
    "1) declared_total_pages")

# ---------------- 2) ctx 字段 + page_size 变更处理 ----------------
sub('''    st = load_state(state_path, out_file)''',
    '''    st = load_state(state_path, out_file)

    # ---- page_size 变更检测 ----
    # 站点用 page_size 改变每页条数时，页码与内容的对应关系就变了：
    # 旧断点里的 pages_done 全部作废（否则会跳过没抓过的内容）。
    # 去重键 seen_keys 必须保留（它跟页码无关，是真正的"抓过没有"）。
    ps_now = CONFIG.get("page_size") or ""
    ps_old = st.get("page_size") or ""
    if ps_now != ps_old and st.get("pages_done"):
        log("注意：page_size 从 %r 变成 %r → 旧断点（%d 页）作废，去重键保留 %d 条"
            % (ps_old, ps_now, len(st.get("pages_done") or []), len(st.get("seen_keys") or [])))
        st["pages_done"] = []
        st["page_size"] = ps_now
        st["out_file"] = out_file
        st["updated_at"] = now_iso()
        save_state(state_path, st)
        ctx.setdefault("anomalies", []).append(
            {"page": "state", "url": "", "reason": "page_size 变更 %r→%r，已清 pages_done"
                                                    % (ps_old, ps_now)})
    elif ps_now:
        st["page_size"] = ps_now''',
    "2) page_size 变更")

# ---------------- 3) 报告字段 ----------------
sub('''        # 因冷却退出时，报告里要能查到"冷却到几点"（否则只有一个 cooldown_active 词）
        "cooldown": ctx.get("cooldown"),''',
    '''        # 因冷却退出时，报告里要能查到"冷却到几点"（否则只有一个 cooldown_active 词）
        "cooldown": ctx.get("cooldown"),
        # 页数口径（提案1）：声明值来自页面"1/M页"，plan 是配置/CLI 给的计划值
        "pages_declared": ctx.get("pages_declared"),
        "pages_planned": ctx.get("pages_planned"),
        "pages_effective": ctx.get("pages_effective"),
        "coverage": ctx.get("coverage"),
        "truncated": bool(ctx.get("truncated")),
        # 页大小探针（提案3）
        "page_size": CONFIG.get("page_size") or "",
        "page_size_probe": bool(CONFIG.get("page_size_probe")),''',
    "3) 报告字段")

# ---------------- 4) 循环里解析 M 并夹紧 ----------------
sub('''    idx = 0
    try:
        while work:''',
    '''    # 页数口径（提案1）：plan 是"计划抓多少页"，declared 是页面自己声明的总页数
    ctx["pages_planned"] = CONFIG["page_end"]
    ctx["pages_effective"] = CONFIG["page_end"]
    ctx["pages_declared"] = None
    ctx["truncated"] = False
    _m_tried = False

    idx = 0
    try:
        while work:''',
    "4) 循环前初始化")

sub('''            # 响应体积与卡片数：报告里要能看出"这页是不是被替换成了假页面"''',
    '''            # ---- 总页数发现（提案1）----
            # 从**本轮第一个真正抓到的页面**解析：续跑时第 1 页可能被跳过，
            # 所以不能写死"只读第 1 页"，否则续跑永远拿不到 M。
            if paginate == "number" and ctx.get("pages_declared") is None and not _m_tried:
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
                else:
                    anomalies.append({"page": page, "url": url,
                                      "reason": "页面上读不到总页数（按配置页数继续）"})
                    log("  读不到总页数 → 按配置页数 %d 继续（只记 anomaly，不拦）"
                        % CONFIG["page_end"])

            # 响应体积与卡片数：报告里要能看出"这页是不是被替换成了假页面"''',
    "4) 循环里解析 M")

# ---------------- 5) coverage + 状态分支 ----------------
sub('''    # 附件有失败：数据拿到了，但文件没下全，不能报 success''',
    '''    # 覆盖率：已抓到数据的页数 / 页面声明的总页数
    _M = ctx.get("pages_declared")
    if _M:
        ctx["coverage"] = round(min(1.0, float(pages_ok) / float(_M)), 3)
    else:
        ctx["coverage"] = None

    # 被"页面声明的总页数"夹紧 → 说明这次没抓完整个结果集。
    # 显式给了 --pages 时这是用户自己要的（按 success 报，但报告里 coverage 会说话）；
    # 没给 --pages 就是配置页数拍大了，必须报 partial，不能假装抓完。
    if ctx.get("truncated"):
        if getattr(args, "pages", None) is not None:
            log("注意：本次只覆盖 %s（声明 %s 页，--pages 限定了 %s 页）"
                % (ctx.get("coverage"), _M, getattr(args, "pages", None)))
        else:
            log("注意：配置页数 %s 大于站点声明的 %s 页 → 判为 partial（没抓完整个结果集）"
                % (ctx.get("pages_planned"), _M))
            return finalize("partial", "page_range_truncated", 3)

    # 附件有失败：数据拿到了，但文件没下全，不能报 success''',
    "5) coverage 与截断状态")

P.write_text(s, encoding="utf-8", newline="\n")
print("crawler.py 提案1 补丁完成")

# ---------------- 6) wzrc_all 默认页数 150 ----------------
W = Path(str(_HOME / "crawlers" / "sites" / "wzrc_all.py"))
t = W.read_text(encoding="utf-8")
old = 'PAGES = int(os.environ.get("WZ_PAGES", "40"))   # 默认 40（原 113），防手滑跑满全站'
new = ('PAGES = int(os.environ.get("WZ_PAGES", "150"))  # 安全上限 150（站点声明值会把它夹紧）\n'
       '# 为什么不是 40：全温州 949 页，40 页会漏掉大半；为什么不是 949：\n'
       '# 先给一个"够用但不出事"的上限，真实页数由页面声明的 M 决定（见 total_pages_pattern）')
assert t.count(old) == 1
t = t.replace(old, new, 1)
if "total_pages_pattern" not in t:
    t = t.replace('    "respect_robots": True,\n    "dedup_key": "detail_url",',
                  '    "respect_robots": True,\n    "dedup_key": "detail_url",\n'
                  '    # 页面里 <span>1</span>/949页 → 声明总页数；读不到就按 PAGES 跑\n'
                  '    "total_pages_pattern": r"</span>\\s*/\\s*(\\d+)\\s*页",', 1)
W.write_text(t, encoding="utf-8", newline="\n")
print("wzrc_all：页数 150 + total_pages_pattern")