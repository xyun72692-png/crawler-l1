# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""提案5：probe_pagesize 补第 2 页重叠检查 + 冷却用站点自己的 state_dir；mock 补 /ps 路由与 mockprobe 站点。"""
from pathlib import Path

# ---------------------------------------------------------------- 1) probe 脚本
P = Path(str(_HOME / "scripts" / "probe_pagesize.py"))
s = P.read_text(encoding="utf-8")

def sub(old, new, why):
    global s
    assert old in s, "未命中：" + why
    assert s.count(old) == 1, "命中多处：" + why
    s = s.replace(old, new, 1)

sub('''def _cooldown_state(cfg):
    """读冷却文件（和爬虫同一套规则：存在且未到期就不探测）。"""
    from crawler import cooldown_group, load_cooldown, cooldown_until
    from datetime import datetime
    from crawler import TZ
    host = urlsplit(cfg["url_template"].format(page=cfg.get("page_start", 1))).netloc.lower()
    key = cooldown_group(host)''',
    '''def _cooldown_state(cfg):
    """
    读冷却文件（和爬虫同一套规则：存在且未到期就不探测）。

    关键：必须先把 crawler.CONFIG["state_dir"] 换成**该站点自己的** state_dir，
    否则会去默认目录找一个根本不存在的冷却文件（等于没检查）。
    """
    import crawler
    from crawler import cooldown_group, load_cooldown, cooldown_until
    from datetime import datetime
    from crawler import TZ
    if cfg.get("state_dir"):
        crawler.CONFIG["state_dir"] = cfg["state_dir"]
    if cfg.get("soft_block"):
        crawler.CONFIG["soft_block"] = cfg["soft_block"]
    host = urlsplit(cfg["url_template"].format(page=cfg.get("page_start", 1))).netloc.lower()
    key = cooldown_group(host)''',
    "1) 冷却用站点 state_dir")

# 抓取时同时收集条目 URL，供重叠检查用
sub('''    def probe(u, label):
        _sleep()
        r = sess.get(u, timeout=25, headers={"Referer": base + "/"})
        html = r.text or ""
        cards = len(re.findall(r'class="[^"]*J_jobsList', html)) if "J_jobsList" in html else None
        if cards is None:                      # 非 wzrc 系站点：数通用卡片
            cards = len(re.findall(r'<div class="[^"]*item', html))
        m = re.search(r"</span>\\s*/\\s*(\\d+)\\s*页", html)
        fake = ("no_page_group" in html) or (r.status_code == 200 and cards == 0)
        return {"label": label, "status": r.status_code, "bytes": len(r.content),
                "cards": cards, "declared_pages": int(m.group(1)) if m else None,
                "fake_page": fake}''',
    '''    def probe(u, label):
        _sleep()
        r = sess.get(u, timeout=25, headers={"Referer": base + "/"})
        html = r.text or ""
        cards = len(re.findall(r'class="[^"]*J_jobsList', html)) if "J_jobsList" in html else None
        if cards is None:                      # 非 wzrc 系站点：数通用卡片
            cards = len(re.findall(r'<div class="[^"]*item', html))
        links = re.findall(r'href="([^"]+)"', html)
        links = [x for x in links if "/d/" in x or "jobinfo" in x or "jobs/" in x]
        m = re.search(r"</span>\\s*/\\s*(\\d+)\\s*页", html)
        fake = ("no_page_group" in html) or (r.status_code == 200 and cards == 0)
        return {"label": label, "status": r.status_code, "bytes": len(r.content),
                "cards": cards, "declared_pages": int(m.group(1)) if m else None,
                "fake_page": fake, "links": links}''',
    "2) 记录条目链接")

# 判定后：卡片变多才做第 2 页重叠检查
sub('''    base_res = probe(url0, "baseline")''',
    '''    url2 = cfg["url_template"].format(page=2)
    sep2 = "&" if "?" in url2 else "?"
    url2 = url2 + sep2 + "%s=%s" % (a.param, a.value)

    base_res = probe(url0, "baseline")''',
    "3) 预生成第 2 页 URL")

sub('''    if not same_cards:
        out["verdict"] = "effective"
        out["note"] = "卡片数 %s → %s，参数有效" % (base_res["cards"], pr["cards"])''',
    '''    if not same_cards and out["requests"] < MAX_REQUESTS:
        # 卡片真的变多了：再验一件更关键的事——**分页有没有被搞坏**。
        # 参数生效但页码错位（第 2 页和第 1 页内容重复）比"参数无效"更危险：
        # 会让人以为抓了 N 条，实际大量重复。
        p2 = probe(url2, "page2")
        out["requests"] += 1
        out["checks"]["page2"] = p2
        overlap = set(pr["links"]) & set(p2["links"])
        if p2["fake_page"]:
            out["verdict"] = "unknown"
            out["note"] = "第 2 页变成假页面，不下结论"
            print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else out["note"])
            return 6
        if overlap:
            out["verdict"] = "broken_pagination"
            out["note"] = ("卡片数变多（%s→%s）但第 2 页与第 1 页有 %d 条重复 → "
                           "分页被打乱，不能直接用这个参数"
                           % (base_res["cards"], pr["cards"], len(overlap)))
            print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else
                  "结论：broken_pagination\\n%s（共 %d 个请求）" % (out["note"], out["requests"]))
            return 3
        out["verdict"] = "effective"
        out["note"] = "卡片数 %s → %s，参数有效；第 2 页无重叠" % (base_res["cards"], pr["cards"])
    elif not same_cards:
        out["verdict"] = "effective"
        out["note"] = "卡片数 %s → %s，参数有效（请求额度已用完，未验第 2 页）" % (
            base_res["cards"], pr["cards"])''',
    "4) 第 2 页重叠检查")

P.write_text(s, encoding="utf-8", newline="\n")
print("probe_pagesize.py 已更新")

# ---------------------------------------------------------------- 2) mock /ps 路由
M = Path(str(_HOME / "tests" / "mock_site.py"))
m = M.read_text(encoding="utf-8")
anchor = '        # ---- 提案1：带"共 M 页"声明的列表页'
assert anchor in m
route = '''        # ---- 提案5：页大小探测用（size= 控制卡片数；MOCK_PS_BROKEN=1 时第 2 页与第 1 页重复）----
        if path.startswith("/ps/p") and path.endswith(".html"):
            try:
                n = int(path[len("/ps/p"):-len(".html")])
            except ValueError:
                self._send(404, b"bad page")
                return
            qs4 = parse_qs(urlparse(self.path).query)
            try:
                size = int((qs4.get("size") or [""])[0] or 5)
            except ValueError:
                size = 5
            size = max(1, min(size, 8))
            broken = os.environ.get("MOCK_PS_BROKEN") == "1"
            page_for_ids = 1 if (broken and n == 2) else n
            items = "".join(
                "<div class=\\"item\\"><a href=\\"/d/ps-%d-%d\\">j%d-%d</a></div>"
                % (page_for_ids, i, page_for_ids, i) for i in range(1, size + 1))
            body = ("<html><body><div class=\\"list\\">%s</div>"
                    "<div class=\\"l5\\"><span>%d</span>/3页</div></body></html>"
                    % (items, n))
            self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
            return

'''
m = m.replace(anchor, route + anchor, 1)
M.write_text(m, encoding="utf-8", newline="\n")
print("mock /ps 路由已加")