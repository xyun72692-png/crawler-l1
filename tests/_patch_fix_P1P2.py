# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""P1/P2 修复：stop_reason 覆盖、证据取错页、冷却可见性、页数、冷却分组。"""
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# ---------------- P1-2：抓完当前页立刻快照 meta ----------------
sub('''            else:
                code, payload = fetch_page(sess, url, log, referer=ref)
            prev_url = url''',
    '''            else:
                code, payload = fetch_page(sess, url, log, referer=ref)
            prev_url = url
            # 立刻快照"这一页"的响应元信息：后面打 canary 会把 _LAST_META 覆盖掉，
            # 到那时再读就成了 canary 的字节数/响应头，证据会张冠李戴。
            page_meta = dict(_LAST_META)''',
    "P1-2 页面 meta 快照")

sub('''            _rb = int(_LAST_META.get("bytes") or 0)''',
    '''            _rb = int(page_meta.get("bytes") or 0)''',
    "P1-2 页字节数改用快照")

# ---------------- P1-1：软封时同时写局部 stop_reason ----------------
sub('''                        ctx["stop_reason"] = "soft_block_suspected"
                        soft_blocked = True
                        break''',
    '''                        # 局部变量也要写：后面 `ctx["stop_reason"] = stop_reason`
                        # 会用局部值覆盖 ctx，只写 ctx 的话报告里就变回空字符串。
                        stop_reason = "soft_block_suspected"
                        ctx["stop_reason"] = stop_reason
                        soft_blocked = True
                        break''',
    "P1-1 stop_reason 同步")

# ---------------- P1-2：证据改用 page_meta ----------------
sub('''                        page_bytes = int(_LAST_META.get("bytes") or 0)''',
    '''                        page_bytes = int(page_meta.get("bytes") or 0)''',
    "P1-2 证据字节数")

sub('''                              "server": _LAST_META.get("server", ""),
                              "cf_ray": _LAST_META.get("cf_ray", ""),''',
    '''                              "server": page_meta.get("server", ""),
                              "cf_ray": page_meta.get("cf_ray", ""),''',
    "P1-2 证据响应头")

# ---------------- P2-2：软封页单独计数 ----------------
sub('''                        stat["soft_block_detected"] = 1''',
    '''                        stat["soft_block_detected"] = 1
                        # 这一页既不算成功也不算普通空页，单独计一项，
                        # 否则 pages_total=1 而 ok/empty/failed 全 0，报告自相矛盾。
                        stat["pages_soft_blocked"] = 1''',
    "P2-2 软封页计数")

# ---------------- P2-3：冷却分组 ----------------
sub('''SOFT_BLOCK_DEFAULTS = {
    "enabled": False,''',
    '''SOFT_BLOCK_DEFAULTS = {
    "enabled": False,
    # 冷却分组：同一家站点的多个子域共用一把锁（WAF 通常按 IP 封，子站会一起死）。
    # 留空 = 按 host 各自锁。
    "group": "",''',
    "P2-3 配置项 group")

sub('''def cooldown_path(host):
    """
    冷却文件路径。**必须**从 state_dir 派生：
    测试用 CRAWLER_STATE_DIR 隔离，写死全局目录会污染真实运行目录。
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", host or "unknown")
    return os.path.join(CONFIG["state_dir"], "_cooldown_%s.json" % safe)''',
    '''def cooldown_group(host):
    """冷却按组算：站点配了 soft_block.group 就用它，否则用 host。"""
    g = (soft_block_cfg().get("group") or "").strip()
    return g or host


def cooldown_path(host):
    """
    冷却文件路径。**必须**从 state_dir 派生：
    测试用 CRAWLER_STATE_DIR 隔离，写死全局目录会污染真实运行目录。
    传进来的是"组名"（cooldown_group 的结果），不是裸 host。
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", host or "unknown")
    return os.path.join(CONFIG["state_dir"], "_cooldown_%s.json" % safe)''',
    "P2-3 group 解析")

sub('''    site_host = urlsplit(first_url).netloc.lower()''',
    '''    site_host = urlsplit(first_url).netloc.lower()
    cd_key = cooldown_group(site_host)   # 冷却按"组"锁，默认等于 host''',
    "P2-3 冷却键")

sub('''    cd = load_cooldown(site_host)''', '''    cd = load_cooldown(cd_key)''', "P2-3 读冷却")
sub('''            log("!! 冷却中：%s 到 %s 之前不再请求（原因 %s，第 %d 次）"
                % (site_host, cd.get("until"), cd.get("reason"), cd.get("strikes", 0)))''',
    '''            log("!! 冷却中：%s 到 %s 之前不再请求（原因 %s，第 %d 次）"
                % (cd_key, cd.get("until"), cd.get("reason"), cd.get("strikes", 0)))''',
    "P2-3 日志用组名")
sub('''                            old = load_cooldown(site_host) or {}''',
    '''                            old = load_cooldown(cd_key) or {}''', "P2-3 读旧 strikes")
sub('''                            cd_data, sec = save_cooldown(site_host, "soft_block_suspected",''',
    '''                            cd_data, sec = save_cooldown(cd_key, "soft_block_suspected",''',
    "P2-3 写冷却用组名")
sub('''                            log("!! 已写冷却文件：%s（%d 秒，第 %d 次）"
                                % (cooldown_path(site_host), sec, strikes))''',
    '''                            log("!! 已写冷却文件：%s（%d 秒，第 %d 次）"
                                % (cooldown_path(cd_key), sec, strikes))''',
    "P2-3 日志路径用组名")

# ---------------- P2-1：报告带上冷却信息 ----------------
sub('''        "stats": dict(stat),''',
    '''        "stats": dict(stat),
        # 因冷却退出时，报告里要能查到"冷却到几点"（否则只有一个 cooldown_active 词）
        "cooldown": ctx.get("cooldown"),''',
    "P2-1 报告带 cooldown")

P.write_text(s, encoding="utf-8", newline="\n")
print("P1/P2 修复完成")