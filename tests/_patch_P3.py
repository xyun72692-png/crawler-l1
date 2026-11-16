# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""P3 五条 + P2-3 接线 + pages_soft_blocked 初始化。"""
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# ---------------- P3-3：字节数用 content，不用 text.encode ----------------
sub('''    try:
        text = resp.text or ""
        _LAST_META["bytes"] = len(text.encode("utf-8", errors="ignore"))
    except Exception:
        _LAST_META["bytes"] = 0''',
    '''    try:
        # 用原始字节：resp.text 是解码后的字符串，
        # 页面没声明 charset（或被猜成 gbk/iso-8859-1）时 encode 回去的长度不等于真实字节数。
        raw = getattr(resp, "content", None)
        _LAST_META["bytes"] = len(raw) if raw is not None else len(
            (resp.text or "").encode("utf-8", errors="ignore"))
    except Exception:
        _LAST_META["bytes"] = 0''',
    "P3-3 用 content")

# ---------------- P3-5：冷却文件损坏 → fail-closed ----------------
sub('''def load_cooldown(host):
    p = cooldown_path(host)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None''',
    '''def load_cooldown(host):
    """
    读冷却文件。文件不存在 → None（正常放行）。

    **文件存在但读不出来 → 当作"仍在冷却"**（fail-closed）：
    一个损坏的冷却文件意味着"我们本来认为这个站被封过"，这时候放行等于
    把安全决定建立在一条解析失败的记录上。宁可挡一次，也不要继续敲门。
    """
    p = cooldown_path(host)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        return data
    except Exception as e:
        return {"host": host,
                "until": (datetime.now(TZ) + timedelta(hours=2)).isoformat(timespec="seconds"),
                "reason": "cooldown_file_corrupt",
                "strikes": 0,
                "corrupt": True,
                "parse_error": "%s: %s" % (type(e).__name__, str(e)[:60]),
                "updated_at": now_iso()}''',
    "P3-5 fail-closed")

# ---------------- P3-1：canary 也要过 robots（抽成函数便于测） ----------------
sub('''def cooldown_group(host):''',
    '''def probe_canary(sess, log, sb, parse_html):
    """
    打一次 canary 并解析出卡片数。

    返回 (cards, bytes, skip_reason)：
        cards      int ≥0 = 解析到的卡片数；None = 无法判定
        skip_reason  "" 或 "robots_denied"（canary 自己也被 robots 禁）

    canary 必须和普通页一样过 robots：它也是对这个站点发请求，
    不能因为"它是探针"就绕开规则（robots 规则已缓存，查一次零成本）。
    """
    curl = sb.get("canary_url") or ""
    if not curl:
        return None, 0, "no_canary_url"
    if CONFIG.get("respect_robots", True) and not url_allowed(curl, log):
        log("  canary 被 robots 禁止 → 无法用它判定（不算软封）")
        return None, 0, "robots_denied"
    ref = "%s://%s/" % (urlsplit(curl).scheme, urlsplit(curl).netloc)
    try:
        code, payload = fetch_page(sess, curl, log, referer=ref)
    except Exception as e:
        log("  canary 抓取失败 %s → 无法判定" % type(e).__name__)
        return None, int(_LAST_META.get("bytes") or 0), "error"
    nbytes = int(_LAST_META.get("bytes") or 0)
    if not payload:
        return None, nbytes, "empty_payload"
    try:
        rows = parse_html(payload, curl)
    except Exception as e:
        log("  canary 解析失败 %s → 无法判定" % type(e).__name__)
        return None, nbytes, "parse_error"
    return len(rows), nbytes, ""


def cooldown_group(host):''',
    "P3-1 抽 probe_canary")

# 用新函数替换原来的内联 canary 抓取
sub('''                    if ctx.get("canary_cards") is None:
                        stat["canary_requests"] += 1
                        log("  空页 → 打一次 canary 对照：%s" % sb["canary_url"])
                        time.sleep(random.uniform(CONFIG["delay_min"], CONFIG["delay_max"]))
                        try:
                            c_code, c_payload = fetch_page(sess, sb["canary_url"], log,
                                                           referer="%s://%s/" % (
                                                               urlsplit(sb["canary_url"]).scheme,
                                                               urlsplit(sb["canary_url"]).netloc))
                            c_rows = parse_list(c_payload, sb["canary_url"]) if c_payload else []
                        except Exception as e:
                            log("  canary 抓取失败 %s → 无法判定，按普通空页处理" % type(e).__name__)
                            c_rows = None
                        if c_rows is None:
                            ctx["canary_cards"] = -1
                            ctx["canary_bytes"] = int(_LAST_META.get("bytes") or 0)
                        else:
                            ctx["canary_cards"] = len(c_rows)
                            ctx["canary_bytes"] = int(_LAST_META.get("bytes") or 0)
                        log("  canary 结果：%s 张卡片（%s 字节）"
                            % (ctx["canary_cards"], ctx["canary_bytes"]))''',
    '''                    if ctx.get("canary_cards") is None:
                        stat["canary_requests"] += 1
                        log("  空页 → 打一次 canary 对照：%s" % sb["canary_url"])
                        time.sleep(random.uniform(CONFIG["delay_min"], CONFIG["delay_max"]))
                        c_cards, c_bytes, c_skip = probe_canary(sess, log, sb, parse_list)
                        ctx["canary_cards"] = -1 if c_cards is None else c_cards
                        ctx["canary_bytes"] = c_bytes
                        if c_skip:
                            ctx["canary_skip"] = c_skip
                            log("  canary 无法判定（%s）→ 按普通空页处理" % c_skip)
                        else:
                            log("  canary 结果：%s 张卡片（%s 字节）" % (c_cards, c_bytes))''',
    "P3-1 用 probe_canary")

# ---------------- P2-2 补齐：初始化就带上 ----------------
sub('''            "soft_block_detected": 0, "canary_requests": 0,''',
    '''            "soft_block_detected": 0, "canary_requests": 0, "pages_soft_blocked": 0,''',
    "P2-2 初始化")

# ---------------- P3-4：rebuild-index 提到冷却检查之前 ----------------
REBUILD = '''    # 只重建索引就到此为止，不碰网络
    if args.rebuild_index:
        seen_only = rebuild_seen(out_file, CONFIG["dedup_key"])
        st0 = load_state(state_path, out_file)
        st0["seen_keys"] = list(seen_only)
        st0["out_file"] = out_file
        st0["updated_at"] = now_iso()
        save_state(state_path, st0)
        log("--rebuild-index：从数据文件重建出去重键 %d 条，未请求任何页面" % len(seen_only))
        ctx["records_before"] = len(seen_only)
        ctx["total_in_file"] = len(seen_only)
        ctx["mode"] = "noop"
        return finalize("noop", "rebuild_index_only", 0)
'''
sub(REBUILD, "", "P3-4 摘出 rebuild-index")

sub('''    # ---- 冷却检查：必须排在 robots 之前 ----''',
    REBUILD + '''
    # ---- 冷却检查：必须排在 robots 之前（但排在 rebuild-index 之后，纯本地操作不该被挡）----''',
    "P3-4 rebuild-index 前置")

# ---------------- P3-2：json 模式不支持 canary → 启动即拒绝 ----------------
sub('''    # 只重建索引就到此为止，不碰网络''',
    '''    # ---- 软封判定需要 HTML 解析；json 模式下 parse_list 解不了 dict ----
    # 不拒绝的话，canary 会一直"无法判定"，等于配了开关却永远不触发（假安全）。
    sb0 = soft_block_cfg()
    if sb0.get("enabled") and response_mode() == "json":
        log("!! soft_block.enabled=true 但 response=json：")
        log("!! json 模式下 canary 无法用 parse_list 解析，软封判定会永远不触发。")
        log("!! 要么关掉 soft_block，要么给该站改成 html 模式。本次直接退出（零请求）。")
        return finalize("failed", "soft_block_incompatible", 1)

    # 只重建索引就到此为止，不碰网络''',
    "P3-2 兼容性拒绝")

P.write_text(s, encoding="utf-8", newline="\n")
print("P3 / P2-2 补丁完成")