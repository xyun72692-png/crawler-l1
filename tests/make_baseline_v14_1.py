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
TARGET = AGENT / "crawlers" / "_baseline_v14_1"
PREV = AGENT / "crawlers" / "_baseline_v14"


def build_whitelist():
    wl = []
    # v14 阶段 0：identity.py 是唯一身份源，必须受基线保护
    for f in ("crawler.py", "gate.py", "robots_rules.py", "clean.py", "doctor.py",
              "identity.py", "curl_adapter.py"):
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
    for f in ("test_crawler.py", "test_discover.py", "test_transport.py"):
        wl.append(("tests/" + f, "tests/" + f))
    return wl


BASELINE_MD = """# 基线 v14.1（2026-11-14 冻结 · T1 传输层适配）

## 这一版新增

| 内容 | 说明 |
|---|---|
| `crawlers/curl_adapter.py` | **T1 适配层**（不是换 Session 类）。对外接口同 requests.Session；**每个真实请求含每跳重定向都过 gate.before()**；curl_cffi 异常包装成 requests 异常族；响应包一层补 `apparent_encoding` / `iter_content` / `close` |
| `tests/test_transport.py` | 21 项离线测试（本地 http.server）：默认仍 plain / cffi 分支 / 闸门计数 / 302 逐跳 / 响应字段 / GBK 编码 / 连接异常映射 / 流式 / transport 取值校验 |
| `CONFIG["transport"]` + `--transport {plain,cffi}` | 站点级三档：plain（默认，行为不变）/ cffi / browser（阶段 2 未接）。默认值不动 → 202 项引擎测试完全不受影响 |

## 本版验收（真实站 A/B，2026-11-14）

```
wzrc_all  1 页  plain vs cffi：记录 5 / 5，字段集一致，逐条 5/5 相同，状态都 success
foodmate  1 页  plain vs cffi：记录 20 / 20，字段集一致，逐条 20/20 相同，状态都 success
gate      requests_used 两边都 = 2（1 robots + 1 页），throttled/stopped_by 一致
编码      GBK 页（无 charset）apparent_encoding 认成 gb18030，text 解出中文
```

## 与 v14.0 的差异

```
条目  38 → 40（+ curl_adapter.py、+ test_transport.py）
引擎  crawler.py 增 CONFIG["transport"] 与 --transport，默认 plain（不改默认行为）
```

## 门禁

```
python tests\\test_crawler.py        202 项 × 两轮
python tests\\test_discover.py       18 项
python tests\\test_identify.py       21 项
python tests\\test_transport.py      21 项
python tests\\verify_baseline.py --strict --check-source
python tests\\baseline_compare.py
python tests\\test_baseline_guard.py
```

## 关键口径（别搞反）

```
transport=plain（默认）→ GatedSession.send() 拦闸门（v12 老路径，一行没改）
transport=cffi          → CurlSessionAdapter 内部逐跳调 gate.before()，语义等价
切 transport 不影响断点/去重/报告格式
```

## 回滚

```
引擎快照（阶段 0 改前）：crawlers\\_engine_snapshot_pre_v14.py（21296CABD1F9）
上一版基线：crawlers\\_baseline_v14（38 条，本脚本未改动它）
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