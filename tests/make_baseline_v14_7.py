# -*- coding: utf-8 -*-
"""
建立 _baseline_v14_7（v13.1：foodmate 接入 + 扩展白名单）。

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
TARGET = AGENT / "crawlers" / "_baseline_v14_7"
PREV = AGENT / "crawlers" / "_baseline_v14_6"


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


BASELINE_MD = r"""# 基线 v14.7（2026-11-15 冻结 · 发现阶段补「检索 + 官方名录」）

## 这一版新增

| 内容 | 说明 |
|---|---|
| `tools/discover.py` | 主流程改成 **⓪检索 → ①官方名录 → ②页脚/友链 → ③域名语法+DNS → ④枚举表抽样 → ⑤seed**；新增 `--print-queries` / `--search-result` / `--from-enum --b-sample` |
| `tools/geo/gov_platforms.json` | 33 键 / 36 条官方平台；`coverage` 三态（unified / fragmented / unknown） |
| `tools/geo/search_queries.json` | 检索模板（招聘/法规/价格/天气），**不含任何具体域名** |
| `tools/geo/cities.json` / `patterns.json` | 城市表与域名模板；本次一并纳管（此前只在工作区） |
| `tests/test_discover.py` | 18 → **23 项**：补 T23~T27（B 档抽样可复现 / 缩写歧义 / concat 拼接 / 模板去重 / 官方名录并入） |

## 修掉的三个真 bug

```
① 域名拼接 dot -> concat
   {pinyin}+".rc.com" = hangzhou.rc.com（永远不存在） -> 白猜
   {pinyin}+"rc.com"  = hangzhourc.com / zjhr.com     -> 真站
② 省级模板缺失：v13 没有 {省}hr.com 这一档 -> zjhr.com 永远生成不出来
③ 缩写歧义单选：zj 被判成「镇江」-> zjrc.com 落 B 档被丢
   现在 owners=[浙江,镇江] + ambiguous=True，两条都保留
```

## 口径（写死）

```
检索第一：没有候选源时先跑检索模板，不是先猜域名
名录第二：读 gov_platforms.json；找某类官方源先找主管部门名单页
B 档不许全丢：--b-sample N（固定种子 0，可复现）
歧义不单选：ambiguous=True 时 owners 全部保留
检索结果不许直接信：搜到只是候选，必须 1 请求验（title/岗位链接/robots）
```

## 门禁

```
test_crawler 202 ｜ test_discover 23 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 18          = 六套 302 项
```

## 回滚

```
上一版基线：crawlers\_baseline_v14_6（69 条）
引擎快照（v14 阶段 0 改前）：crawlers\_engine_snapshot_pre_v14.py
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