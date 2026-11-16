# -*- coding: utf-8 -*-
"""
建立 _baseline_v13（v13：发现能力建设）。

硬规矩（上次 v11 被覆盖的教训）：
  1 目标目录已存在 → 直接报错退出，**绝不覆盖**
  2 支持 --dry-run：只打印目标路径 + 将写入的条目，不动磁盘
  3 白名单制：只纳入 10 个文件，临时探测脚本一律不进
  4 全程不碰 _baseline_v12（只读）

用法：
    python tests\\make_baseline_v13.py --dry-run
    python tests\\make_baseline_v13.py
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
TARGET = AGENT / "crawlers" / "_baseline_v13"
PREV = AGENT / "crawlers" / "_baseline_v12"      # 只读参照，不修改

# 白名单：rel_in_baseline ← 源文件
WHITELIST = [
    ("code/crawler.py", "crawlers/crawler.py"),
    ("code/gate.py", "crawlers/gate.py"),
    ("code/robots_rules.py", "crawlers/robots_rules.py"),
    ("tools/three_votes.py", "tools/three_votes.py"),
    ("tools/fingerprint_offline.py", "tools/fingerprint_offline.py"),
    ("tools/_murmur3.py", "tools/_murmur3.py"),
    ("tools/jrzp_domain_enum_v2.py", "tools/jrzp_domain_enum_v2.py"),
    ("sites/registry.json", "sites/registry.json"),
    ("tests/test_crawler.py", "tests/test_crawler.py"),
    ("tests/test_discover.py", "tests/test_discover.py"),
]

BASELINE_MD = """# 基线 v13（2026-11-13 冻结 · 发现能力建设）

## 这一版是什么

引擎（v12.3 的闸门 + 四阶段穿透 + 两段式）**一行未改**；
v13 新增的是**发现能力**：怎么找到新站、怎么判它是不是同一家、值不值得接。

| 文件 | 作用 |
|---|---|
| `tools/_murmur3.py` | 纯 Python murmur3_32 + `base64.encodebytes` + `favicon_hash`（口径：b64 **带换行**） |
| `tools/fingerprint_offline.py` | 离线指纹：出站域名（全量 + top）、资源域名、静态路径、favicon、`subdomains_of_self`、`resolve_city`（锚文本） |
| `tools/three_votes.py` | **平台与皮肤分轴**：平台=平台资源域名引用数（≥20 → jrzp）；皮肤=A/B；三票仅确认皮肤 |
| `tools/jrzp_domain_enum_v2.py` | 域名语法枚举（**www 优先、禁 apex 聚类、共享 IP 排除**），只发 DNS |
| `sites/registry.json` | 66 条台账（url 唯一 / status 三值 / 每条带 discovered_by + evidence） |

## 三条钉死的判据

```
1 平台 = 平台资源域名（img.jrzp.com / jrzp.com 系）引用数 >= 20     ← 二值，不投票
2 皮肤 = 路径数 + favicon → A（>=120 且 0de05b2a）/ B（<=110 且非 A）/ unknown
3 三票 = robots MD5 / favicon 字节 / 出站域名（3a 全等，3b 交集>=2 且平台域相交）
   —— 只用于"皮肤一致性"，**不用于判平台**
```

## 两个必须记住的坑

1. **apex 是停放页**：省级站/城市站的 apex 全在 `203.107.45.167`，只有 `www.` 才是真站；
   **IP 簇不能跨时间比较**（实测同一批域名 23:0x 前后解析完全不同）。
2. **判据不能读被截断的展示字段**：`outbound_hosts` top40 曾把 `beian.miit.gov.cn`（排名第 88）截掉，
   导致 3b 误判为否；判据必须用 `outbound_all`。

## 门禁

```
python tests\\test_crawler.py       202 项 × 两轮
python tests\\test_discover.py      12 项（T1~T16）
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
    print("目标目录：%s" % TARGET)
    print("参照（只读）：%s" % PREV)
    if TARGET.exists():
        print("!! 目标目录已存在 → 拒绝执行（绝不覆盖）")
        return 3

    missing = [src for _, src in WHITELIST if not (AGENT / src).exists()]
    print("白名单 %d 个；缺源文件 %d 个 %s" % (len(WHITELIST), len(missing), missing or ""))
    if missing:
        return 4

    if dry:
        print("--- dry-run：将写入 ---")
        for rel, src in WHITELIST:
            p = AGENT / src
            print("  %-34s ← %-40s %7d 字节" % (rel, src, p.stat().st_size))
        print("--- dry-run 结束，未改任何文件 ---")
        return 0

    rows, problems = [], []
    for rel, src_rel in WHITELIST:
        src = AGENT / src_rel
        dst = TARGET / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        hs, hd = md5_of(src), md5_of(dst)
        if hs != hd:
            problems.append("哈希不一致: %s" % rel)
        rows.append({
            "rel": rel, "src_rel": src_rel,
            "bytes": dst.stat().st_size,
            "lastwrite": datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "md5_source": hs, "md5_copy": hd,
            "verify": "OK" if hs == hd else "MISMATCH",
        })

    with open(TARGET / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "src_rel", "bytes", "lastwrite",
                                         "md5_source", "md5_copy", "verify"])
        w.writeheader()
        w.writerows(rows)

    (TARGET / "baseline.md").write_text(BASELINE_MD, encoding="utf-8")

    total = sum(r["bytes"] for r in rows)
    print("条目 %d / 字节 %d" % (len(rows), total))
    print("manifest → %s" % (TARGET / "manifest.csv"))
    if problems:
        print("!! 问题:", problems)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())