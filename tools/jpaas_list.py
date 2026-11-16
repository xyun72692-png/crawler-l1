# -*- coding: utf-8 -*-
"""
浙江政务云 CMS（jpaas）栏目列表接口客户端 —— **不需要浏览器**。

实测协议（2026-11-14）：

    GET https://<host>/api-gateway/jpaas-publish-server/front/page/build/unit
    params:
        parseType=bulidstatic
        webId=<站点ID>
        tplSetId=<模板集ID>
        pageType=column
        tagId=<标签名，通常是「当前栏目列表」>
        editType=null
        pageId=<栏目ID>
        paramJson={"pageNo":2,"pageSize":10}      ← 分页就靠这个（JSON 字符串）

    返回 JSON：{"success":true,"data":{"html":"…列表片段…"}}
    片段里的 <table … count="367" pageNo="2"> 给出**总条数**与当前页。

关键点：
  · 前 7 个参数**全部写在栏目页的 <script unitbuild.js> 标签属性里**（0 额外请求就能拿到）
  · 分页参数必须放在 `paramJson` 里（放 top-level 的 pageNo/pageSize 会被忽略 —— 实测）
  · 标题/日期/详情URL 都在返回的 HTML 片段里，正则或 BeautifulSoup 都能取

用法：
    python tools\\jpaas_list.py --html <栏目页壳.html> --page 1
    python tools\\jpaas_list.py --url https://rlsbt.zj.gov.cn/col/col1229743683/index.html --page 2
"""

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

import sys as _sys
from pathlib import Path as _path_lib
_sys.path.insert(0, str(_path_lib(__file__).resolve().parents[1] / "crawlers"))
from identity import UA  # noqa: E402  ← 唯一身份源（v14 阶段 0）
UNIT_PATH = "/api-gateway/jpaas-publish-server/front/page/build/unit"
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


LIST_TAG_HINT = ("list", "列表", "当前栏目列表", "文章列表", "分页列表")


def _tag_score(tag_id):
    t = (tag_id or "").lower()
    for k in LIST_TAG_HINT:
        if k.lower() in t:
            return 10
    if "移动端" in t or "mobile" in t:
        return 1          # 移动端模板通常也能用，但优先级最低
    return 5


def extract_units(html, page_host="https://rlsbt.zj.gov.cn"):
    """把页面上所有 unitbuild 标签都抠出来，按"像列表"的程度排序。

    返回 [{"params": {...}, "unit_url": ..., "tag_id": ...}, ...]
    """
    soup = BeautifulSoup(html, "lxml")
    out = []
    for sc in soup.find_all("script"):
        src = sc.get("src") or ""
        if "unitbuild.js" not in src:
            continue
        raw = sc.get("querydata") or sc.get("queryData") or ""
        raw = raw.replace("'", '"')
        try:
            qd = json.loads(raw)
        except Exception:
            qd = {}
        params = {
            "parseType": qd.get("parseType", "bulidstatic"),
            "webId": qd.get("webId", ""),
            "tplSetId": qd.get("tplSetId", ""),
            "pageType": qd.get("pageType", "column"),
            "tagId": qd.get("tagId", "当前栏目列表"),
            "editType": qd.get("editType", "null"),
            "pageId": qd.get("pageId", ""),
        }
        url = sc.get("url") or UNIT_PATH
        out.append({"params": params, "tag_id": params["tagId"],
                    "unit_url": page_host.rstrip("/") + url})
    out.sort(key=lambda x: -_tag_score(x["tag_id"]))
    return out


def extract_unit_params(html, page_host="https://rlsbt.zj.gov.cn"):
    """兼容旧接口：返回"最像列表"的那个标签。没有就返回空参数 + needs_investigation。"""
    units = extract_units(html, page_host)
    if units:
        best = dict(units[0])
        best["units"] = units
        return best
    arts = len(re.findall(r"/art/\d{4}/", html or ""))
    return {"params": {}, "unit_url": page_host.rstrip("/") + UNIT_PATH,
            "needs_investigation": arts == 0, "art_links": arts, "units": []}


def parse_items(html_fragment, base_url=""):
    """从接口返回的 HTML 片段里取 (标题, 日期, 详情URL)。"""
    soup = BeautifulSoup(html_fragment, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/art/" not in href:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        # 日期常在同级 li 里
        li = a.find_parent("li") or a.parent
        m = DATE_RE.search(li.get_text(" ", strip=True)) if li is not None else None
        out.append({"title": title,
                    "published": m.group(1) if m else "",
                    "url": href if href.startswith("http") else base_url.rstrip("/") + href})
    # 去重（同一 URL 可能出现多次）
    seen, uniq = set(), []
    for x in out:
        if x["url"] in seen:
            continue
        seen.add(x["url"])
        uniq.append(x)
    return uniq


def parse_meta(html_fragment):
    """取 count（总条数）与 pageNo（当前页）、rows（每页条数）。"""
    m = re.search(r'count="(\d+)"\s+pageNo="(\d+)"', html_fragment)
    rows = re.search(r'rows="(\d+)"', html_fragment)
    return {
        "count": int(m.group(1)) if m else None,
        "page_no": int(m.group(2)) if m else None,
        "rows": int(rows.group(1)) if rows else None,
    }


def fetch_unit(unit_url, params, page_no=1, page_size=10, timeout=30, session=None, base_url=None):
    import requests
    from urllib.parse import urlsplit
    if base_url is None:
        u = urlsplit(unit_url)
        base_url = '%s://%s' % (u.scheme, u.netloc)
    s = session or requests.Session()
    p = dict(params)
    p["paramJson"] = json.dumps({"pageNo": page_no, "pageSize": page_size},
                                separators=(",", ":"))
    r = s.get(unit_url, params=p, timeout=timeout,
              headers={"User-Agent": UA, "Referer": unit_url})
    d = r.json()
    if not d.get("success"):
        raise RuntimeError("接口返回失败：%s" % d.get("message"))
    frag = d["data"]["html"]
    return {"status": r.status_code, "meta": parse_meta(frag),
            "items": parse_items(frag, base_url), "raw_html": frag}


def main():
    args = sys.argv[1:]
    src = None
    page = 1
    size = 10
    host = "https://rlsbt.zj.gov.cn"
    i = 0
    while i < len(args):
        if args[i] == "--html":
            src = ("file", args[i + 1]); i += 2
        elif args[i] == "--url":
            src = ("url", args[i + 1]); i += 2
        elif args[i] == "--page":
            page = int(args[i + 1]); i += 2
        elif args[i] == "--size":
            size = int(args[i + 1]); i += 2
        elif args[i] == "--host":
            host = args[i + 1]; i += 2
        else:
            i += 1
    if not src:
        print(__doc__)
        return 2

    if src[0] == "file":
        html = Path(src[1]).read_text(encoding="utf-8", errors="replace")
    else:
        import requests
        r = requests.get(src[1], headers={"User-Agent": UA}, timeout=30)
        html = r.content.decode("utf-8", errors="replace")
        from urllib.parse import urlsplit
        u = urlsplit(src[1])
        host = "%s://%s" % (u.scheme, u.netloc)

    info = extract_unit_params(html, host)
    print("接口:", info["unit_url"])
    print("参数:", json.dumps(info["params"], ensure_ascii=False))
    if not info["params"].get("pageId"):
        print("!! 没从页面里找到 unitbuild 参数")
        return 3

    res = fetch_unit(info["unit_url"], info["params"], page, size)
    print("第 %d 页 → HTTP %s | 总条数 %s | 本页 %d 条"
          % (page, res["status"], res["meta"]["count"], len(res["items"])))
    for it in res["items"]:
        print("  %-46s %-11s %s" % (it["title"][:44], it["published"], it["url"][-40:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())