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
TARGET = AGENT / "crawlers" / "_baseline_v13_1"
PREV = AGENT / "crawlers" / "_baseline_v13"


def build_whitelist():
    wl = []
    for f in ("crawler.py", "gate.py", "robots_rules.py", "clean.py", "doctor.py"):
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


BASELINE_MD = """# 基线 v13.1（2026-11-14 冻结 · foodmate 接入完成）

## 这一版新增

| 内容 | 说明 |
|---|---|
| `crawlers/sites/foodmate.py` | 食品伙伴网·食品人才中心（DESTOON B2B）。GBK、20 条/页、245 页；**禁 search.php**，地区筛选只能本地做 |
| `tools/region_map.py` | 市→省映射（浙江 11+29、江苏 13+35），取不到返回空、不猜 |
| `tools/build_target_list.py` | 三层清单（A 可直接投 / B 需人工看 / C 备选） |
| registry | foodmate `待接入 → 已验证`；66 条 |

## 实测数字（2026-11-14 全量跑）

```
foodmate 全量 245 页 / 4,888 条（两批，246 请求，0 失败）
字段非空：title/salary/region/exp/edu 均 100%，company 99.9%
浙江+江苏 659 条（13.5%）→ 岗位族命中 158 条
三层（薪资>=4500）：A 11 / B 76 / C 370
面议（薪资未知）但岗位族+行业命中：21 条（B 层最高优先）
```

## 判据（沿用 v13）

```
平台 = 平台资源域名引用数 >= 20（二值，不投票）
皮肤 = 路径数 + favicon → A/B/unknown
三票 = robots MD5 / favicon 字节 / 出站域名（3a 全等，3b 交集>=2 且平台域相交）
       —— 只确认皮肤，不判平台
```

## 门禁

```
python tests\\test_crawler.py        202 项 × 两轮
python tests\\test_discover.py       14 项（T1~T18）
python tests\\verify_baseline.py --strict
python tests\\baseline_compare.py
python tests\\test_baseline_guard.py
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