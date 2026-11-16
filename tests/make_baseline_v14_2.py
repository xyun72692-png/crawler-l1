# -*- coding: utf-8 -*-
"""
建立 _baseline_v13_1（v13.1：foodmate 接入 + 扩展白名单）。

与 v13 的区别：
  · 白名单从 10 → 约 36：把站点模块（sites/*.py）、clean.py、doctor.py、
    tools（three_votes / fingerprint_offline / _murmur3 / jrzp_domain_enum_v2 /
    region_map / pick_details）、registry、两份测试全纳入
  · registry 里 foodmate 状态由 待接入 → 已验证

硬规矩（沿用 v13）：
  1 目标目录已存在 → 直接退出，不覆盖
  2 --dry-run 只打印不动盘
  3 不碰 _baseline_v12 / _baseline_v13

用法：
    python tests\\make_baseline_v13_1.py --dry-run
    python tests\\make_baseline_v13_1.py
"""
import csv
import hashlib
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AGENT = Path(r"D:\agent-work")
TARGET = AGENT / "crawlers" / "_baseline_v14_2"
PREV = AGENT / "crawlers" / "_baseline_v14_1"


def build_whitelist():
    wl = []
    # v14 阶段 0：identity.py 是唯一身份源，必须受基线保护
    for f in ("crawler.py", "gate.py", "robots_rules.py", "clean.py", "doctor.py",
              "identity.py", "curl_adapter.py", "stealth.py", "rule0.py"):
        wl.append(("code/" + f, "crawlers/" + f))
    for p in sorted((AGENT / "crawlers" / "sites").glob("*.py")):
        if p.name.startswith("_"):
            continue
        wl.append(("code/sites/" + p.name, "crawlers/sites/" + p.name))
    for f in ("three_votes.py", "fingerprint_offline.py", "_murmur3.py",
              "render_selfcheck.py",
              "jrzp_domain_enum_v2.py", "region_map.py", "build_target_list.py",
              "pick_details.py"):
        p = AGENT / "tools" / f
        if p.exists():
            wl.append(("tools/" + f, "tools/" + f))
    wl.append(("sites/registry.json", "sites/registry.json"))
    for f in ("test_crawler.py", "test_discover.py", "test_transport.py",
              "test_rule0.py"):
        wl.append(("tests/" + f, "tests/" + f))
    return wl


BASELINE_MD = """# 基线 v14.2（2026-11-14 冻结 · 渲染自检 + Rule 0）

## 这一版新增

| 内容 | 说明 |
|---|---|
| `tools/render_selfcheck.py` | §4.1.1 六项自检（webdriver / UA与CH-UA同源 / WebGL非软渲染 / plugins / 与真Chrome四项 / JS执行）。用本地回显服务读**请求头**，不靠 `navigator.userAgentData` |
| `crawlers/stealth.py` | 薄封装：去 `--enable-automation`、关 Blink AutomationControlled、init script 置 `navigator.webdriver=false`。**不做** WebGL/Canvas/字体伪造 |
| `crawlers/rule0.py` | Rule 0：`terms_status` 三态（unknown 默认不抓）+ 统一决策块 + jrzp 点对点授权例外（三道闸）+ 报告四字段 |
| `tests/test_rule0.py` | 17 项离线测试（三态 / CLI 覆盖 / 授权三闸 / 决策块 / rc=2 / 防漏标） |
| 站点标注 | 9 个业务站 + 测试夹具共 22 个站点模块标 `terms_status: "allowed"`；`cangnan_home` 另加 `platform: "jrzp"` |
| `identity.py` | 新增 `for_playwright_actual(browser_version)` / `playwright_identity()`；渲染通道按**真实浏览器版本**生成 UA+Sec-CH-UA（本机 157），不再沿用 T1 的 152 |

## 自检结果（2026-11-14，6/6 通过）

```
① webdriver=False
② js_UA=157 / hdr_UA=157 / CH-UA=157 / 真实=157
③ WebGL: ANGLE (Intel, Intel(R) Arc(TM) Graphics) —— 非软渲染
④ plugins=5
⑤ 与真 Chrome 四项全同（主版本/品牌/语言/时区）
⑥ JS 能执行（setTimeout 写 DOM → js-ok）
```

## Rule 0 口径（写死）

```
terms_status=unknown（缺省）→ 不抓，打印决策块，rc=2，0 请求   ← fail-closed
terms_status=blocked        → 同上，reason=blocked_terms
terms_status=allowed        → 放行
CLI --terms-status 临时覆盖（留痕）
jrzp 授权例外三道闸：① --allow-robots-js ② 站点 CONFIG.render_authorized(by/at)
                     ③ platform ∈ {"jrzp"}
                     全满足才 robots_override=True / scope=js/css / max_pages=20
报告字段：terms_status / robots_override / override_scope / authorized_by / authorized_at
```

## 与 v14.1 的差异

```
条目  40 → 44（+ stealth.py、rule0.py、test_rule0.py、tools/render_selfcheck.py）
站点  22 个模块标 terms_status=allowed（cangnan_home 另标 platform=jrzp）
引擎  crawler.py：Rule 0 判定前置（0 请求前）+ 报告字段 + --terms-status/--allow-robots-js
```

## 门禁

```
test_crawler 202 ｜ test_discover 18 ｜ test_identify 21 ｜ test_transport 21 ｜ test_rule0 17
verify --strict --check-source ｜ baseline_compare 49 项 ｜ test_baseline_guard 12
```

## 回滚

```
引擎快照（阶段 0 改前）：crawlers\\_engine_snapshot_pre_v14.py（21296CABD1F9）
上一版基线：crawlers\\_baseline_v14_1（40 条，本脚本未改动它）
```
"""


def md5_of(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    dry = "--dry-run" in sys.argv
    wl = build_whitelist()
    print("目标目录：%s" % TARGET)
    print("参照（只读）：%s" % PREV)
    if TARGET.exists():
        print("!! 目标目录已存在 → 拒绝执行（绝不覆盖）")
        return 3
    missing = [s for _, s in wl if not (AGENT / s).exists()]
    print("白名单 %d 个；缺源文件 %d %s" % (len(wl), len(missing), missing or ""))
    if missing:
        return 4
    if dry:
        for rel, src in wl:
            print("  %-40s ← %-44s %7d 字节" % (rel, src, (AGENT / src).stat().st_size))
        print("--- dry-run 结束，未改任何文件 ---")
        return 0

    rows, problems = [], []
    for rel, src_rel in wl:
        src = AGENT / src_rel
        dst = TARGET / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        hs, hd = md5_of(src), md5_of(dst)
        if hs != hd:
            problems.append(rel)
        rows.append({"rel": rel, "src_rel": src_rel, "bytes": dst.stat().st_size,
                     "lastwrite": datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                     "md5_source": hs, "md5_copy": hd,
                     "verify": "OK" if hs == hd else "MISMATCH"})
    with open(TARGET / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "src_rel", "bytes", "lastwrite",
                                          "md5_source", "md5_copy", "verify"])
        w.writeheader()
        w.writerows(rows)
    (TARGET / "baseline.md").write_text(BASELINE_MD, encoding="utf-8")
    print("条目 %d / 字节 %d" % (len(rows), sum(r["bytes"] for r in rows)))
    if problems:
        print("!! 哈希不一致:", problems)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())