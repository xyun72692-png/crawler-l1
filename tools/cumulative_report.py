# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
累计进度报表（**不是止损判断**，只报数字）。

输入：`data\\raw\\wzrc_fullsite_20261112.jsonl`（全站抓取，WZ_TAG=0）
      `manifests\\state_wzrc_fullsite_20261112.json`（拿 pages_done / pages_declared）
输出：终端一行行统计 + 可选 --json 落一份

统计口径（顺序固定，每条记录只落一个桶，所以各桶之和 = 总数）：
  1 不对口       classify(title) 为空
  2 非直招       judge_nature != 企业直招
  3 学历超大专    judge_edu 不通过
  4 面议/不明    parse_salary 状态不是 ok
  5 薪资<下限    floor < 下限（4500 / 5000 两档分别算）
  6 保留         以上全过 → 再按双休状态拆「明确双休 / 未标注 / 非双休」

另给两组对照：
  · 「不在旧双休池」= detail_url 不在 wzrc_dw_20261111.jsonl（502 条）里
  · 「与上一版 29 岗位」= 公司+岗位归一化后比对 out\\温州岗位清单_20261111.json

用法：
    python tools\\cumulative_report.py
    python tools\\cumulative_report.py --json out\\累计进度_20261112.json
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path

AGENT = Path(str(_HOME))
sys.path.insert(0, str(AGENT / "crawlers"))
import clean_jobs_wz as cw          # noqa: E402

JOB = "wzrc_fullsite_20261112"
DATA = AGENT / "data" / "raw" / (JOB + ".jsonl")
STATE = AGENT / "manifests" / ("state_" + JOB + ".json")
OLD_POOL = AGENT / "data" / "raw" / "wzrc_dw_20261111.jsonl"   # 11-11 双休池 502 条
PREV_LIST = AGENT / "out" / "温州岗位清单_20261111.json"        # 上一版 29 岗位

FLOORS = (4500, 5000)
REASONS = ("不对口", "非直招", "学历超大专", "面议/不明", "薪资<下限")


def norm(text):
    s = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", s).lower()


def load_jsonl(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def classify_row(r, floor):
    """返回 (桶, 说明)。桶 ∈ 剔除原因 or '保留'。"""
    if not cw.classify(r.get("title") or ""):
        return "不对口", ""
    nature = cw.judge_nature(r)
    if nature != "企业直招":
        return "非直招", nature
    edu_text, edu_ok, edu_note = cw.judge_edu(r)
    if not edu_ok:
        return "学历超大专", edu_text or edu_note
    sal_floor, state = cw.parse_salary(r.get("salary_raw"))
    if state != "ok":
        return "面议/不明", r.get("salary_raw") or ""
    if sal_floor is None or sal_floor < floor:
        return "薪资<下限", r.get("salary_raw") or ""
    return "保留", ""


def weekend(r):
    st, _note = cw.weekend_state(r)
    return st          # 明确双休 / 未标注 / 非双休


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="把统计额外写成 json")
    a = ap.parse_args()

    rows = load_jsonl(DATA)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    pages_done = sorted(set(state.get("pages_done") or []))
    declared = state.get("pages_declared")

    old_urls = {r.get("detail_url") for r in load_jsonl(OLD_POOL)}
    prev = []
    if PREV_LIST.exists():
        prev = json.loads(PREV_LIST.read_text(encoding="utf-8"))
    prev_keys = {norm(p.get("company")) + "|" + norm(p.get("title")) for p in prev}

    total = len(rows)
    n_pages = len(pages_done)

    out = OrderedDict()
    print("=" * 66)
    print("累计进度报表   job=%s" % JOB)
    print("=" * 66)
    print("数据文件      %s" % DATA.name)
    print("累计页数      %d%s" % (n_pages, (" / 声明 %s（%.1f%%）" % (declared, 100 * n_pages / declared)) if declared else ""))
    print("累计条数      %d" % total)
    print("每页均值      %.2f 条/页" % (total / n_pages if n_pages else 0))
    out["pages_done"] = n_pages
    out["pages_declared"] = declared
    out["records"] = total
    out["per_page"] = round(total / n_pages, 2) if n_pages else 0

    # ---- 双休状态分布（全部记录）
    wk = Counter(weekend(r) for r in rows)
    print()
    print("双休状态分布（全部 %d 条）" % total)
    for k in ("明确双休", "未标注", "非双休"):
        v = wk.get(k, 0)
        print("  %-8s %5d  (%.1f%%)" % (k, v, 100 * v / total if total else 0))
    out["weekend_all"] = dict(wk)

    # ---- 不在旧双休池
    fresh = [r for r in rows if r.get("detail_url") not in old_urls]
    print()
    print("新岗位（detail_url 不在 11-11 双休池 502 条里）")
    print("  %5d 条  (%.1f%%)   旧池命中 %d 条"
          % (len(fresh), 100 * len(fresh) / total if total else 0, total - len(fresh)))
    out["fresh_vs_old_pool"] = len(fresh)
    out["old_pool_hit"] = total - len(fresh)

    # ---- 两档硬筛
    for floor in FLOORS:
        buckets = Counter()
        kept = []
        for r in rows:
            b, note = classify_row(r, floor)
            buckets[b] += 1
            if b == "保留":
                kept.append(r)
        keep_wk = Counter(weekend(r) for r in kept)
        keep_fresh = [r for r in kept if r.get("detail_url") not in old_urls]
        keep_keys = {norm(r.get("company")) + "|" + norm(r.get("title")) for r in kept}
        overlap_prev = keep_keys & prev_keys
        new_vs_prev = keep_keys - prev_keys

        print()
        print("-" * 66)
        print("硬筛（对口 + 直招 + 学历 + 薪资下限 ≥ %d）" % floor)
        print("  保留            %5d 条" % len(kept))
        print("    ├ 明确双休      %5d" % keep_wk.get("明确双休", 0))
        print("    ├ 未标注        %5d" % keep_wk.get("未标注", 0))
        print("    └ 非双休        %5d" % keep_wk.get("非双休", 0))
        print("  其中不在旧双休池 %5d 条" % len(keep_fresh))
        print("  与上一版 29 岗位  重合 %d / 新增 %d 个岗位" % (len(overlap_prev), len(new_vs_prev)))
        print("  剔除原因分布（加总 = %d）" % total)
        s = 0
        for k in REASONS:
            v = buckets.get(k, 0)
            s += v
            print("    %-10s %5d" % (k, v))
        print("    保留       %5d" % len(kept))
        print("    合计       %5d  %s" % (s + len(kept), "✅" if s + len(kept) == total else "❌ 对不上"))

        out.setdefault("hard_filter", {})[str(floor)] = {
            "kept": len(kept),
            "kept_weekend": dict(keep_wk),
            "kept_fresh": len(keep_fresh),
            "overlap_prev": len(overlap_prev),
            "new_vs_prev": len(new_vs_prev),
            "rejected": {k: buckets.get(k, 0) for k in REASONS},
            "sum_check": s + len(kept) == total,
        }

    print()
    print("=" * 66)
    print("（这是进度报表，不做\"该不该继续\"的判断）")

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("明细已写：%s" % a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())