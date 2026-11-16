# -*- coding: utf-8 -*-
"""
建立 _baseline_v14_12（A5：window 模式断点加时间维度）。

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
TARGET = AGENT / "crawlers" / "_baseline_v14_12"
PREV = AGENT / "crawlers" / "_baseline_v14_11"


def build_whitelist():
    wl = []
    # v14 阶段 0：identity.py 是唯一身份源，必须受基线保护
    for f in ("crawler.py", "gate.py", "robots_rules.py", "clean.py", "doctor.py",
              "identity.py", "curl_adapter.py", "stealth.py", "rule0.py",
              "timeline.py"):
        wl.append(("code/" + f, "crawlers/" + f))
    for p in sorted((AGENT / "crawlers" / "sites").glob("*.py")):
        if p.name.startswith("_"):
            continue
        wl.append(("code/sites/" + p.name, "crawlers/sites/" + p.name))
    for f in ("three_votes.py", "fingerprint_offline.py", "_murmur3.py",
              "render_selfcheck.py", "render_batch.py", "identify_batch.py",
              "identify.py", "discover.py",
              "jrzp_domain_enum_v2.py", "region_map.py", "build_target_list.py",
              "pick_details.py"):
        p = AGENT / "tools" / f
        if p.exists():
            wl.append(("tools/" + f, "tools/" + f))
    # v14.7：发现阶段的判据数据（discover.py 依赖它们，必须一起纳管）
    for p in sorted((AGENT / "tools" / "geo").glob("*.json")):
        wl.append(("tools/geo/" + p.name, "tools/geo/" + p.name))
    wl.append(("sites/registry.json", "sites/registry.json"))
    for p in sorted((AGENT / "tools" / "channels").glob("*.json")):
        wl.append(("tools/channels/" + p.name, "tools/channels/" + p.name))
    for f in ("test_crawler.py", "test_discover.py", "test_transport.py",
              "test_rule0.py", "test_identify.py", "test_render_batch.py"):
        wl.append(("tests/" + f, "tests/" + f))
    acc = "tests/data/acceptance_15.json"
    if (AGENT / acc).exists():
        wl.append((acc, acc))
    return wl


BASELINE_MD = r"""# 基线 v14.12（2026-11-15 冻结 · A5：断点加时间维度）

## 这一版解决什么问题（A5）

```
滚动时间窗（settr=3 + sort=rtime）+ 页码断点 = 永远看不到新数据
  新岗位永远出现在第 1 页顶部
  而第 1 页永远"已完成" → 跳过 → 一个请求都不发
```

## 改了什么（最小版，六件）

| # | 内容 | 落点 |
|---|---|---|
| 1 | `pages_done` 加日期戳 | `st["pages_done_at"] = {页码: 'YYYY-MM-DD'}`；`blank_state()` 补默认键 |
| 2 | window 跨天作废，full 保持续跑 | `load_state()` 之后、`pages_done = set(...)` 之后判 `coverage_mode()` |
| 3 | 每次只重抓前 3 页 | `work` 构造时 `page_end = min(page_end, page_start + refresh_pages - 1)` |
| 4 | `seen_keys` 去重 | 复用既有去重前置（未改） |
| 5 | 连续 N 条都见过就提前停 | 跨页累计 `window_consec_dup`，达 `refresh_stop_after_dups` → `stop_reason=refresh_no_new` |
| 6 | 跨天后第 1 页必须重抓 | 用例 209（window）/ 210（full 对照） |

## 语义边界（别搞混）

```
window：断点只认「当天」，跨天作废；覆盖不全属设计如此（不给 coverage=1.0 的假象）
full  ：完全没有时间维度，照旧续跑（用例 210 钉死这一点，window 不污染 full）
```

**阈值 20 的数学提醒**：`refresh_pages=3` × 5 条/页 = 15 条 < 20，
所以当前配置下"连续 20 条提前停"**不会触发**；它是把 refresh_pages 调大时的安全阀。

## 站点配置

`wzrc_inc`：`coverage_mode="window"` + `refresh_pages=3` + `refresh_stop_after_dups=20`。
（11-11 曾裁定"不配 coverage_mode"，那针对一次性快照语义；11-15 按滚动时间窗改判，注释已写清。）

## 新增夹具

`crawlers/sites/mockwindow.py`：与 `mock.py` 同一个假站，只多三个 window 配置项。
它是 window 语义的唯一可执行说明书；`terms_status` 必须显式写（Rule 0 静态检查看不见继承）。

## 门禁

```
test_crawler 210 ｜ test_discover 29 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 316 项
```

## 回滚

```
上一版基线：crawlers\_baseline_v14_11（74 条）
本版源码差异：crawlers/crawler.py（A5 六处）+ sites/wzrc_inc.py + sites/mockwindow.py（新）+ tests/test_crawler.py
A5 之前的引擎：crawlers\_baseline_v14_11\code\crawler.py
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