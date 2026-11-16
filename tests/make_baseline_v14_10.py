# -*- coding: utf-8 -*-
"""
建立 _baseline_v14_10（v13.7：A6 判定集中化，纯重构零行为变化）。

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
TARGET = AGENT / "crawlers" / "_baseline_v14_10"
PREV = AGENT / "crawlers" / "_baseline_v14_9"


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


BASELINE_MD = r"""# 基线 v14.10（2026-11-15 冻结 · A6：判定集中化，纯重构）

## 这一版做了什么

**只重构，不改行为。** 312 项测试一项没动、全部通过。

| 内容 | 说明 |
|---|---|
| `beyond_declared(page, pages_declared)` | "页码是否超出站点声明的总页数 M" 的**唯一**判定点。原来这表达式散在 4 处（进循环前剔除 / 循环内发现 M 后剔除 / 两处 `pages_done.add` 前），改一处容易漏另外三处 |
| `page_done(page, pages_done)` | "断点里是否已完成"的**唯一**判定点。原来循环里直接写 `page in pages_done` |
| 替换 7 处调用 | 4 处 `p>X` + 2 处 `page>ctx["pages_declared"]` + 1 处循环跳过；字符 161,738 → 161,707 |

## 语义边界（写清楚，防止后来人误解）

```
beyond_declared  → 只决定「记不记断点 / 报不报覆盖率」，**不决定「这一页抓不抓」**
page_done        → 才决定「跳过还是发请求」；它不看 M
```

所以 noop 续跑仍会多发 1 个请求去确认 M —— 这是**已知代价**，属于 A6 里"不改行为"的保留项，
真正的修法在 A5（pages_done 加时间维度 + window 模式）那一批里一起处理。

## 为什么值得单独冻一版

判定散在 4 处时，"改判定"要同时改 4 个地方且必须保持一致；
集中成 2 个函数后，A5 改 window 模式只需改 `page_done()` 一处，测试能立刻告诉你有没有改坏。

## 门禁

```
test_crawler 208 ｜ test_discover 27 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 312 项
```

## 回滚

```
上一版基线：crawlers\_baseline_v14_9（74 条）
本版源码差异：crawlers/crawler.py（只加两个谓词 + 换 7 处调用）
重构前的引擎副本：logs\_crawler_before_a6.py
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