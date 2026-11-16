# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""阶段A 施工第二批：main() 里的冷却检查 / Referer / canary / 新统计。"""
import sys
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")
orig_lines = len(s.splitlines())

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# ---------------------------------------------------------------- 1) CLI: --ignore-cooldown
sub('''    ap.add_argument("--no-repair-attachments", dest="repair_attachments",''',
    '''    ap.add_argument("--ignore-cooldown", action="store_true",
                    help="无视冷却文件强行开跑（会立刻再敲站点，慎用）")
    ap.add_argument("--no-repair-attachments", dest="repair_attachments",''',
    "CLI 加 --ignore-cooldown")

# ---------------------------------------------------------------- 2) 冷却检查（必须在 robots 之前）
sub('''    sess = session_factory()
    first_url = CONFIG["url_template"].format(page=CONFIG["page_start"])

    # 只重建索引就到此为止，不碰网络''',
    '''    sess = session_factory()
    first_url = CONFIG["url_template"].format(page=CONFIG["page_start"])
    site_host = urlsplit(first_url).netloc.lower()

    # ---- 冷却检查：必须排在 robots 之前 ----
    # 被判软封后整站都在返回假页面，这时候连 robots 都不该再敲。
    cd = load_cooldown(site_host)
    cd_until = cooldown_until(cd)
    if cd and cd_until is not None and datetime.now(TZ) < cd_until:
        if getattr(args, "ignore_cooldown", False):
            log("!" * 62)
            log("!! 冷却期未结束（到 %s），但指定了 --ignore-cooldown" % cd["until"])
            log("!! 这一跑会继续敲站点，风险自负")
            log("!" * 62)
        else:
            log("!! 冷却中：%s 到 %s 之前不再请求（原因 %s，第 %d 次）"
                % (site_host, cd.get("until"), cd.get("reason"), cd.get("strikes", 0)))
            log("!! 要强行跑请加 --ignore-cooldown；本次未发出任何网络请求")
            ctx["cooldown"] = cd
            return finalize("failed", "cooldown_active", 6)

    # 只重建索引就到此为止，不碰网络''',
    "插入冷却检查")

# ---------------------------------------------------------------- 3) stat 初始化：新字段
sub('''    stat = {"pages_total": 0, "pages_ok": 0, "pages_skipped": 0, "pages_empty": 0,
            "pages_blocked": 0, "pages_failed": 0, "records_new": 0, "records_dup": 0,
            "detail_failed": 0}''',
    '''    stat = {"pages_total": 0, "pages_ok": 0, "pages_skipped": 0, "pages_empty": 0,
            "pages_blocked": 0, "pages_failed": 0, "records_new": 0, "records_dup": 0,
            "detail_failed": 0,
            # 阶段A 新增（先置 0，报告里一定能读到）
            "retry_after_waits": 0, "retry_after_max_sec": 0,
            "soft_block_detected": 0, "canary_requests": 0,
            "resp_bytes_min": 0, "resp_bytes_total": 0, "cards_total": 0}''',
    "stat 新字段")

# ---------------------------------------------------------------- 4) 页面循环：Referer + 响应指标
sub('''            if mode_resp == "json":
                code, payload = fetch_page(sess, url, log, page=page)
            else:
                code, payload = fetch_page(sess, url, log)''',
    '''            # Referer 按页传：第 1 页给站点根，之后给上一页的 URL。
            # 不做"全局静态 Referer"——那在跨页时反而是明显的不自然特征。
            if idx == 1:
                ref = "%s://%s/" % (urlsplit(url).scheme, urlsplit(url).netloc)
            else:
                ref = prev_url or ("%s://%s/" % (urlsplit(url).scheme, urlsplit(url).netloc))
            if mode_resp == "json":
                code, payload = fetch_page(sess, url, log, page=page, referer=ref)
            else:
                code, payload = fetch_page(sess, url, log, referer=ref)
            prev_url = url''',
    "页面循环加 Referer")

sub('''            # 接口里的名单里混进了非对象条目（字符串/数字/null）：''',
    '''            # 响应体积与卡片数：报告里要能看出"这页是不是被替换成了假页面"
            _rb = int(_LAST_META.get("bytes") or 0)
            if _rb:
                stat["resp_bytes_total"] += _rb
                stat["resp_bytes_min"] = _rb if not stat["resp_bytes_min"] else min(stat["resp_bytes_min"], _rb)

            # 接口里的名单里混进了非对象条目（字符串/数字/null）：''',
    "响应字节统计")

sub('''            # ---- 去重前置 ----''',
    '''            stat["cards_total"] = stat.get("cards_total", 0) + len(rows)

            # ---- 去重前置 ----''',
    "卡片总数")

# ---------------------------------------------------------------- 5) 空页 → canary 判定
sub('''            if not rows:
                stat["pages_empty"] += 1''',
    '''            if not rows:
                # 空页先别当"真空"：有可能是整站被替换成了假页面（软封）。
                # 判据不是字节数阈值，而是"再打一次已知有结果的页面还空不空"。
                sb = soft_block_cfg()
                if sb.get("enabled") and sb.get("canary_url"):
                    if ctx.get("canary_cards") is None:
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
                            % (ctx["canary_cards"], ctx["canary_bytes"]))

                    if ctx.get("canary_cards") == 0:
                        # 本页空 + canary 也空 → 判定软封，立刻停手
                        stat["soft_block_detected"] = 1
                        page_bytes = int(_LAST_META.get("bytes") or 0)
                        hit_markers = []
                        try:
                            if payload and any(m in str(payload) for m in sb.get("markers") or []):
                                hit_markers = [m for m in sb.get("markers") or [] if m in str(payload)]
                        except Exception:
                            pass
                        ev = {"page_url": url, "resp_bytes": page_bytes, "cards": 0,
                              "canary_url": sb["canary_url"],
                              "canary_bytes": ctx.get("canary_bytes", 0),
                              "canary_cards": ctx.get("canary_cards"),
                              "server": _LAST_META.get("server", ""),
                              "cf_ray": _LAST_META.get("cf_ray", ""),
                              "markers": hit_markers}
                        anomalies.append({"page": page, "url": url,
                                          "reason": "判定软封（软封页与 canary 都是 0 卡片）",
                                          "evidence": ev})
                        log("!! 空页 + canary 也空 → 判定为软封，立即停止（不再发任何页面请求）")
                        try:
                            old = load_cooldown(site_host) or {}
                            strikes = int(old.get("strikes") or 0) + 1
                            cd_data, sec = save_cooldown(site_host, "soft_block_suspected",
                                                         strikes, ev)
                            log("!! 已写冷却文件：%s（%d 秒，第 %d 次）"
                                % (cooldown_path(site_host), sec, strikes))
                        except Exception as e:
                            log("!! 冷却文件写入失败 %s: %s" % (type(e).__name__, e))
                        ctx["stop_reason"] = "soft_block_suspected"
                        soft_blocked = True
                        break

                stat["pages_empty"] += 1''',
    "插入 canary 软封判定")

# ---------------------------------------------------------------- 6) 循环变量：prev_url / soft_blocked
sub('''    consecutive_empty = 0
    dedup_checked = False''',
    '''    consecutive_empty = 0
    dedup_checked = False
    prev_url = ""          # 上一页的 URL，用来给下一页当 Referer
    soft_blocked = False   # 判定软封后不再继续''',
    "循环变量")

# ---------------------------------------------------------------- 7) 状态判定：软封优先
sub('''    # 附件有失败：数据拿到了，但文件没下全，不能报 success''',
    '''    if soft_blocked or stat.get("soft_block_detected"):
        log("!! 本次判定为软封 → failed / soft_block_suspected")
        return finalize("failed", "soft_block_suspected", 6)

    # 附件有失败：数据拿到了，但文件没下全，不能报 success''',
    "软封状态判定")

P.write_text(s, encoding="utf-8", newline="\n")
print("第二批完成，行数 %d → %d" % (orig_lines, len(s.splitlines())))