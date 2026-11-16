# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
阶段1 · 真站 A/B：旧 detail_hook vs 新通用流程，40 条逐条比对。

做法：用同一个站点（foodlaw）、同样 2 页，各跑一遍，
      --job 不同 → 数据落到不同文件，互不去重；
      --detail-mode 不同 → 一次走旧的 detail_hook，一次走引擎通用流程。
      然后把两份 jsonl 按 detail_url 对齐，逐条比 16 个业务字段。

比对范围（故意的）：
    比：title / detail_title / publish_date / status_img / effective_date /
        abolish_date / issuer / doc_no / attr / valid_status / status_confirmed /
        detail_fetch / detail_http_status
    不比：fetched_at / detail_fetched_at / run_id / source_url / content_hash
          —— 这些是"什么时候抓的"，两次跑必然不同，比了没有意义。

跑法：
    python tests\\compare_detail_paths.py            # 完整跑（约 4 分钟，80 次详情请求）
    python tests\\compare_detail_paths.py --reuse    # 不重跑，只比对已有文件

退出码：0 一致 / 1 有差异 / 2 缺数据文件
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PY = str(_HOME / "venv" / "Scripts" / "python.exe")
CRAWLER = str(_HOME / "crawlers" / "crawler.py")
# 旧实现（detail_hook）已从生产代码删除。要重跑 A 侧，就用阶段0 冻结的那份 crawler.py：
# 它自带旧逻辑，而且它的 sites/ 目录里是旧版 foodlaw.py，跑起来就是当年的行为。
LEGACY_CRAWLER = str(_HOME / "crawlers" / "_baseline_v1" / "code" / "crawler.py")
RAW = Path(str(_HOME / "data" / "raw"))
REPORTS = Path(str(_HOME / "out" / "reports"))

JOB_LEGACY = "foodlaw_abl"
JOB_GENERIC = "foodlaw_abg"

COMPARE_FIELDS = [
    "title", "detail_title", "publish_date", "status_img",
    "effective_date", "abolish_date", "issuer", "doc_no", "attr",
    "valid_status", "status_confirmed",
    "detail_fetch", "detail_http_status",
]


def prepare_legacy_tree():
    """
    把阶段0 基线里的旧代码复制到 logs\\_legacy_replay\\，只改两处：
        job       → foodlaw_abl（这样数据落到独立文件，不碰 foodlaw.jsonl）
        page_end  → 2
    基线本身不动（它是只读证据，改了就没法做离线对照了）。

    为什么这么麻烦：旧实现已经删除，但它必须"还能被跑起来验证"，
    否则以后有人说"新逻辑和旧的不一样"，就没有裁判了。
    """
    import shutil
    src = Path(str(_HOME / "crawlers" / "_baseline_v1" / "code"))
    dst = Path(str(_HOME / "logs" / "_legacy_replay"))
    if not src.exists():
        raise RuntimeError("基线代码目录不存在：%s" % src)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    cfg = dst / "sites/foodlaw.py"
    txt = cfg.read_text(encoding="utf-8")
    txt = txt.replace('"job": "foodlaw"', '"job": "%s"' % JOB_LEGACY, 1)
    txt = txt.replace('"page_end": 1,', '"page_end": 2,', 1)
    cfg.write_text(txt, encoding="utf-8", newline="\n")
    return str(dst / "crawler.py")


def clean_job(job):
    """删掉该 job 的数据/断点，保证这次是"从零开始抓"，不会被去重挡住。"""
    for p in (RAW / ("%s.jsonl" % job),
              Path(str(_HOME / "manifests" / "state_%s.json") % job)):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def run(job, mode, crawler=None):
    print("\n---- 跑 %s（mode=%s）----" % (job, mode))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    clean_job(job)
    if crawler:
        # 旧版 crawler.py 没有 --job / --detail-mode 参数，任务名从补丁后的 CONFIG 来
        cmd = [PY, crawler, "--site", "foodlaw", "--pages", "2"]
    else:
        cmd = [PY, CRAWLER, "--site", "foodlaw", "--pages", "2",
               "--job", job, "--detail-mode", mode]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=env, timeout=900)
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-6:]
    for ln in tail:
        print("   " + ln)
    return r.returncode


def load(job):
    p = RAW / ("%s.jsonl" % job)
    if not p.exists():
        return None
    rows = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                rows.append(json.loads(ln))
    return rows


def norm(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true", help="不重跑，只比已有文件")
    ap.add_argument("--a", default=JOB_LEGACY, help="A 侧 job 名（默认 %s = 旧逻辑）" % JOB_LEGACY)
    ap.add_argument("--b", default=JOB_GENERIC, help="B 侧 job 名（默认 %s = 新流程）" % JOB_GENERIC)
    args = ap.parse_args()

    print("=" * 78)
    print("阶段1 · 真站 A/B：旧 detail_hook vs 新通用流程")
    print("=" * 78)

    if not args.reuse:
        legacy = prepare_legacy_tree()          # 旧实现（从冻结基线还原到临时目录）
        rc1 = run(JOB_LEGACY, "legacy", crawler=legacy)
        rc2 = run(JOB_GENERIC, "generic")        # 现在的生产实现
        print("\n退出码：legacy=%d generic=%d" % (rc1, rc2))

    a = load(args.a)
    b = load(args.b)
    if a is None or b is None:
        print("缺数据文件：%s / %s" % (RAW / (args.a + ".jsonl"),
                                    RAW / (args.b + ".jsonl")))
        return 2

    print("\nA(%s) %d 条 / B(%s) %d 条" % (args.a, len(a), args.b, len(b)))

    ma = {r.get("detail_url"): r for r in a}
    mb = {r.get("detail_url"): r for r in b}
    only_a = sorted(set(ma) - set(mb))
    only_b = sorted(set(mb) - set(ma))
    common = sorted(set(ma) & set(mb))

    print("共同 URL %d / 只在旧 %d / 只在新 %d"
          % (len(common), len(only_a), len(only_b)))

    diffs = []
    for url in common:
        ra, rb = ma[url], mb[url]
        for k in COMPARE_FIELDS:
            va, vb = norm(ra.get(k)), norm(rb.get(k))
            if va != vb:
                diffs.append((url, k, va, vb))

    # 字段集合也要比：多一个少一个字段都是行为变化
    fa = sorted({k for r in a for k in r} - {"fetched_at", "detail_fetched_at",
                                            "run_id", "source_url", "content_hash"})
    fb = sorted({k for r in b for k in r} - {"fetched_at", "detail_fetched_at",
                                            "run_id", "source_url", "content_hash"})
    if fa != fb:
        print("\n!! 字段集合不同")
        print("   只在旧：%s" % sorted(set(fa) - set(fb)))
        print("   只在新：%s" % sorted(set(fb) - set(fa)))

    if diffs:
        print("\n!! 发现 %d 处字段不一致（前 30 条）" % len(diffs))
        print("%-46s %-20s %-22s %s" % ("detail_url 尾部", "字段", "A 侧", "B 侧"))
        print("-" * 110)
        for url, k, va, vb in diffs[:30]:
            print("%-46s %-20s %-22s %s"
                  % (url[-46:], k, va[:21], vb[:21]))
    if only_a[:5] or only_b[:5]:
        print("\n不一致的 URL（前 5 个）")
        for u in only_a[:5]:
            print("   只在旧：%s" % u)
        for u in only_b[:5]:
            print("   只在新：%s" % u)

    print("\n" + "=" * 78)
    ok = (not diffs and not only_a and not only_b and fa == fb and len(common) > 0)
    if ok:
        print("结论：一致 —— %d 条记录 × %d 个字段，零差异"
              % (len(common), len(COMPARE_FIELDS)))
        return 0
    print("结论：有差异，不能删旧逻辑（差异 %d 处，URL 差异 %d/%d，字段集合%s）"
          % (len(diffs), len(only_a), len(only_b), "一致" if fa == fb else "不同"))
    return 1


if __name__ == "__main__":
    sys.exit(main())