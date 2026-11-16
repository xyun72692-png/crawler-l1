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
TARGET = AGENT / "crawlers" / "_baseline_v14_13"
PREV = AGENT / "crawlers" / "_baseline_v14_12_1"


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
    acc = "tests/data/acceptance_15.json"
    if (AGENT / acc).exists():
        wl.append((acc, acc))
    return wl


BASELINE_MD = r"""# 基线 v14.13（2026-11-15 冻结 · robots 四态 fail-closed）

## 为什么有这一版

发现并复现了一个 fail-open：`/robots.txt` 返回 200 但内容是 HTML（WAF 挑战页 / 软 404）时，
旧实现只看状态码 → 解析出 0 组规则 → **任意 URL 全放行**。
实测原值：lagou 的 WAF 页 11027 字符 → `decide() = (True, '', 0)`；
真 robots 90 字节 → `(False, 'Disallow: /*?*', 第 5 行)`。

项目语料里 23 个主机有 5 个的 robots.txt 实际是 HTML（约 22%），
其中含两个政府站（rlsbt / zjamr）和一个 552 字节的小 HTML ——
**用「体积 >10KB」的判法会漏掉后者**。

## 这一版改了什么

| # | 内容 | 落点 |
|---|---|---|
| 1 | `classify_robots()` 四态：absent / ok / denied / unparsable | `crawlers/robots_rules.py` |
| 2 | 主页面 robots 走四态，unparsable → fail-closed + 打印首行 | `crawler.load_robots` |
| 3 | **附件** robots 同样走四态（旧实现同样 fail-open） | `crawler.origin_robots` |
| 4 | 渲染通道：403/5xx/异常/HTML 全部拒绝（旧实现取不到就放行） | `render_batch.robots_allows` |
| 5 | 探测工具：200+HTML 判「不可接」 | `tools/probe_one.py` |
| 6 | 报告新增 `robots.status / bytes / groups` | `write_report` |
| 7 | 页脚过滤按 F-14：锚文本 2~12 字 + 外链，删掉 `rc./rcw./job` 域名子串 | `tools/discover.py` |
| 8 | F-22 计数：未执行检索时明确打印「漏项」 | `discover.main` |

## 判据（写死）

```
404                      -> absent     放行
401/403/5xx/其它非 200    -> denied     拒绝
200 且正文以 < 开头       -> unparsable 拒绝（fail-closed）
200 且 content-type=html 但正文含 robots 指令 -> ok（实测有服务器标错类型）
200 空 / 纯注释           -> ok
```

## 门禁

```
test_crawler 214 ｜ test_discover 30 ｜ test_identify 21 ｜ test_transport 21
test_rule0 17 ｜ test_render_batch 20          = 六套 323 项
```

## 回滚

```
上一版基线：crawlers\_baseline_v14_12_1（75 条）
改前源码备份：logs\_pre_v14_13\（8 个文件）
引擎上一版：crawlers\_baseline_v14_12_1\code\crawler.py
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