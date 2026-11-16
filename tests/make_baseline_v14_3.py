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
TARGET = AGENT / "crawlers" / "_baseline_v14_3"
PREV = AGENT / "crawlers" / "_baseline_v14_2"


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
              "render_selfcheck.py", "render_batch.py",
              "identify.py", "discover.py",
              "jrzp_domain_enum_v2.py", "region_map.py", "build_target_list.py",
              "pick_details.py"):
        p = AGENT / "tools" / f
        if p.exists():
            wl.append(("tools/" + f, "tools/" + f))
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


BASELINE_MD = """# 基线 v14.3（2026-11-14 冻结 · T2 批量渲染 + v13.2 工具纳管）

## 这一版新增

| 内容 | 说明 |
|---|---|
| `tools/render_batch.py` | T2 批量渲染：一次启动 N 次导航；**导航计入 gate，子资源不计但受 单页≤80 / 累计≤4000 双上限**；逐页 robots（`robots_rules.decide`）；Rule 0 先行；落盘 `_rendered/<job>/pN.html`；报告复用 `crawler.write_report` |
| `tests/test_render_batch.py` | 18 项离线测试（本地 mock JS 渲染页）：两页抽取 / 导航计数 / 子资源与拦截计数 / 授权例外开关 / terms=blocked 不打浏览器 / 代码零域名 |
| `sites/mockrender.py` | 渲染测试夹具（parse_list 从渲染后 DOM 取 `a.job`） |
| `sites/jrzp_list.py` | jrzp 列表渲染模块 —— **已标注当前不可用**（实测页面自毁） |
| `tools/identify.py` / `tools/discover.py` / `tools/channels/*.json` | v13.2 的判定器与规则表**首次纳入基线保护**（之前只存在于工作区） |
| `tests/test_identify.py` + `tests/data/acceptance_15.json` | 15 站验收清单与 21 项断言 |

## 关键实测（2026-11-14）

```
render_batch 离线（mock JS 页）：2 页 → 6 条，导航 2、子资源 8（均 4.0）、拦截 4（默认拦 image/font/media）
render_batch 真站（jrzp_list / chinahzrc）：
   导航 200，但页面随即刷成 about:blank（console.clear + 自毁），html 只剩 39 字节
   headless 与 headed 两条通道都一样 → 判定"站点反自动化"
   按 Rule 0 红线不升级对抗 → channels/jrzp.json 从 needs_v14 改为 **blocked**
```

## 口径（写死）

```
导航 vs 子资源：gate 只数导航（1 goto = 1）；子资源另设 单页 ≤80 / 累计 ≤4000
资源拦截：默认拦 image/font/media（不拦 CSS/JS）；被拦的单独计 subresources_blocked
自毁识别：html < 200 且 url 以 about: 开头 → anomaly=page_self_destructed，立即停
最薄一层：只取 detail URL + 标题；详情与附件一律回 plain
```

## 与 v14.2 的差异

```
条目  44 → 69（+ render_batch、mockrender、jrzp_list、identify、discover、13 条 channels、
              test_identify、test_render_batch、acceptance_15）
```

## 门禁

```
test_crawler 202 ｜ test_discover 18 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18
verify --strict --check-source ｜ baseline_compare 49 项 ｜ test_baseline_guard 12
```

## 回滚

```
引擎快照（阶段 0 改前）：crawlers\\_engine_snapshot_pre_v14.py（21296CABD1F9）
上一版基线：crawlers\\_baseline_v14_2（44 条，本脚本未改动它）
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