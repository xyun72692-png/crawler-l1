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

AGENT = Path(__file__).resolve().parent.parent
TARGET = AGENT / "crawlers" / "_baseline_v14_13_4"
PREV = AGENT / "crawlers" / "_baseline_v14_13_3"


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
    for p in sorted((AGENT / "crawlers" / "sites" / "families").glob("*.py")):
        if p.name.startswith("_"):
            continue
        wl.append(("code/sites/families/" + p.name,
                   "crawlers/sites/families/" + p.name))
    for f in ("three_votes.py", "fingerprint_offline.py", "_murmur3.py",
              "render_selfcheck.py", "render_batch.py", "identify_batch.py",
              "identify.py", "discover.py", "probe_one.py",
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
    wl.append(("tests/mock_site.py", "tests/mock_site.py"))
    for extra in ("tests/data/qscms74_golden.json",):
        if (AGENT / extra).exists():
            wl.append((extra, extra))
    acc = "tests/data/acceptance_15.json"
    if (AGENT / acc).exists():
        wl.append((acc, acc))
    return wl


BASELINE_MD = r"""# 基线 v14.13.4（2026-11-15 冻结 · 74cms 家族抽取）

## 为什么

wzrc_all / wzrc_inc / yqwzrc / yqwzrc_wage 四个模块的 parse_list 几乎逐行相同，
只差「地区前缀保留与否」和「source_site 文案」。复制四份 → 改一处要改四处。

## 改了什么

```text
新增  crawlers/sites/families/qscms74.py
        parse_jobs(html, page_url, source_site, keep_area)
改    wzrc_all.py / yqwzrc.py / yqwzrc_wage.py
        parse_list 缩成 3 行调用；config 与筛选参数不动
       wzrc_inc.py 本来就复用 wzrc_all.parse_list，不动
新增  tests/data/qscms74/<4 个站>_p1.html     真实列表页样本（共约 325 KB）
新增  tests/data/qscms74_golden.json          重构前输出（每站 5 条）
新增  test_crawler 6e                        4 个站重跑同一批 HTML，与 golden 逐字节一致
```

## 黄金样本（2026-11-15 抓，6 个请求：2 robots + 4 页）

```
wzrc_all      5 条
wzrc_inc      5 条
yqwzrc        5 条
yqwzrc_wage   5 条
比对含字段顺序：equal=True / key_order=True
```

顺手验证了 robots 四态的一个真实场景：两个站的 /robots.txt 都是 **404 + 3KB HTML**
（软 404）——按 404=absent 处理才对，按"内容像 HTML 就拒"会误杀。

## 门禁

```
test_crawler 216 ｜ test_discover 32 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 20          = 六套 327 项
```

## 回滚

```
上一版基线：crawlers\_baseline_v14_13_3（78 条）
单文件回滚：三个站点模块的 parse_list 恢复成各自原实现（见 git v14.13.3）
```
"""


def kind_of(rel):
    """code / data：strict 只对 code 判失败，data 只报告 + 校验 JSON 可解析。"""
    rel = rel.replace("\\", "/")
    if rel.startswith("code/"):
        return "code"
    if rel.startswith("tools/") and rel.endswith(".py"):
        return "code"
    if rel.startswith("tests/") and not rel.startswith("tests/data/"):
        return "code"
    return "data"


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
        rows.append({"rel": rel, "src_rel": src_rel, "kind": kind_of(rel), "bytes": dst.stat().st_size,
                     "lastwrite": datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                     "md5_source": hs, "md5_copy": hd,
                     "verify": "OK" if hs == hd else "MISMATCH"})
    with open(TARGET / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "src_rel", "kind", "bytes", "lastwrite",
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