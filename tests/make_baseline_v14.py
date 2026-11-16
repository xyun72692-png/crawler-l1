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
TARGET = AGENT / "crawlers" / "_baseline_v14"
PREV = AGENT / "crawlers" / "_baseline_v13"


def build_whitelist():
    wl = []
    # v14 阶段 0：identity.py 是唯一身份源，必须受基线保护
    for f in ("crawler.py", "gate.py", "robots_rules.py", "clean.py", "doctor.py",
              "identity.py"):
        wl.append(("code/" + f, "crawlers/" + f))
    for p in sorted((AGENT / "crawlers" / "sites").glob("*.py")):
        if p.name.startswith("_"):
            continue
        wl.append(("code/sites/" + p.name, "crawlers/sites/" + p.name))
    for f in ("three_votes.py", "fingerprint_offline.py", "_murmur3.py",
              "jrzp_domain_enum_v2.py", "region_map.py", "build_target_list.py",
              "pick_details.py"):
        p = AGENT / "tools" / f
        if p.exists():
            wl.append(("tools/" + f, "tools/" + f))
    wl.append(("sites/registry.json", "sites/registry.json"))
    for f in ("test_crawler.py", "test_discover.py"):
        wl.append(("tests/" + f, "tests/" + f))
    return wl


BASELINE_MD = """# 基线 v14.0（2026-11-14 冻结 · 身份统一 + 历史欠账吸收）

## 这一版新增 / 变化

| 内容 | 说明 |
|---|---|
| `crawlers/identity.py` | **唯一身份源**（v14 阶段 0）。UA / Sec-CH-UA / Sec-Fetch-* 同源；版本不同源直接抛错；`DEFAULT_VERSION="152"`、`DEFAULT_IMPERSONATE="chrome152"` |
| UA 硬编码清零 | A 层（生产 11 处）+ B 层（测试 4 处）= **0**；全部改为 `import identity`。C 层 51 处一次性探针登记不修 |
| `tools/fetch_rendered.py` | 删掉 `new_context(user_agent=UA)` 覆盖 → `new_context(**identity.for_playwright())`（真浏览器用真 UA） |
| 历史欠账吸收 | `tools/build_target_list.py`（三层新口径）、`tests/test_crawler.py`（`_UA` 走 identity）、`tests/test_discover.py` 三处改动纳入基线 |

## 与 v13.1 的差异

```
条目  37 → 38（+ identity.py）
新增受管文件  code/identity.py
源漂移  6 → 0（crawler.py / sites×2 / build_target_list.py / test×2 全部被本版吸收）
```

## 判据（沿用 v13，未变）

```
平台 = 平台资源域名引用数 >= 20（二值，不投票）
皮肤 = 路径数 + favicon → A/B/unknown
三票 = robots MD5 / favicon 字节 / 出站域名（3a 全等，3b 交集>=2 且平台域相交）
       —— 只确认皮肤，不判平台
```

## 门禁

```
python tests\\test_crawler.py        202 项 × 两轮
python tests\\test_discover.py       18 项（T1~T22）
python tests\\test_identify.py       21 项（v13.2）
python tests\\verify_baseline.py --strict --check-source
python tests\\baseline_compare.py
python tests\\test_baseline_guard.py
```

## 回滚

```
引擎快照（阶段 0 改前）：crawlers\\_engine_snapshot_pre_v14.py（186,715 字节 / 21296CABD1F9）
上一版基线：crawlers\\_baseline_v13_1（37 条，本脚本未改动它）
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