# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""修 bug：断点没有"筛选条件指纹"，换筛选会沿用旧 pages_done/pages_declared。"""
from pathlib import Path

P = Path(str(_HOME / "crawlers" / "crawler.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

# ---------------- 1) 指纹函数 ----------------
sub('''def total_pages_supported(site_mod=None):''',
    '''def query_fingerprint(url):
    """
    把 URL 里的"筛选条件"压成一个短指纹（去掉 page）。

    为什么需要：同一个 --job 换筛选（WZ_SETTR / WZ_CITY / WZ_WAGE / WZ_TRADE…）时，
    第 1 页已经不是同一批数据了。若沿用旧断点：
      · pages_done 里有 1..5 → 新条件的第 1..5 页被"跳过"，一个请求都不发
      · pages_declared 是旧条件的 M → coverage 算成 1.0
      · 最后报告 success —— 最恶劣的那种"假成功"
    所以条件一变，页码映射就作废；去重键 seen_keys 必须保留（它跟页码无关）。
    """
    try:
        parts = urlsplit(url)
        q = parse_qs(parts.query, keep_blank_values=True)
        q.pop("page", None)
        norm = "&".join("%s=%s" % (k, ",".join(sorted(v))) for k, v in sorted(q.items()))
        raw = (parts.path or "/") + "?" + norm
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    except Exception:
        return ""


def total_pages_supported(site_mod=None):''',
    "1) 指纹函数")

# ---------------- 2) 状态里比对指纹 ----------------
sub('''    # ---- page_size 变更检测 ----''',
    '''    # ---- 筛选条件指纹检测（先于 page_size）----
    # 同一 job 换筛选 → 页码与内容的对应关系整体作废，旧断点必须清。
    fp_now = query_fingerprint(first_url)
    fp_old = st.get("filters_fp") or ""
    if fp_now and fp_old and fp_now != fp_old:
        log("!! 筛选条件变了（指纹 %s → %s）→ 旧断点作废" % (fp_old, fp_now))
        log("!!   清空 pages_done（%d 页）与 pages_declared（%s），保留去重键 %d 条"
            % (len(st.get("pages_done") or []), st.get("pages_declared"),
               len(st.get("seen_keys") or [])))
        st["pages_done"] = []
        st["pages_declared"] = None
        ctx.setdefault("anomalies", []).append(
            {"page": "state", "url": first_url,
             "reason": "筛选条件变更 %s→%s，已清 pages_done/pages_declared" % (fp_old, fp_now)})
    st["filters_fp"] = fp_now

    # ---- page_size 变更检测 ----''',
    "2) 指纹比对")

# blank_state 里带上默认字段（老 state 文件没有也能补）
sub('''def blank_state(out_file):''', '''def blank_state(out_file):''', "3) 占位（不需要改）")

P.write_text(s, encoding="utf-8", newline="\n")
print("crawler.py 指纹检测已加")

# ---------------- 3) blank_state 补默认键 ----------------
s2 = P.read_text(encoding="utf-8")
if '"filters_fp": ""' not in s2:
    import re
    m = re.search(r'def blank_state\(out_file\):\n(.*?)\n\n', s2, re.S)
    print("blank_state 片段:")
    print(m.group(0)[:400] if m else "未找到")