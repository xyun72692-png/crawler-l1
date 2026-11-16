# -*- coding: utf-8 -*-
"""
v13 发现工具的离线测试（T1 / T2 / T6），**0 请求**。

为什么要有这个文件：
  · 只有正例回测（8/8 命中）是不够的 —— 一个"把整页文本倒出来"的实现也能过；
    必须有一条**负例**：拿不相干的站（乐清列表页）跑，jrzp 域名必须 0 命中。
  · "0 请求"如果只靠人记得，加一行 import requests 就失效了 → 用 AST 扫源码把性质钉死。
  · 指纹的判定阈值（Jaccard 三档）必须写进测试，否则以后调参没有锚。

运行：
    python tests\\test_discover.py
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "data"
RAW = ROOT / "data" / "raw"
TOOLS = ROOT / "tools"
ROOT_SITES = ROOT / "crawlers" / "sites"
ROOT_TOOLS = TOOLS
GOLDEN = TOOLS / "golden" / "jrzp_wenzhou_known.txt"

sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True

import fingerprint_offline as fp  # noqa: E402

# --- CI 编码护栏（v14.13.20）------------------------------------------------
# 为什么需要：GitHub 的 windows runner 默认 locale 是 cp1252，子进程（crawler.py）
# 往管道里打中文会抛 UnicodeEncodeError；而本机是中文 Windows（cp936）能编码中文，
# 所以这个坑只在 CI 暴露。v14.13.19 的 test_crawler 就栽在这一点上。
# 这里统一给「本进程 + 它启动的子进程」钉死 UTF-8。
import os as _os_enc
_os_enc.environ.setdefault("PYTHONIOENCODING", "utf-8")
_os_enc.environ.setdefault("PYTHONUTF8", "1")
# ---------------------------------------------------------------------------


results = []


def _safe(x):
    """GBK 控制台/重定向遇到 ↔ ✗ 这类字符会崩；先试编码，编不了就替换。"""
    s = str(x)
    enc = getattr(sys.stdout, "encoding", None) or "gbk"
    try:
        s.encode(enc)
        return s
    except (UnicodeEncodeError, LookupError):
        return s.encode(enc, "replace").decode(enc, "replace")


def rec(name, ok, detail):
    results.append((name, ok, detail))
    print("  %-6s %s  %s" % ("PASS" if ok else "FAIL", _safe(name), _safe(detail)))


def known_domains():
    return [x.strip() for x in GOLDEN.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.startswith("#")]


def hosts_of(path, base=""):
    r = fp.analyze(str(path), base)
    return [h for h, _ in r["outbound_hosts"]]


# ---------------------------------------------------------------- T1 负例
def t1_negative():
    p = FIX / "_probe_yqrc_job.html"
    if not p.exists():
        rec("T1 负例（乐清样本 → jrzp 域名 0 命中）", False, "样本缺失 %s" % p)
        return
    hs = hosts_of(p)
    doms = [d for d in known_domains() if not d.startswith("cangnanrc")]
    hit = [d for d in doms if any(d in h for h in hs)]
    rec("T1 负例（乐清样本 → jrzp 域名 0 命中）", len(hit) == 0,
        "出站域名 %d 个，jrzp 家族命中 %d %s" % (len(hs), len(hit), hit[:3]))


# ---------------------------------------------------------------- T2 AST 禁网
FORBID_ANY = {"requests", "urllib.request", "socket", "http.client", "aiohttp", "httpx"}
FORBID_HTTP = {"requests", "urllib.request", "http.client", "aiohttp", "httpx"}

# 纯离线模块：一个网络调用都不许有
OFFLINE_MODULES = ["fingerprint_offline.py", "_murmur3.py"]
# 只允许 DNS：不许 HTTP
DNS_MODULES = ["jrzp_domain_enum.py"]


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
                # from urllib import request 只记 urllib 会漏，连别名一起记
                for a in node.names:
                    mods.add(node.module + "." + a.name)
    return mods


def _violates(mods, forbid):
    out = []
    for m in mods:
        for f in forbid:
            if m == f or m.startswith(f + "."):
                out.append(m)
    return out


def t2_ast_no_network():
    bad = []
    for name in OFFLINE_MODULES:
        p = TOOLS / name
        if not p.exists():
            bad.append("%s 缺失" % name)
            continue
        v = _violates(imported_modules(p), FORBID_ANY)
        if v:
            bad.append("%s(%s)" % (name, v))
    for name in DNS_MODULES:
        p = TOOLS / name
        if not p.exists():
            continue          # 还没写就先不判，由 T8 覆盖
        v = _violates(imported_modules(p), FORBID_HTTP)
        if v:
            bad.append("%s(%s)" % (name, v))
    # 对照组：检查器必须能抓出已知的网络脚本（否则这条测试是自证式的）
    ctrl = TOOLS / "_cangnan_phase0.py"
    ctrl_ok = (not ctrl.exists()) or bool(_violates(imported_modules(ctrl), FORBID_ANY))
    rec("T2 AST：离线模块无网络 import（含对照组）", (not bad) and ctrl_ok,
        "违规 %d %s | 对照组能抓到=%s" % (len(bad), bad[:3], ctrl_ok))


# ---------------------------------------------------------------- T6 Jaccard
def jaccard(a, b):
    A, B = set(a), set(b)
    return len(A & B) / float(len(A | B)) if (A or B) else 1.0


def t6_jaccard():
    cn = FIX / "_probe_cangnan_home.html"
    cn2 = FIX / "_probe_cangnanrc.html"
    jz = FIX / "_probe_jrzp_home.html"
    if not (cn.exists() and cn2.exists() and jz.exists()):
        rec("T6 Jaccard 阈值", False, "样本缺失")
        return
    pa = fp.analyze(str(cn), "")["static_paths"]
    pb = fp.analyze(str(cn2), "")["static_paths"]
    pc = fp.analyze(str(jz), "")["static_paths"]
    j_self = jaccard(pa, pb)
    j_main = jaccard(pa, pc)
    ok = abs(j_self - 1.0) < 1e-9 and 0.0 < j_main < 0.05
    rec("T6 Jaccard：同站=1.0、苍南↔主站≈0.009", ok,
        "同站 %.3f | 主站 %.4f（%d/%d）" % (j_self, j_main, len(set(pa) & set(pc)),
                                        len(set(pa) | set(pc))))




# ---------------------------------------------------------------- T8 域名枚举召回
def t8_domain_recall():
    import jrzp_domain_enum_v2 as de
    doms = de.gen(de.WENZHOU)
    miss = [d for d in known_domains() if d not in doms]
    rec("T8 域名枚举召回：温州已知 11 个全部可生成", not miss,
        "候选 %d 个，漏 %d %s | 龙港=%s"
        % (len(doms), len(miss), miss[:3],
           "已生成(longgangrc.com)" if "longgangrc.com" in doms else "未生成"))




# ---------------------------------------------------------------- T9 www 优先 + apex 停放排除
def t9_resolver_rules():
    import jrzp_domain_enum_v2 as de
    prefixes, _detail = de.known_clusters(known_domains())

    which_py, ips_py = de.resolve_best("pingyangrc.com")
    apex_ips = de._ips("pingyangrc.com")

    www_first = (which_py == "www" and bool(ips_py))
    apex_is_parking = bool(apex_ips) and "203.107.45.167" in apex_ips
    cluster_ok = bool(prefixes)
    # 关键：簇不能是停放段（203.107.45）
    not_parking = all(p != "203.107.45" for p in prefixes)

    # DNS 答案会随时间/网络变化（实测 23:0x 前后完全不同）→ 这里只验逻辑，不断言具体 IP
    ok = www_first and apex_is_parking and cluster_ok and not_parking
    rec("T9 www 优先 + apex 停放不参与聚类（只验逻辑）", ok,
        "which=%s apex=%s 簇数=%d 含停放段=%s"
        % (which_py, ",".join(apex_ips)[:22], len(prefixes), not not_parking))



def t10_three_votes():
    import three_votes as tv
    raw = str(FIX / "homes")
    a, b = tv.collect(raw, "cangnan"), tv.collect(raw, "wzohrc")
    d = tv.votes(a, b)
    pos_ok = (d["yes"] == 3 and d["voted"] == 3 and d["plat_b"][0] == "jrzp"
              and d["gen_b"] == "A" and "可批量" in d["skin_note"])

    a2, b2 = tv.collect(raw, "cangnan"), tv.collect(raw, "jrzp")
    d2 = tv.votes(a2, b2)
    neg_ok = (d2["yes"] <= 1 and "可批量" not in d2["skin_note"])
    rec("T10 三票制：同平台同皮肤 3/3；异皮肤不判可批量",
        pos_ok and neg_ok,
        "正例 %d/%d 平台=%s 皮肤=%s；负例 %d/%d 平台=%s 皮肤=%s"
        % (d["yes"], d["voted"], d["plat_b"][0], d["gen_b"],
           d2["yes"], d2["voted"], d2["plat_b"][0], d2["gen_b"]))




# ---------------------------------------------------------------- T11 3b 交集判据
def t11_tier3b():
    import three_votes as tv
    raw = str(FIX / "homes")
    a = tv.collect(raw, "cangnan")
    b = tv.collect(raw, "lianyungangrc")
    d = tv.votes(a, b)
    o = d["res"]["outbound"]
    ok = bool(o) and o[0] and o[4] == "3b" and bool(o[5])
    rec("T11 3b：跨省站靠交集+平台域名过票3", ok,
        "tier=%s 交集=%s 平台核心=%s 票=%d/%d"
        % (o[4] if o else "-", o[3] if o else "-", o[5] if o else "-",
           d["yes"], d["voted"]))


# ---------------------------------------------------------------- T12 皮肤分代
def t12_skin_gen():
    import three_votes as tv
    raw = str(FIX / "homes")
    a = tv.collect(raw, "cangnan")
    expect = {"longgangrc": "A", "yuhangrc": "A", "suqianrc": "B", "r6_chinajsjob": "B"}
    bad = []
    for name, want in expect.items():
        d = tv.votes(a, tv.collect(raw, name))
        if d["gen_b"] != want:
            bad.append("%s 期望%s 实得%s(路径%s)" % (name, want, d["gen_b"], d["paths_b"]))
    rec("T12 皮肤分代：A/B 可区分（含江苏人才网=B）", not bad,
        "违规 %d %s" % (len(bad), bad[:2]))


# ---------------------------------------------------------------- T13 截断修复 + 平台分轴
def t13_truncation_and_platform():
    import three_votes as tv
    import fingerprint_offline as fp
    raw = str(FIX / "homes")
    # ① 截断修复：江苏人才网出站 87 个，全部进 outbound_all
    r = fp.analyze(str(ROOT / "tests" / "data" / "_probe_r6_chinajsjob_home.html"), "")
    all_n = len(r.get("outbound_all") or [])
    # ② 平台分轴：chinajsjob 平台应为 jrzp（资源引用 191 次），皮肤 B
    a, b = tv.collect(raw, "cangnan"), tv.collect(raw, "r6_chinajsjob")
    d = tv.votes(a, b)
    ok = (all_n >= 80 and d["plat_b"][0] == "jrzp" and d["plat_b"][1] >= 20
          and d["gen_b"] == "B" and d["yes"] == 1)
    rec("T13 全量出站 + 平台分轴：江苏人才网=jrzp/B、票 1/3", ok,
        "outbound_all=%d 平台=%s(%d) 皮肤=%s 票=%d/%d" %
        (all_n, d["plat_b"][0], d["plat_b"][1], d["gen_b"], d["yes"], d["voted"]))




# ---------------------------------------------------------------- T14/15/16 锚文本城市识别
def _mk_html(path, anchors):
    body = "".join('<a href="https://%s/">%s</a>' % (d, t) for d, t in anchors)
    Path(path).write_text("<html><body>%s</body></html>" % body, encoding="utf-8")


def t14_anchor_city():
    import fingerprint_offline as fp
    p = RAW / "_tmp_t14.html"
    _mk_html(p, [
        ("hz1.com", "杭州人才网"), ("sx1.com", "绍兴人才网"), ("jx1.com", "嘉兴招聘网"),
        ("noise1.com", "蓝蜻蜓无人机培训"), ("noanchor.com", ""),
    ])
    keep, drop = fp.resolve_city(str(p), "浙江")
    cities = sorted(x["city"] for x in keep)
    ok = (set(cities) == {"杭州", "嘉兴", "绍兴"} and len(drop) == 2)
    rec("T14 锚文本城市识别：3 命中 / 2 丢弃", ok,
        "命中=%s 丢弃=%d" % (cities, len(drop)))
    p.unlink(missing_ok=True)


def t15_no_anchor_dropped():
    import fingerprint_offline as fp
    p = RAW / "_tmp_t15.html"
    _mk_html(p, [("www.zhangzhourcw.com", ""), ("www.ningborcw.com", "宁波人才网")])
    keep, drop = fp.resolve_city(str(p), "浙江")
    domains = [x["domain"] for x in keep]
    ok = ("www.zhangzhourcw.com" not in domains
          and "www.ningborcw.com" in domains)
    rec("T15 无锚文本外链不进候选（漳州站被丢弃）", ok,
        "命中=%s 丢弃=%d" % (domains, len(drop)))
    p.unlink(missing_ok=True)


def t16_province_filter():
    import fingerprint_offline as fp
    p = FIX / "_probe_r6a_chinazjrc_home.html"
    keep, drop = fp.resolve_city(str(p), "浙江", "www.chinazjrc.com")
    cities = {x["city"] for x in keep}
    want = {"杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水"}
    out_prov = [x for x in keep if x["city"] not in want]
    ok = (cities == want) and not out_prov
    # 邻省站必须被丢
    domains_drop = [x["domain"] for x in drop]
    chengdu = "www.changzhourcw.com" in domains_drop
    rec("T16 省域过滤：浙江 11/11 齐全、邻省不进清单", ok,
        "命中城市=%d 越界=%d 常州被丢=%s" % (len(cities), len(out_prov), chengdu))




# ---------------------------------------------------------------- T17 站点模块签名
def t17_site_signatures():
    """遍历 crawlers/sites/*.py：parse_list 必须可两参调用；
    parse_total_pages 若存在，**不允许因参数个数抛 TypeError**（v12、v13 各踩过一次）。"""
    import importlib
    import inspect
    sys.path.insert(0, str(ROOT / "crawlers"))   # 让 import sites.xxx 成立
    stub_html = "<html><body><title>t</title></body></html>"
    stub_url = "http://example.invalid/p1.html"
    bad = []
    checked = 0
    for p in sorted(Path(ROOT_SITES).glob("*.py")):
        if p.name.startswith("_"):
            continue
        name = p.stem
        try:
            mod = importlib.import_module("sites." + name)
        except Exception as e:
            bad.append("%s 导入失败 %s" % (name, type(e).__name__))
            continue
        checked += 1
        pl = getattr(mod, "parse_list", None)
        if pl is None or not callable(pl):
            bad.append("%s 缺 parse_list" % name)
            continue
        try:
            n = len([x for x in inspect.signature(pl).parameters.values()
                     if x.default is inspect.Parameter.empty])
            if n > 2:
                bad.append("%s parse_list 要 %d 个必填参数（引擎只给 2 个）" % (name, n))
        except (ValueError, TypeError):
            pass
        ptp = getattr(mod, "parse_total_pages", None)
        if ptp is not None:
            try:
                ptp(stub_html, stub_url)          # 引擎就是这么调的（两参）
            except TypeError as e:
                bad.append("%s parse_total_pages 两参调用抛 TypeError（%s）" % (name, e))
            except Exception:
                pass                              # 解析失败没关系，签名对就行
    rec("T17 站点模块签名：parse_list 两参可调、parse_total_pages 不抛 TypeError", not bad,
        "检查 %d 个模块，问题 %d %s" % (checked, len(bad), bad[:3]))


# ---------------------------------------------------------------- T18 市→省映射
def t18_region_map():
    sys.path.insert(0, str(ROOT_TOOLS))
    import region_map as rm
    cases = [("湖州市", "浙江"), ("温州市", "浙江"), ("义乌市", "浙江"),
             ("苏州市", "江苏"), ("昆山市", "江苏"), ("连云港市", "江苏"),
             ("商丘市", ""), ("荆门市", ""), ("", "")]
    bad = [(c, want, rm.province_of(c)) for c, want in cases if rm.province_of(c) != want]
    rec("T18 市→省映射：浙江/江苏命中、外省不误判", not bad,
        "用例 %d，错 %d %s" % (len(cases), len(bad), bad[:3]))




# ---------------------------------------------------------------- T19/T20 公告型解析
def t19_announcement_parse():
    sys.path.insert(0, str(ROOT_TOOLS))
    import announcement_parser as ap
    f = ROOT / "tests" / "data" / "fixtures" / "zjrs_announce_requests.html"
    if not f.exists():
        rec("T19 公告正文解析（title/日期/附件/正文）", False, "样本缺失 %s" % f)
        return
    d = ap.parse_announcement(f.read_text(encoding="utf-8", errors="replace"), str(f))
    ok = (d["title"].startswith("浙江省气象部门")
          and d["published"] == "2026-11-13"
          and d["body_len"] > 1000
          and len(d["attachments"]) == 4
          and len(d["job_tables"]) == 2
          and d["attachments"][0]["ext"] == ".xlsx")
    rec("T19 公告正文解析（title/日期/附件/正文）", ok,
        "标题=%s 发布=%s 正文=%d 附件=%d 岗位表=%d"
        % (d["title"][:16], d["published"], d["body_len"],
           len(d["attachments"]), len(d["job_tables"])))


def t20_jobtable_parse():
    sys.path.insert(0, str(ROOT_TOOLS))
    import announcement_parser as ap
    f = ROOT / "tests" / "data" / "fixtures" / "zjrs_岗位表.xlsx"
    if not f.exists():
        rec("T20 岗位表附件解析（表头识别 + 行数）", False, "样本缺失 %s" % f)
        return
    tabs = ap.parse_jobtable(str(f))
    ok = bool(tabs)
    detail = ""
    if ok:
        t = tabs[0]
        heads = "".join(t["header"])
        ok = ("拟安排岗位" in heads and "专业" in heads and "学历" in heads
              and t["n_rows"] >= 30)
        detail = "表=%s 表头=%s 行=%d" % (t["sheet"], t["header"][:3], t["n_rows"])
    rec("T20 岗位表附件解析（表头识别 + 行数）", ok, detail)




# ---------------------------------------------------------------- T21 jpaas 栏目接口
def t21_jpaas_list():
    sys.path.insert(0, str(ROOT_TOOLS))
    import json as _json
    import jpaas_list as jl
    shell = FIX / "_probe_c_rlsbt_zj_gov_cn_col.html"
    p1 = ROOT / "tests" / "data" / "fixtures" / "jpaas_unit_get.txt"
    p2 = ROOT / "tests" / "data" / "fixtures" / "jpaas_unit_p2_paramjson.txt"
    if not (shell.exists() and p1.exists() and p2.exists()):
        rec("T21 jpaas 栏目接口（参数/列表/分页）", False, "样本缺失")
        return

    info = jl.extract_unit_params(shell.read_text(encoding="utf-8", errors="replace"),
                                  "https://rlsbt.zj.gov.cn")
    prm = info["params"]
    params_ok = (prm.get("webId") == "2758" and prm.get("pageId") == "1229743683"
                 and prm.get("tagId") == "当前栏目列表" and prm.get("tplSetId"))

    def load(p):
        return _json.loads(p.read_text(encoding="utf-8"))["data"]["html"]

    f1, f2 = load(p1), load(p2)
    m1, m2 = jl.parse_meta(f1), jl.parse_meta(f2)
    i1, i2 = jl.parse_items(f1, "https://rlsbt.zj.gov.cn"), jl.parse_items(f2, "https://rlsbt.zj.gov.cn")
    list_ok = (m1["count"] == 367 and m1["page_no"] == 1 and len(i1) == 10
               and i1[0]["published"] == "2026-11-13")
    # 分页必须真的换内容（不是同一页）
    page_ok = (m2["page_no"] == 2 and len(i2) == 10
               and {x["url"] for x in i1}.isdisjoint({x["url"] for x in i2}))
    ok = params_ok and list_ok and page_ok
    rec("T21 jpaas 栏目接口（参数/列表/分页）", ok,
        "参数=%s count=%s 第1页=%d条 第2页=%d条 两页无交集=%s"
        % (bool(params_ok), m1["count"], len(i1), len(i2), page_ok))




# ---------------------------------------------------------------- T22 xls + 两行表头
def t22_legacy_xls_and_two_row_header():
    sys.path.insert(0, str(ROOT_TOOLS))
    import announcement_parser as ap
    fix = ROOT / "tests" / "data" / "fixtures"
    xls = fix / "zjrs_宁波大学2026年公开招聘高层次人才_教师_岗位计划表.xlsx"   # 实为 OLE .xls
    two = fix / "zjrs_浙江省文化广电和旅游厅部分直属事业单位公开招聘人员计划表_2026年第二批_.xlsx"
    if not (xls.exists() and two.exists()):
        rec("T22 老 .xls 解析 + 两行表头合并", False, "样本缺失")
        return
    t1 = ap.parse_jobtable(str(xls))
    ok1 = bool(t1) and t1[0]["n_rows"] == 87 and t1[0]["header"][0] == "部门名称"
    t2 = ap.parse_jobtable(str(two))
    ok2 = bool(t2) and "岗位名称" in "".join(t2[0]["header"]) and t2[0]["n_rows"] == 4
    rec("T22 老 .xls 解析 + 两行表头合并", ok1 and ok2,
        "宁波大学 行=%s 表头首列=%s | 文广旅 行=%s 表头=%s"
        % (t1[0]["n_rows"] if t1 else "-", t1[0]["header"][0] if t1 else "-",
           t2[0]["n_rows"] if t2 else "-", (t2[0]["header"][:3] if t2 else "-")))


# ---------------------------------------------------------------- T23-T27 v13.4 新代码（0 请求）
def t23_enum_b_sample():
    sys.path.insert(0, str(ROOT_TOOLS))
    import discover as dc
    csv_p = FIX / "v13_enum_v2.csv"
    if not csv_p.exists():
        rec("T23 枚举表 A 全收 + B 抽样", False, "样本缺失 %s" % csv_p)
        return
    import contextlib
    import io as _io
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        r1 = dc.from_enum(str(csv_p), b_sample=5)
        r2 = dc.from_enum(str(csv_p), b_sample=5)
    a = [x for x in r1 if x.get("置信度") == "A"]
    b = [x for x in r1 if x.get("verify_quota") == "b_sample"]
    same = [x["域名"] for x in r1] == [x["域名"] for x in r2]
    ok = len(a) == 16 and len(b) == 5 and same
    rec("T23 枚举表 A 全收 + B 抽样（固定种子）", ok,
        "A=%d B抽样=%d 两次一致=%s" % (len(a), len(b), same))


def t24_abbr_ambiguous():
    sys.path.insert(0, str(ROOT_TOOLS))
    import discover as dc
    idx = dc.build_abbr_index("浙江")
    zj, jx, tz = idx.get("zj", []), idx.get("jx", []), idx.get("tz", [])
    ok = (len(zj) > 1 and "浙江" in zj and "镇江" in zj
          and len(jx) > 1 and len(tz) > 1)
    rec("T24 缩写歧义不单选（zj/jx/tz）", ok,
        "zj=%s jx=%s tz=%s" % (zj, jx, tz))


def t25_concat_not_dot():
    sys.path.insert(0, str(ROOT_TOOLS))
    import discover as dc
    old = dc.dns_ok
    dc.dns_ok = lambda h, timeout=2.0: True          # 桩掉 DNS：0 网络
    try:
        rows = dc._gen_level([{"city": "杭州", "pinyin": "hangzhou", "abbr": "hz"}],
                             ["rc.com"], ["{pinyin}"], 1, {}, "市级")
        hosts = [r["域名"] for r in rows]
    finally:
        dc.dns_ok = old
    ok = hosts == ["hangzhourc.com"]
    rec("T25 域名拼接 concat 不是 dot", ok, "生成=%s" % hosts)


def t26_print_queries_no_dup():
    """--print-queries 现在必须带 goal，且只出那一类（不许 14 条全吐）。"""
    sys.path.insert(0, str(ROOT_TOOLS))
    import discover as dc
    import contextlib
    import io as _io

    def grab(goal):
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dc.print_queries("浙江", "", "食品", goal)
        qs = [l.strip() for l in buf.getvalue().splitlines()
              if l.startswith("  ") and l.strip()]
        return rc, qs

    rc_j, jobs = grab("jobs")
    rc_w, weather = grab("weather")
    rc_none, _ = grab("")            # 不给 goal → 必须报错
    rc_bad, _ = grab("nonsense")     # 非法 goal → 必须报错
    dup = sorted({q for q in jobs if jobs.count(q) > 1})
    # 两类互不串台：天气模板里不该出现"招聘"
    clean = (not any("招聘" in q for q in weather)) and (not any("气象" in q for q in jobs))
    ok = (rc_j == 0 and rc_w == 0 and rc_none == 2 and rc_bad == 2
          and len(jobs) >= 5 and not dup and clean)
    rec("T26 --print-queries 按 goal 只出一类、不重复、缺 goal 报错", ok,
        "jobs=%d weather=%d dup=%s 无goal_rc=%d 非法goal_rc=%d 不串台=%s"
        % (len(jobs), len(weather), dup[:3], rc_none, rc_bad, clean))


def t27_gov_roster():
    sys.path.insert(0, str(ROOT_TOOLS))
    import discover as dc
    zj = dc.from_gov_roster("浙江")
    doms = [r["域名"] for r in zj]
    ver = [r for r in zj if r["置信度"] == "已验证"]
    allr = dc.from_gov_roster("浙江", all_regions=True)
    ok = ("www.zjhr.com" in doms and len(ver) >= 1 and len(allr) >= 30
          and all("coverage" in r for r in zj))
    rec("T27 官方名录并入（浙江 + 全国）", ok,
        "浙江=%d 已验证=%d 全国=%d" % (len(zj), len(ver), len(allr)))

_venv_py = ROOT / "venv" / "Scripts" / "python.exe"
PY_BIN = str(_venv_py if _venv_py.exists() else sys.executable)


def _run_cli(args, timeout=60):
    """跑 discover.py 的 CLI（判型与 goal 都是 CLI 行为，只能这么测）。"""
    import subprocess
    import os
    env = dict(os.environ, PYTHONIOENCODING="utf-8")   # 子进程必须 UTF-8，否则管道下是 GBK
    r = subprocess.run([PY_BIN, str(ROOT_TOOLS / "discover.py")] + args,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(ROOT), timeout=timeout, env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def t28_weather_official_no_search():
    """A/D 型（天气）给了官方源 → 不检索、不枚举。"""
    rc, out = _run_cli(["--region", "浙江", "--mode", "single", "--goal", "weather",
                        "--seed", "https://example.invalid/", "--out",
                        str(ROOT / "logs" / "_t28.csv")])
    no_search = "第 1 步" not in out
    # 用"步骤日志"判断是否真的没跑，不用关键词 —— 说明文字里本来就写着"不跑页脚/域名/枚举"
    no_enum = all(("第 %d 步" % i) not in out for i in (2, 3, 4, 5))
    rec("T28 天气（A/D 型）给官方源 → 不搜索、不枚举", rc == 0 and no_search and no_enum,
        "rc=%d 无第1步=%s 无第2~5步=%s" % (rc, no_search, no_enum))


def t29_regulation_official_no_enum():
    """A 型（法规）给了官方平台 → 只名录+seed，不跑域名枚举。"""
    rc, out = _run_cli(["--region", "中国", "--mode", "single", "--goal", "regulation",
                        "--seed", "https://example.invalid/", "--out",
                        str(ROOT / "logs" / "_t29.csv")])
    no_enum = all(("第 %d 步" % i) not in out for i in (2, 3, 4, 5))
    rec("T29 法规（A 型）给官方平台 → 不枚举", rc == 0 and no_enum,
        "rc=%d 无第2~5步=%s" % (rc, no_enum))


def t30_account_zero_request():
    """C 型（拼多多价格）→ 0 请求、0 文件，只问账号。"""
    import time
    outp = ROOT / "logs" / "_t30_should_not_exist.csv"
    if outp.exists():
        outp.unlink()
    t0 = time.time()
    rc, out = _run_cli(["--mode", "account", "--goal", "price", "--out", str(outp)])
    dur = time.time() - t0
    ok = (rc == 0 and ("账号" in out) and ("0 请求" in out)
          and (not outp.exists()) and dur < 10)
    rec("T30 拼多多（C 型）→ 0 请求、不写文件、只问账号", ok,
        "rc=%d 提到账号=%s 无输出文件=%s 耗时=%.1fs"
        % (rc, "账号" in out, not outp.exists(), dur))


def t31_jobs_wide_must_search():
    """B 型（招聘）wide → 必须走第 1 步检索。"""
    rc, out = _run_cli(["--region", "浙江", "--mode", "wide", "--goal", "jobs",
                        "--skip-syntax", "--limit", "5", "--out",
                        str(ROOT / "logs" / "_t31.csv")])
    has_step1 = "第 1 步" in out
    has_f22 = "F-22" in out          # 没给 --search-result 时必须记成漏项
    rec("T31 招聘（B 型）wide → 必须检索 + F-22 计数", rc == 0 and has_step1 and has_f22,
        "rc=%d 有第1步检索=%s F-22=%s" % (rc, has_step1, has_f22))


def t32_goal_required_in_all_modes():
    """不给 --goal：即使给了 --mode 也必须 rc=2、0 请求、不写候选文件。"""
    outp = ROOT / "logs" / "_t32_should_not_exist.csv"
    if outp.exists():
        outp.unlink()
    rc, out = _run_cli(["--mode", "single", "--region", "浙江", "--out", str(outp)])
    ok = (rc == 2 and ("--goal 必填" in out) and (not outp.exists()))
    rec("T32 不给 --goal（即使有 --mode）→ rc=2、0 请求、不写文件", ok,
        "rc=%d 提到必填=%s 无文件=%s" % (rc, "--goal 必填" in out, not outp.exists()))


def t34_footer_anchor_not_domain():
    """F-14：页脚按锚文本识别，不按域名拼音筛（lagou 这类不再被静默丢掉）。"""
    import tempfile
    import discover as d
    old_raw = d.RAW
    with tempfile.TemporaryDirectory(prefix="foot_") as td:
        (Path(td) / "x_home.html").write_text(
            '<html><head><link rel="canonical" href="https://self.example/"></head><body>'
            '<a href="https://www.lagou.com/">招聘网</a>'
            '<a href="https://self.example/about">关于我们</a>'
            '</body></html>', encoding="utf-8")
        d.RAW = Path(td)
        try:
            rows = d.from_footer("浙江")
        finally:
            d.RAW = old_raw
    hosts = [r["域名"] for r in rows]
    ok = ("www.lagou.com" in hosts) and ("self.example" not in hosts)
    rec("T34 页脚按锚文本识别（lagou 不因域名不含 rc/job 被丢）", ok, "%s" % hosts)


def t35_known_platform_priors():
    """平台先验：后缀匹配 / 未知 / 过期三态。"""
    import copy
    import discover as d
    k = d.load_known_platforms()
    e1, s1 = d.match_known_platform("www.lagou.com", k)
    e2, s2 = d.match_known_platform("example.invalid", k)
    k2 = copy.deepcopy(k)
    hit = next(x for x in k2["platforms"] if x["id"] == "lagou")
    hit["verified_at"] = "2020-01-01"
    e3, s3 = d.match_known_platform("www.lagou.com", k2)
    ok = (bool(e1) and e1["id"] == "lagou" and s1 == "fresh"
          and e2 is None and s2 == "" and s3 == "stale")
    rec("T35 平台先验：后缀匹配 / 未知 / 过期 stale", ok,
        "%s|%s|%s" % (s1, s2 or "-", s3))


def t36_known_platform_in_cli():
    """CLI：--seed 命中已知平台 → 0 请求给结论，并写进 CSV 的「平台判定」列。"""
    outp = ROOT / "logs" / "_t36_known.csv"
    if outp.exists():
        outp.unlink()
    rc, out = _run_cli(["--region", "浙江", "--mode", "single", "--goal", "jobs",
                        "--seed", "https://www.lagou.com/", "--out", str(outp)])
    head, body = "", ""
    if outp.exists():
        txt = outp.read_text(encoding="utf-8-sig")
        head = txt.split("\n")[0]
        body = txt
    ok = (rc == 0 and "平台先验" in out and "平台判定" in head
          and "lagou.com" in body and "blocked" in body)
    rec("T36 CLI：已知平台命中 → 0 请求给结论并写进 CSV", ok,
        "rc=%d 命中=%s 列=%s" % (rc, "平台先验" in out, "平台判定" in head))


def t33_wide_rejects_ad_goal():
    """--goal weather/regulation + --mode wide 必须拒绝：rc=2、0 请求、不生成候选文件。"""
    results = []
    for goal in ("weather", "regulation"):
        outp = ROOT / "logs" / ("_t33_should_not_exist_%s.csv" % goal)
        if outp.exists():
            outp.unlink()
        rc, out = _run_cli(["--mode", "wide", "--goal", goal, "--region", "浙江",
                            "--out", str(outp)])
        results.append((goal, rc, "--force-wide" in out, outp.exists()))
    ok = all(rc == 2 and not exist and mentioned
             for _, rc, mentioned, exist in results)
    rec("T33 A/D 型 goal + wide → rc=2、0 请求、不写文件、提示 --force-wide", ok,
        "; ".join("%s rc=%d 提示force=%s 文件=%s" % (g, rc, m, e)
                  for g, rc, m, e in results))


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    print("v13 离线测试（0 请求）")
    print("=" * 62)
    t1_negative()
    t2_ast_no_network()
    t6_jaccard()
    t8_domain_recall()
    t9_resolver_rules()
    t10_three_votes()
    t11_tier3b()
    t12_skin_gen()
    t13_truncation_and_platform()
    t14_anchor_city()
    t15_no_anchor_dropped()
    t16_province_filter()
    t17_site_signatures()
    t18_region_map()
    t19_announcement_parse()
    t20_jobtable_parse()
    t21_jpaas_list()
    t22_legacy_xls_and_two_row_header()
    t23_enum_b_sample()
    t24_abbr_ambiguous()
    t25_concat_not_dot()
    t26_print_queries_no_dup()
    t27_gov_roster()
    t28_weather_official_no_search()
    t29_regulation_official_no_enum()
    t30_account_zero_request()
    t31_jobs_wide_must_search()
    t32_goal_required_in_all_modes()
    t34_footer_anchor_not_domain()
    t35_known_platform_priors()
    t36_known_platform_in_cli()
    t33_wide_rejects_ad_goal()
    print("=" * 62)
    passed = sum(1 for _, ok, _ in results if ok)
    print("结果：%d/%d 通过" % (passed, len(results)))
    for n, ok, d in results:
        if not ok:
            print("  未通过：%s  %s" % (n, d))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
