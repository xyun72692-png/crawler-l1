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
TARGET = AGENT / "crawlers" / "_baseline_v14_13_5"
PREV = AGENT / "crawlers" / "_baseline_v14_13_4"


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


BASELINE_MD = r"""# 基线 v14.13.5（2026-11-15 冻结 · 仓库可克隆）

## 为什么

外部 clone 后跑测试会失败，原因三件叠加：

```text
.gitignore 的 `data/` 把 tests/data 也挡了（任意层级匹配）→ 0 个文件入库
tests/test_crawler.py 里 15 处写死 D:\agent-work
另有两个 fixture 只在本机存在（foodlaw_detail1 / wzrc_probe）
```

后果：本机 clone 假绿（子进程测的是原仓库），换台机器几乎全灭。

## 改了什么

```text
.gitignore          根目录锚定（/data/ /out/ /logs/ ...）+ !tests/data/
tests/data/         入库：acceptance_15.json、qscms74_golden.json、
                    qscms74/*.html、foodlaw_detail1.html、wzrc_probe.html
test_crawler.py     ROOT = parents[1]；PY = sys.executable；15 处绝对路径清零
test_discover.py    ROOT 相对 + PY_BIN 回退 sys.executable
test_baseline_guard.py  AGENT_REAL 相对；REAL_BASE 改指活跃基线
verify/snapshot     默认 BASE / AGENT 改成相对
make_baseline_v14_13_4.py  AGENT 改成相对（后续模板）
```

## 验收

```
原地：六套 327 项（216/32/21/21/17/20）
克隆：git clone → 用同一 venv python 跑六套 → 327/327（提交说明里附结果）
```

## 回滚

```
上一版基线：crawlers\_baseline_v14_13_4（80 条）
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