# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
北森（Beisen / iTalent）招聘站客户端 —— 多租户通用。

任何用北森的公司，招聘站都在 `https://{slug}.zhiye.com`，抓法完全一样：

  ① GET  https://{slug}.zhiye.com/portal/registerSystemInfo
        → HTML 里内联 `var BSGlobal = {...}`，取 **PortalId**
  ② POST https://{slug}.zhiye.com/api/Jobad/GetJobAdPageList
        body: {"PageIndex":0,"PageSize":50,"KeyWords":"","SpecialType":0,
               "PortalId":"...","DisplayFields":["Category","Description","Location","Department","Salary"]}
        → {"Code":200,"Count":N,"Data":[{JobAdId, JobAdName, Category, Salary, Duty, Require, ChangeDate, ...}]}

岗位公开页：`https://{slug}.zhiye.com/portal/jobs/{JobAdId}`

协议来源：独立开源适配器 ever-jobs/ever-jobs（Spec 741 Beisen 多租户适配器）的公开说明，
本轮用双汇/蒙牛/贝因美实测确认。

用法：
    python tools\\beisen_client.py --slug shuanghui
    python tools\\beisen_client.py --slugs shuanghui,mengniu,beingmate --max-pages 3
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）
PAGE_SIZE = 50
OUT_DIR = Path(str(_HOME / "out"))


def slice_balanced(text, start):
    """从 `{` 起做括号配平（跳过字符串与转义），返回完整的 JSON 对象串。"""
    depth, i, in_str, quote = 0, start, False, ""
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in ("\"", "'"):
            in_str, quote = True, ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None


def resolve_portal(sess, slug, timeout=20, delay=(3.0, 4.5)):
    """① 取 PortalId 与公司名。"""
    base = "https://%s.zhiye.com" % slug
    time.sleep(_rand(delay))
    r = sess.get(base + "/portal/registerSystemInfo", timeout=timeout)
    html = r.content.decode("utf-8", errors="replace")
    import re
    m = re.search(r"var\s+BSGlobal\s*=\s*\{", html)
    if not m:
        return None
    blob = slice_balanced(html, m.end() - 1)
    try:
        cfg = json.loads(blob)
    except Exception:
        return None
    portal = cfg.get("PortalId")
    if not portal:
        return None
    return {"slug": slug, "base": base, "portal_id": portal,
            "company": cfg.get("Name") or "", "template": cfg.get("Code") or ""}


def list_jobs(sess, tenant, page_size=PAGE_SIZE, max_pages=10, delay=(3.0, 4.5), timeout=25):
    """② 分页取岗位（按 JobAdId 去重，遇到空页/短页/够数就停）。"""
    base = tenant["base"]
    seen, rows = set(), []
    total = None
    for page in range(max_pages):
        # DisplayFields 决定返回哪些字段；**LocNames 必须和 LocId 一起要，单独要 LocNames 返回空数组**
        body = {"PageIndex": page, "PageSize": page_size, "KeyWords": "", "SpecialType": 0,
                "PortalId": tenant["portal_id"],
                "DisplayFields": ["Category", "Description", "Location", "Department",
                                  "Salary", "LocNames", "LocId", "Station"]}
        time.sleep(_rand(delay))
        r = sess.post(base + "/api/Jobad/GetJobAdPageList", json=body, timeout=timeout,
                      headers={"Referer": base + "/social/jobs", "Origin": base})
        try:
            d = r.json()
        except Exception:
            break
        if total is None:
            total = d.get("Count")
        data = d.get("Data") or []
        if not data:
            break
        added = 0
        for it in data:
            jid = it.get("JobAdId")
            if jid is None or jid in seen:
                continue
            seen.add(jid)
            rows.append(normalise(it, base))
            added += 1
        if total is not None and len(rows) >= int(total):
            break
        if added == 0 or len(data) < page_size:
            break
    return {"count": total, "jobs": rows}


def normalise(it, base):
    # 地点优先级：LocNames（省·市） > Station（门店/厂区） > DetailAddress
    def _s(v):
        if isinstance(v, list):
            return " / ".join(str(x) for x in v if x)
        return str(v) if v not in (None, "") else ""

    raw_names = it.get("LocNames") or []
    loc_names = [str(x) for x in (raw_names if isinstance(raw_names, list) else [raw_names]) if x]
    loc = (" / ".join(loc_names) if loc_names
           else (_s(it.get("Station")) or _s(it.get("DetailAddress"))))
    city = ""
    if loc_names:
        # '宁夏回族自治区·银川市' → 取最后一段当城市
        last = loc_names[0].split("·")[-1]
        city = last.strip()
    return {
        "job_ad_id": it.get("JobAdId"),
        "title": (it.get("JobAdName") or "").strip(),
        "category": it.get("Category") or "",
        "salary": (it.get("Salary") or "").strip(),
        "location": str(loc).strip(),
        "city": city,
        "duty": (it.get("Duty") or "").strip(),
        "require": (it.get("Require") or "").strip(),
        "change_date": (it.get("ChangeDate") or "")[:10],
        "post_date": (it.get("PostDate") or "")[:10],
        "url": "%s/portal/jobs/%s" % (base, it.get("JobAdId")),
        "company_slug": base.split("//")[1].split(".")[0],
    }


def _rand(pair):
    import random
    return random.uniform(*pair)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--slugs")
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()
    slugs = [s.strip() for s in (args.slugs or args.slug or "").split(",") if s.strip()]
    if not slugs:
        print(__doc__)
        return 2

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    summary = []
    for slug in slugs:
        print("\n=== %s ===" % slug)
        t = resolve_portal(sess, slug)
        if not t:
            print("  ✗ 取不到 PortalId（可能非北森站 / 已下线）")
            summary.append({"slug": slug, "ok": False})
            continue
        print("  PortalId=%s 公司=%s" % (t["portal_id"], t["company"]))
        res = list_jobs(sess, t, max_pages=args.max_pages)
        print("  Count=%s 抓到 %d 条" % (res["count"], len(res["jobs"])))
        for j in res["jobs"][:5]:
            print("    %s | %-28s | %-10s | %s" % (j["job_ad_id"], j["title"][:26],
                                                  j["category"], j["salary"]))
        out = OUT_DIR / ("beisen_%s.json" % slug)
        out.write_text(json.dumps({"tenant": t, **res}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  →", out)
        summary.append({"slug": slug, "ok": True, "company": t["company"],
                        "count": res["count"], "got": len(res["jobs"])})

    print("\n===== 汇总 =====")
    for s in summary:
        if s["ok"]:
            print("  %-12s %-10s 在招 %s 条（抓到 %d）" % (s["slug"], s["company"], s["count"], s["got"]))
        else:
            print("  %-12s ✗" % s["slug"])
    return 0


if __name__ == "__main__":
    sys.exit(main())