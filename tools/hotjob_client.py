# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
大易 hotjob 客户端（多租户）—— 又一个 ATS 杠杆。

协议（实测 2026-11-14，伊利）：
    GET https://{tenant}.hotjob.cn/wt/{tenant}/web/json/position/list?pageNo=1
    → {"pageCount":177, "postList":[{postId, postName, workPlace, workPlaceCode,
        orgName, deptOrgName, publishDate, endDate, workYears, workContent,
        serviceCondition, workingTreatment, recruitNum, recruitType, ...}]}

要点：
  · pageSize 被服务端忽略（固定 10 条/页）
  · pageCount 是**页数**，不是条数
  · 岗位详情页：https://{tenant}.hotjob.cn/wt/{tenant}/web/index/…!gotoPostDetailForAjax?postId={postId}
  · 伊利官网页（/joinus）里的「全部岗位」链接就是 gethotjob 的 templet1000 入口

用法：
    python tools\\hotjob_client.py --tenants yili --pages 3
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests

import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）
OUT_DIR = Path(str(_HOME / "out"))


def list_page(sess, tenant, page_no, timeout=25, delay=(3.0, 4.5), recruit_type=1):
    # 分页参数是 page=（不是 pageNo）；其余参数来自外壳页里的 url 拼接
    url = ("https://%s.hotjob.cn/wt/%s/web/json/position/list"
           "?positionType=&comPart=&sicCorpCode=&brandCode=1&releaseTime="
           "&trademark=1&recruitType=%d&projectId=&lanType=1&workPlace=&page=%d"
           % (tenant, tenant, recruit_type, page_no))
    time.sleep(random.uniform(*delay))
    r = sess.get(url, timeout=timeout,
                 headers={"Referer": "https://%s.hotjob.cn/" % tenant,
                          "X-Requested-With": "XMLHttpRequest"})
    d = r.json()
    return d.get("pageCount"), normalise_all(d.get("postList") or [], tenant)


def normalise_all(items, tenant):
    out = []
    for it in items:
        out.append({
            "post_id": it.get("postId"),
            "title": (it.get("postName") or "").strip(),
            "work_place": (it.get("workPlace") or "").strip(),
            "place_code": it.get("workPlaceCode") or "",
            "org": (it.get("orgName") or "").strip(),
            "dept": (it.get("deptOrgName") or "").strip(),
            "publish_date": (it.get("publishDate") or "")[:10],
            "end_date": (it.get("endDate") or "")[:10],
            "work_years": (it.get("workYears") or "").strip(),
            "treatment": (it.get("workingTreatment") or "").strip(),
            "recruit_num": it.get("recruitNum"),
            "recruit_type": it.get("recruitType"),
            "tenant": tenant,
            "url": "https://%s.hotjob.cn/wt/%s/web/index/webPositionN300!getOnePosition?postId=%s"
                   % (tenant, tenant, it.get("postId")),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", default="yili")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--rt", type=int, default=1, help="1=校园招聘 2=社会招聘")
    args = ap.parse_args()
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    summary = []
    for tenant in [t.strip() for t in args.tenants.split(",") if t.strip()]:
        print("\n=== %s ===" % tenant)
        rows, page_count = [], None
        for p in range(1, args.pages + 1):
            try:
                pc, items = list_page(sess, tenant, p, recruit_type=args.rt)
            except Exception as e:
                print("  第 %d 页失败 %s" % (p, type(e).__name__))
                break
            if page_count is None:
                page_count = pc
            rows.extend(items)
            print("  第 %d 页 → 本页 %d 条（pageCount=%s）" % (p, len(items), pc))
            if not items:
                break
        out = OUT_DIR / ("hotjob_%s_rt%d.json" % (tenant, args.rt))
        out.write_text(json.dumps({"tenant": tenant, "page_count": page_count, "jobs": rows},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print("  合计 %d 条 → %s" % (len(rows), out))
        summary.append((tenant, page_count, len(rows)))
        for j in rows[:5]:
            print("    %s | %-30s | %s | %s" % (j["post_id"], j["title"][:28], j["work_place"] or "-",
                                               j["publish_date"]))
    print("\n===== 汇总 =====")
    for t, pc, n in summary:
        print("  %-10s pageCount=%s 抓 %d 条" % (t, pc, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())