# -*- coding: utf-8 -*-
"""
建立 _baseline_v14_12_1（A5 补丁：window 每轮重抓 + 阈值 15）。

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
TARGET = AGENT / "crawlers" / "_baseline_v14_12_1"
PREV = AGENT / "crawlers" / "_baseline_v14_12"


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


BASELINE_MD = r"""# 基线 v14.12.1（2026-11-15 冻结 · A5 补丁：window 每轮重抓）

## 为什么有这一版（v14.12 的问题）

v14.12 的 window 只做到「**跨天**作废」。同一天第二次跑时，第 1 页在这一轮之前刚被抓过、
日期戳还是今天 → 仍然"有效" → 又被跳过 → **一个请求都不发**。
病根没除，只是把复发周期从"每次"推到了"每天一次"。

## 这一版改了什么

| # | 内容 | 落点 |
|---|---|---|
| 1 | window **每轮清空 pages_done** | `load_state()` 之后无条件 `pages_done = set()`；同一天第二次跑也重抓 |
| 2 | 阈值 `refresh_stop_after_dups` 20 → **15** | `refresh_pages=3` × 5 条/页 = 15 条，正好够得着（20 时永远不触发） |
| 3 | 提前停检查移到 `pages_ok += 1` **之后** | 否则提前停的那一页不算"处理完"，计数少一页 |
| 4 | `refresh_no_new` 进白名单 | 它是 window 的正常收工（这轮没新数据），不是翻页异常，不能被判 partial |
| 5 | success 时带出 `refresh_no_new` | 报告 reason 能看到"为什么提前收工" |
| 6 | 夹具新增 `/v5/pN.html`（每页 5 条） | 默认 v1 每页 3 条，3 页才 9 条，够不到 15 |

## 语义（写死）

```
window：每轮清空页码断点 → 重抓前 refresh_pages 页 → 靠 seen_keys 去重
        "覆盖不全"是设计如此；没新数据时 status=success + reason=refresh_no_new
full  ：完全没有时间维度，照常续跑（用例 210 钉死）
seen_keys 不清（它跟页码无关，是真正的"抓过没有"）
```

## 四条 A5 用例

```
209  window 跨天        → 断点作废、第 1 页重抓（跳过=0）
210  full 跨天          → 断点保留、照旧 noop（window 不污染 full）
211  window 同天连跑两次 → 第二次 total=3 / ok=3 / skipped=0 / new=0，不是 noop
212  3 页全重复          → reason=refresh_no_new、dup=15、ok=3、仍 success
```

## 门禁

```
test_crawler 212 ｜ test_discover 29 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 318 项
```

## 回滚

```
上一版基线：crawlers\_baseline_v14_12（75 条）
本版源码差异：crawlers/crawler.py + sites/wzrc_inc.py + sites/mockwindow.py + tests/mock_site.py + tests/test_crawler.py
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