# -*- coding: utf-8 -*-
"""A5 最小版：window 模式的时间维度断点。

六件事：
  1. pages_done 加日期戳（st["pages_done_at"]）
  2. window 跨天作废；full 保持续跑
  3. window 每次只看前 refresh_pages 页（默认 3）
  4. seen_keys 去重（已有，复用）
  5. 连续 refresh_stop_after_dups 条都见过 → 提前停（跨页累计）
  6. 验证：跨天后第 1 页必须重抓

只做精确字符串替换；每处都断言命中，避免"改了一半"。
"""
from pathlib import Path

P = Path(r"D:\agent-work\crawlers\crawler.py")
t = P.read_text(encoding="utf-8")
orig = t
hits = []


def rep(old, new, tag):
    global t
    assert old in t, "未命中：" + tag
    assert t.count(old) == 1, "命中多处以至于不确定：" + tag
    t = t.replace(old, new, 1)
    hits.append(tag)


# ---------- A. import date ----------
rep("import hashlib\nimport ipaddress",
    "import hashlib\nimport ipaddress\nfrom datetime import date",
    "A import date")

# ---------- B. blank_state 加 pages_done_at ----------
rep('''        "pages_done": [],      # number 模式''',
    '''        "pages_done": [],      # number 模式
        # A5：页码 -> 抓完那天的日期（'YYYY-MM-DD'）。
        # window 模式跨天作废用它判断；full 模式不看它（续跑语义）。
        "pages_done_at": {},''',
    "B blank_state")

# ---------- C. load 后：window 跨天作废 ----------
rep('''    pages_done = set(st["pages_done"])
    log("断点：已完成 %d 页，已知去重键 %d 条" % (len(pages_done), len(seen)))''',
    '''    pages_done = set(st["pages_done"])

    # ---- A5：window 模式 —— 断点只对「当天」有效，跨天作废 ----
    # 根因（A5）：滚动时间窗（settr=3）+ 页码断点 = 第 1 页永远"已完成"
    #   → 新岗位永远在第 1 页顶部，而第 1 页永远被跳过 → 一个请求都不发。
    # 修法：给每一页记"哪天抓的"，window 模式只认今天的；full 模式完全不动
    #   （full 是"抓完整站"语义，续跑必须保留断点）。
    if coverage_mode() == "window":
        _today = date.today().isoformat()
        _done_at = st.get("pages_done_at") or {}
        _stale = sorted(p for p in pages_done if str(_done_at.get(str(p))) != _today)
        if _stale:
            for _p in _stale:
                pages_done.discard(_p)
            st["pages_done"] = sorted(pages_done)
            ctx["window_expired_pages"] = len(_stale)
            log("window 模式：%d 页断点是跨天的（%s）→ 已作废，本轮重抓"
                % (len(_stale), ",".join(str(x) for x in _stale[:10])))
        # 只保留今天的页码戳（旧戳已被上面的作废清掉）
        st["pages_done_at"] = {str(p): _today for p in pages_done}
    log("断点：已完成 %d 页，已知去重键 %d 条" % (len(pages_done), len(seen)))''',
    "C window 跨天作废")

# ---------- D. work 构造：window 只看前 N 页 ----------
rep('''    if paginate == "number":
        work = [(p, CONFIG["url_template"].format(page=p))
                for p in range(CONFIG["page_start"], CONFIG["page_end"] + 1)]''',
    '''    if paginate == "number":
        _pe = CONFIG["page_end"]
        if coverage_mode() == "window":
            # A5：滚动时间窗下"抓完整站"没意义，只维护最近窗口。
            # 默认前 3 页；站点可用 refresh_pages 覆盖。
            _cap = int(CONFIG.get("refresh_pages") or 3)
            _pe = min(_pe, CONFIG["page_start"] + _cap - 1)
            log("window 模式：本轮只看前 %d 页（第 %d–%d 页）"
                % (_cap, CONFIG["page_start"], _pe))
        work = [(p, CONFIG["url_template"].format(page=p))
                for p in range(CONFIG["page_start"], _pe + 1)]''',
    "D work 限页")

# ---------- E. 跨页累计"连续见过" ----------
rep('''            dup_now = 0
            if rows:''',
    '''            dup_now = 0
            # A5：跨页累计"连续见过"的条数（遇到新记录就清零）。
            # 用累计而不是按页，是因为一页可能只有 5 条，单页永远到不了阈值。
            if rows:''',
    "E1 注释")

rep('''                    if k0 and (k0 in seen or k0 in batch_seen):
                        dup_now += 1
                        continue''',
    '''                    if k0 and (k0 in seen or k0 in batch_seen):
                        dup_now += 1
                        window_consec_dup += 1
                        continue
                    window_consec_dup = 0   # A5：遇到新记录，连续计数清零''',
    "E2 累计计数")

rep('''                if dup_now:
                    stat["records_dup"] += dup_now
                    log("  本页 %d 条已抓过，跳过详情/附件" % dup_now)''',
    '''                if dup_now:
                    stat["records_dup"] += dup_now
                    log("  本页 %d 条已抓过，跳过详情/附件" % dup_now)

                # A5：window 模式 —— 连续见过太多就提前停（不再往后翻页）
                if coverage_mode() == "window" and not rows:
                    _thr = int(CONFIG.get("refresh_stop_after_dups") or 20)
                    if window_consec_dup >= _thr:
                        stop_reason = "refresh_no_new"
                        log("  连续 %d 条都是已抓过的（阈值 %d）→ 提前停，不再翻页"
                            % (window_consec_dup, _thr))
                        break''',
    "E3 提前停")

# ---------- F. 循环外初始化计数器 ----------
rep('''    idx = 0
    try:
        while work:''',
    '''    idx = 0
    # A5：window 模式的"连续见过"计数器（跨页累计；full 模式不用）
    window_consec_dup = 0
    try:
        while work:''',
    "F 计数器初始化")

# ---------- G. 两处 pages_done.add 后写日期 ----------
pairs = [
    ('''                    if not _over_M2:
                        pages_done.add(page)
                        st["pages_done"] = sorted(pages_done)''',
     '''                    if not _over_M2:
                        pages_done.add(page)
                        st["pages_done"] = sorted(pages_done)
                        if coverage_mode() == "window":
                            st.setdefault("pages_done_at", {})[str(page)] = date.today().isoformat()''',
     "G1 整页全旧的 add"),
    ('''                else:
                    pages_done.add(page)
                    st["pages_done"] = sorted(pages_done)''',
     '''                else:
                    pages_done.add(page)
                    st["pages_done"] = sorted(pages_done)
                    if coverage_mode() == "window":
                        st.setdefault("pages_done_at", {})[str(page)] = date.today().isoformat()''',
     "G2 正常页的 add"),
]
for old, new, tag in pairs:
    rep(old, new, tag)

P.write_text(t, encoding="utf-8")
print("命中 %d 处：" % len(hits))
for h in hits:
    print("   ✓", h)
print("字符 %d → %d" % (len(orig), len(t)))