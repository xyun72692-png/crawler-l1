# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""修复 codex 复审的两处阻断：
   1) 坏冷却文件每次续期 → 永久锁死（改为隔离 + 落一份合法冷却，不自我续命）
   2) rebuild-index 被 json+soft_block 兼容性检查挡住（把纯本地操作提到最前）
   顺带：yqwzrc_wage 的 canary 改成"自己的列表页第 1 页"。
"""
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# ---------------- 1) load_cooldown：隔离坏文件 + 落合法冷却 ----------------
sub('''def load_cooldown(host):
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
    '''def load_cooldown(host, log=None):
    """
    读冷却文件。文件不存在 → None（正常放行）。

    **文件存在但读不出来 → 按损坏处理，并且一次做三件事**：
      1. 把坏文件改名隔离成 `*.corrupt-<时间戳>`（留证据，不直接删）
      2. 写一份**合法**冷却 JSON（reason=cooldown_file_corrupt，2 小时）
      3. 日志写明原路径/隔离后路径/恢复方式

    为什么必须落一份合法文件：只在内存里造一个"now+2h"的假冷却，
    下次启动又会从坏文件重新算出新的 now+2h —— 等于**永久锁死这个站**。
    落盘之后，第二次读到的就是合法文件，到期自然放行。
    """
    p = cooldown_path(host)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("不是 JSON 对象")
        if cooldown_until(data) is None:
            # JSON 合法但 until 丢了/写坏了：同样属于"读不出有效期"，按损坏处理
            raise ValueError("until 字段缺失或无法解析")
        return data
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:60])
        stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
        quarantine = "%s.corrupt-%s" % (p, stamp)
        try:
            os.replace(p, quarantine)
        except Exception:
            quarantine = "(改名失败，原文件仍在原地)"
        data, sec = save_cooldown(host, "cooldown_file_corrupt", 0,
                                  {"parse_error": err, "quarantined_to": quarantine})
        if log:
            log("!! 冷却文件损坏（%s）" % err)
            log("!!   原文件：%s" % p)
            log("!!   已隔离：%s" % quarantine)
            log("!!   已写入合法冷却 %d 秒（到 %s）；到期自动恢复，也可手工删掉该文件"
                % (sec, data.get("until")))
        return data''',
    "1) load_cooldown 隔离+落盘")

# ---------------- 2) rebuild-index 提到最前（页范围/冷却/兼容性之前） ----------------
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
sub(REBUILD, "", "2) 摘出 rebuild 块")

sub('''    # 页范围校验：--pages 3 --page-from 20 这种组合会得到空区间，必须明确报错而不是静默 0 页''',
    REBUILD + '''
    # 页范围校验：--pages 3 --page-from 20 这种组合会得到空区间，必须明确报错而不是静默 0 页
    # 注意顺序：--rebuild-index 在上面已经返回 —— 它是纯本地操作，
    # 不该被页范围、冷却、json/soft_block 兼容性这些"联网前检查"挡住。''',
    "2) rebuild 前置")

P.write_text(s, encoding="utf-8", newline="\n")
print("crawler.py 两处阻断已修")

# ---------------- 3) yqwzrc_wage 的 canary 改成自己的列表页 ----------------
W = Path(str(_HOME / "crawlers" / "sites" / "yqwzrc_wage.py"))
t = W.read_text(encoding="utf-8")
old = '"canary_url": BASE + "/index.php?m=&c=Jobs&a=jobs_list&jobtag=147&page=1",'
new = ('# canary 必须是"这个模块自己列表的第 1 页"：封禁若按栏目/路径生效，\n'
       '        # 拿别的栏目的页当 canary 会误判成"还能出卡片"，从而漏判软封。\n'
       '        "canary_url": BASE + "/index.php?m=&c=Jobs&a=jobs_list&wage=" + WAGE + "&page=1",')
assert t.count(old) == 1
t = t.replace(old, new, 1)
W.write_text(t, encoding="utf-8", newline="\n")
print("yqwzrc_wage canary 已改为自己的列表页")