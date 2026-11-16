# -*- coding: utf-8 -*-
"""v13.2 判定器离线测试（T-ID-1 ~ T-ID-7）——全部 0 请求。

跑法：python tests/test_identify.py
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import identify as ID  # noqa: E402

CHDIR = ROOT / "tools" / "channels"
DATA = ROOT / "tests" / "data"
MANIFEST = DATA / "acceptance_15.json"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %-46s %s" % ("PASS" if cond else "FAIL", name, detail))


def read(p):
    """读样本：绝对路径照读；相对路径一律按 tests/data 解析。

    acceptance_15.json 里统一写相对路径（fixtures/xxx.html），这样换台机器、
    没有 D:\\agent-work 也能跑；旧数据里的绝对路径仍然兼容。
    """
    q = Path(p)
    if not q.is_absolute():
        q = DATA / q
    return q.read_text(encoding="utf-8", errors="replace")


def judge_all(network=False):
    items = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {}
    for it in items:
        card = ID.identify(
            it["url"],
            html=read(it["html"]) if it.get("html") else None,
            robots_text=read(it["robots"]) if it.get("robots") else None,
            home_html=read(it["home"]) if it.get("home") else None,
            allow_network=network,
        )
        out[it["key"]] = card
    return out


def main():
    cards = judge_all(network=False)

    # ---------------- T-ID-1 七类通道各 1 个样本 ----------------
    print("T-ID-1 通道指纹（7 类）")
    expect = {
        "wzrc": "qscms74", "njrcw": "old_asp", "rlsbt": "jpaas",
        "shuanghui": "beisen", "yili": "dayee_old",
        "wecruit": "dayee_new", "cangnan": "jrzp",
    }
    for k, want in expect.items():
        check("T-ID-1 %s → %s" % (k, want), cards[k]["channel"] == want,
              "实际 %s" % cards[k]["channel"])

    # ---------------- T-ID-2 Rule 0 一票否决 ----------------
    print("T-ID-2 Rule 0")
    for k in ("zjamr", "cti"):
        c = cards[k]
        check("T-ID-2 %s blocked" % k,
              c["status"] == "blocked" and c["capability"] == "blocked",
              "status=%s capability=%s" % (c["status"], c["capability"]))
    check("T-ID-2 命中原因非空", bool(cards["zjamr"]["rule0_hit"] or cards["cti"]["rule0_hit"]))

    # ---------------- T-ID-3 jrzp 必须写"仅首页" ----------------
    print("T-ID-3 jrzp 能力边界")
    for k in ("cangnan", "chinahzrc", "ningborcw"):
        c = cards[k]
        ok = (c["channel"] == "jrzp" and c["capability"] == "blocked"
              and "首页" in c["next_step"])
        check("T-ID-3 %s = 仅首页可抓 + 列表 blocked" % k, ok,
              "cap=%s next=%s" % (c["capability"], c["next_step"][:24]))

    # ---------------- T-ID-4 顺序短路：给了 HTML 就不许发请求 ----------------
    print("T-ID-4 短路（0 请求）")
    orig = ID.Probe._sess

    def boom(self):
        raise AssertionError("不应发请求")

    ID.Probe._sess = boom
    try:
        c = ID.identify("https://x.invalid/zhaopin.asp",
                        html=read(ROOT / "tests/data/fixtures/probe74_njrcw_zhaopin.html"),
                        allow_network=True)
        check("T-ID-4 有 HTML 时 requests_made == 0", c["requests_made"] == 0,
              "req=%d" % c["requests_made"])
    finally:
        ID.Probe._sess = orig

    # ---------------- T-ID-5 输出 schema ----------------
    print("T-ID-5 schema")
    need = ["schema_version", "rules_version", "url", "host", "status", "form", "channel",
            "transport", "capability", "confidence", "evidence", "est_volume",
            "rule0_hit", "next_step", "matched_rule"]
    st_ok = {"ok", "blocked", "unknown"}
    form_ok = {"ssr_list", "spa", "plain_api", "ats_api", "encrypted_api", ""}
    cap_ok = {"ok", "needs_v14", "blocked", "unknown"}   # unknown=没拿到页面，不是判不出
    tr_ok = {"plain", "browser", "none"}
    bad = []
    for k, c in cards.items():
        miss = [f for f in need if f not in c]
        if miss:
            bad.append("%s 缺 %s" % (k, miss))
        if c["status"] not in st_ok:
            bad.append("%s status=%s" % (k, c["status"]))
        if c["form"] not in form_ok:
            bad.append("%s form=%s" % (k, c["form"]))
        if c["capability"] not in cap_ok:
            bad.append("%s capability=%s" % (k, c["capability"]))
        if c["transport"] not in tr_ok:
            bad.append("%s transport=%s" % (k, c["transport"]))
        if not isinstance(c["evidence"], list) or not c["evidence"]:
            bad.append("%s evidence 空" % k)
        if c["confidence"] not in ("A", "B", "C"):
            bad.append("%s confidence=%s" % (k, c["confidence"]))
    check("T-ID-5 字段齐全 + 枚举合法", not bad, "; ".join(bad[:3]))
    check("T-ID-5 带版本号", all(c["schema_version"] and c["rules_version"]
                             for c in cards.values()),
          cards["wzrc"]["rules_version"])

    # ---------------- T-ID-6 规则表可扩展（代码零改动） ----------------
    print("T-ID-6 扩展性：临时加一条假通道")
    tmp = Path(tempfile.mkdtemp(prefix="channels_"))
    try:
        for p in CHDIR.glob("*.json"):
            shutil.copy(p, tmp / p.name)
        fake = {
            "id": "fake_channel", "kind": "channel", "priority": 40,
            "name": "假通道（测试用）",
            "detect": {"any": [{"html_contains": "FAKE_CHANNEL_MARKER"}]},
            "form": "ssr_list", "channel": "fake_channel", "transport": "plain",
            "capability": "ok", "est_volume": "1", "next_step": "无需", "doc": "",
        }
        (tmp / "fake_channel.json").write_text(
            json.dumps(fake, ensure_ascii=False), encoding="utf-8")
        c = ID.identify("https://x.invalid/list", html="<html><body>FAKE_CHANNEL_MARKER</body></html>",
                        allow_network=False, rules_dir=tmp)
        check("T-ID-6 新规则被识别（identify.py 未改）", c["channel"] == "fake_channel",
              "channel=%s rule=%s" % (c["channel"], c["matched_rule"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- T-ID-7 capability 三态 ----------------
    print("T-ID-7 capability")
    check("T-ID-7 jrzp 三站 = blocked（列表渲染被自毁，2026-11-14 实测）",
          all(cards[k]["capability"] == "blocked" for k in ("cangnan", "chinahzrc", "ningborcw")))
    check("T-ID-7 hzrc = needs_v14（SPA）", cards["hzrc"]["capability"] == "needs_v14",
          "form=%s" % cards["hzrc"]["form"])
    check("T-ID-7 两 WAF 站 = blocked",
          all(cards[k]["capability"] == "blocked" for k in ("zjamr", "cti")))

    # ---------------- 附加：代码里不许出现具体域名 ----------------
    print("附加 代码零域名")
    dom = re.compile(r"[\w-]+\.(?:com|cn|net|gov\.cn|org)\b", re.I)
    offenders = []
    for f in ("identify.py", "discover.py"):
        src = read(ROOT / "tools" / f)
        # 允许的只是正则/注释里的通配，真实域名会以 xxx.com 形式出现
        hits = [m.group(0) for m in dom.finditer(src)
                if m.group(0).lower() not in ("gov.cn", "x.invalid")]
        if hits:
            offenders.append("%s: %s" % (f, hits[:3]))
    check("附加 identify.py/discover.py 无具体域名", not offenders, "; ".join(offenders))

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())