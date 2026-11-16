# -*- coding: utf-8 -*-
"""v14.12.1：window 每轮重抓 + 提前停位置修正 + refresh_no_new 不算异常。"""
from pathlib import Path

P = Path(r"D:\agent-work\crawlers\crawler.py")
t = P.read_text(encoding="utf-8")
hits = []


def rep(old, new, tag):
    global t
    assert old in t, "未命中：" + tag
    assert t.count(old) == 1, "多处命中：" + tag
    t = t.replace(old, new, 1)
    hits.append(tag)


# ---------- 1. window：每轮清空 pages_done（同一天第二次跑也重抓） ----------
rep('''    # ---- A5：window 模式 —— 断点只对「当天」有效，跨天作废 ----
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
        st["pages_done_at"] = {str(p): _today for p in pages_done}''',
    '''    # ---- A5：window 模式 —— 每一轮都重抓，断点不跨运行 ----
    # 根因（A5）：滚动时间窗（settr=3）+ 页码断点 = 第 1 页永远"已完成"
    #   → 新岗位永远在第 1 页顶部，而第 1 页永远被跳过 → 一个请求都不发。
    # 修法：window 模式**每次开跑就清空 pages_done**（不是"跨天才作废"）——
    #   因为同一天跑第二次时，第 1 页也在这一轮之前刚被抓过，按日期戳它还"有效"，
    #   于是第二次又变成"跳过 → 一个请求都不发"。只有"每轮重抓"才真的解决。
    # 代价说清楚：window 一轮只抓前 refresh_pages 页（默认 3），重抓成本很低；
    #   真正的去重靠 seen_keys（它跟页码无关，不清）。
    # full 模式完全不动（full 是"抓完整站"语义，续跑必须保留断点）。
    if coverage_mode() == "window":
        _prev_n = len(pages_done)
        if _prev_n:
            log("window 模式：每轮重抓前 %d 页 → 清空上一轮的 %d 页断点（%s）"
                % (int(CONFIG.get("refresh_pages") or 3), _prev_n,
                   ",".join(str(x) for x in sorted(pages_done)[:10])))
        pages_done = set()
        st["pages_done"] = []
        st["pages_done_at"] = {}
        ctx["window_expired_pages"] = _prev_n''',
    "1 window 每轮清空")

# ---------- 2. 提前停检查移到 pages_ok+1 之后（保证这页算处理完） ----------
rep('''                if dup_now:
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
    '''                if dup_now:
                    stat["records_dup"] += dup_now
                    log("  本页 %d 条已抓过，跳过详情/附件" % dup_now)''',
    "2a 移除旧位置")

rep('''                st["out_file"] = out_file
                st["updated_at"] = now_iso()
                save_state(state_path, st)
                time.sleep(random.uniform(CONFIG["delay_min"], CONFIG["delay_max"]))
                continue''',
    '''                st["out_file"] = out_file
                st["updated_at"] = now_iso()
                save_state(state_path, st)
                # A5：window 模式 —— 连续见过太多就提前停。
                # 位置很关键：必须放在 pages_ok += 1 和 save_state 之后，
                # 这样"这一页算处理完"already 成立，计数不会因为提前停而少一页。
                if coverage_mode() == "window":
                    _thr = int(CONFIG.get("refresh_stop_after_dups") or 15)
                    if window_consec_dup >= _thr:
                        stop_reason = "refresh_no_new"
                        log("  连续 %d 条都是已抓过的（阈值 %d）→ 提前停，不再翻页"
                            % (window_consec_dup, _thr))
                        break
                time.sleep(random.uniform(CONFIG["delay_min"], CONFIG["delay_max"]))
                continue''',
    "2b 插入到 pages_ok+1 之后")

# ---------- 3. refresh_no_new 不算翻页异常 ----------
rep('''    if stop_reason and stop_reason not in ("no_next", "", "soft_block_suspected"):
        if pages_ok > 0:
            log("翻页异常（%s）→ 判为 partial" % stop_reason)''',
    '''    # refresh_no_new 是 window 模式的正常收工（这轮没新数据），不是翻页异常。
    # 放进白名单，让它走后面的"正常收尾"分支（success）。
    if stop_reason and stop_reason not in ("no_next", "", "soft_block_suspected",
                                           "refresh_no_new"):
        if pages_ok > 0:
            log("翻页异常（%s）→ 判为 partial" % stop_reason)''',
    "3 refresh_no_new 白名单")

P.write_text(t, encoding="utf-8")
print("命中：", hits)
print("字符", len(t))