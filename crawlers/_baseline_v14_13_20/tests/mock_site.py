# -*- coding: utf-8 -*-
"""
本地 mock 站点：给爬虫做故障注入测试用，全程不出网。

启动：
    python mock_site.py            # 前台跑，Ctrl+C 停
    python mock_site.py --port 8765

页面（每页 3 条）：
    /v1/p1.html     正常
    /v1/p2.html     正常（内容不同）
    /v1/p3.html     空页（没有 .item）
    /v1/p4.html     空页
    /v1/p5.html     空页
    /v1/p6.html     403
    /v1/p7.html     正常，但用于测 robots 禁止

robots.txt 模式由 --robots 控制：
    none        返回 404（= 未设限）
    allow       允许全部
    deny-p2     允许 /v1/p1.html，禁止 /v1/p2.html
    forbid-all  禁止全部
    err403      robots.txt 本身返回 403
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATE = {"robots_mode": "none"}

# 计数器：用于"失败 N 次后成功"，验证重试真的在退避重试而不是盲目重跑
_COUNTERS = {}
_COUNTERS_LOCK = threading.Lock()


def bump_hit(path):
    with _COUNTERS_LOCK:
        _HITS[path] = _HITS.get(path, 0) + 1
        return _HITS[path]


_HITS = {}


def bump(key):
    with _COUNTERS_LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0) + 1
        return _COUNTERS[key]

PAGE_TMPL = """<!doctype html>
<html><head><title>mock page {n}</title></head><body>
<h1>Page {n}</h1>
<div class="list">
{items}
</div>
</body></html>
"""

ITEM_TMPL = """  <div class="item">
    <a class="title" href="/detail/{n}-{i}">Item {n}-{i}</a>
    <span class="note">note-{n}-{i}</span>
  </div>"""


def build_page(n, count=3):
    items = "\n".join(ITEM_TMPL.format(n=n, i=i) for i in range(1, count + 1))
    return PAGE_TMPL.format(n=n, items=items)


EMPTY_PAGE = """<!doctype html>
<html><head><title>empty</title></head><body>
<h1>Nothing here</h1>
<div class="list"></div>
</body></html>
"""

# =====================================================================
# 详情阶段测试用（阶段1）：/d/<kind>/p1.html 一页 20 条，
# 每条链到 /detail/<kind>-<i>，detail 的行为由 kind 决定。
#   ok      → 200，字段齐全
#   fail    → 永远 500（测失败率熔断）
#   slow    → 睡 3 秒（测超时/重试）
#   forbid  → 403（测遇到拒绝立刻整体停）
#   nofield → 200 但缺 span.pub（测必填字段校验）
#   flaky   → 每个 URL 第一次 500，第二次起 200（测"下次自动补抓"）
# =====================================================================
DETAIL_LIST_TMPL = """<!doctype html>
<html><head><title>detail list {kind}</title></head><body>
<h1>Detail list {kind}</h1>
<div class="list">
{items}
</div>
</body></html>
"""

DETAIL_ITEM_TMPL = """  <div class="di">
    <a class="dt" href="/detail/{kind}-{i}">DItem {kind}-{i}</a>
  </div>"""

DETAIL_PAGE_TMPL = """<!doctype html>
<html><head><title>detail {name}</title></head><body>
<div class="dbody">
<h1>Item {name}</h1>
{pub}
<span class="st">ok</span>
</div>
</body></html>
"""


def build_detail_list(kind, count=20):
    items = "\n".join(DETAIL_ITEM_TMPL.format(kind=kind, i=i) for i in range(1, count + 1))
    return DETAIL_LIST_TMPL.format(kind=kind, items=items)


def build_detail_page(name, with_pub=True):
    pub = '<span class="pub">PUB-%s</span>' % name if with_pub else ""
    return DETAIL_PAGE_TMPL.format(name=name, pub=pub)


# =====================================================================
# 阶段3：JSON 接口测试用（/api/ 开头）
#   GET  /api/items?page=N      {"code":0,"data":{"total":9,"items":[3 条]}}
#   POST /api/post              回显收到的 body 类型，返回 3 条
#   GET  /api/bizerror          HTTP 200 但 {"code":5001}（业务错误）
#   GET  /api/empty             {"code":0,"data":{"items":[]}}
#   GET  /api/missing           只有部分字段（测 field_map 缺键）
#   GET  /api/next?p=1          响应里带 next URL，最后一页 next 为 null
#   GET  /api/cursor?cursor=X   响应里带 next_cursor，最后一页为 null
#   GET  /api/notjson           HTTP 200 但返回 HTML（测"200 但不是 JSON"）
# =====================================================================
def build_json_items_reltime(n=3):
    """同一批条目，但 created 是**每请求递增的相对时间**（测 content_hash 稳定性）。"""
    bump("reltime")
    m = _COUNTERS.get("reltime", 0) * 2 + 28     # 28、30、32… 分钟前
    return [{"name": "rel-%d" % i,
             "link": "/detail/rel-%d" % i,
             "created": "%d分钟前" % m} for i in range(1, n + 1)]


def build_json_items(prefix, n=3):
    return [{"name": "%s-%d" % (prefix, i),
             "link": "/detail/%s-%d" % (prefix, i),
             "created": "2026-11-%02d" % (i + 1)} for i in range(1, n + 1)]


JSON_PAGE_TMPL = None  # 直接用 json.dumps，不需要模板

DETAIL_KINDS = ("ok", "fail", "slow", "forbid", "nofield", "flaky")

# =====================================================================
# 阶段2：next 分页测试用页面（/n/ 开头）
#   每页 3 条 item，页面底部可能有 <a class="next"> 指向下一页
#   /n/page1 → page2 → page3 → 无下一页        （正常三页）
#   /n/loop1 ⇄ /n/loop2                        （翻页循环）
#   /n/self1 → 自己                             （自指）
#   /n/dup1?a=1&b=2 → /n/dup1?b=2&a=1          （参数顺序不同，归一化后同一页）
#   /n/broken1 → 500                            （第一页就挂，读不到下一页）
#   /n/inf/pN → /n/inf/pN+1                     （无限链，用来测 max_pages / 续跑）
# =====================================================================
NEXT_PAGE_TMPL = """<!doctype html>
<html><head><title>{name}</title></head><body>
<h1>{name}</h1>
<div class="list">
{items}
</div>
{next_link}
</body></html>
"""


def build_next_page(name, prefix, next_href=None, count=3, boom=False):
    items = "\n".join(ITEM_TMPL.format(n=prefix, i=i) for i in range(1, count + 1))
    nxt = ('<a class="next" href="%s">下一页</a>' % next_href) if next_href else ""
    # div.boom 让 mocknext.parse_next 抛异常（测"解析器坏了不能报成没下一页"）
    boom_mark = '<div class="boom"></div>' if boom else ""
    return NEXT_PAGE_TMPL.format(name=name, items=items,
                                 next_link=nxt + boom_mark)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # 测试时看请求次数很重要（验证 403 不重试、rebuild-index 不发请求）
        sys.stderr.write("[mock] %s %s\n" % (self.command, self.path))

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_HEAD(self):
        self._send(200, b"")

    def do_POST(self):
        # POST 与 GET 走同一套路由：/api/post 需要读 body，
        # 其它路径按 GET 的规则处理即可（测试里不区分这么细）
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?")[0]
        mode = STATE["robots_mode"]

        if path == "/__ping":
            self._send(200, b"pong", "text/plain")
            return

        # ---- v14 T2：真 JS 渲染页（render_batch 用）----
        if path == "/spa/img.png":
            png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                   b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
                   b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
            self._send(200, png, "image/png")
            return

        if path == "/spa/style.css":
            self._send(200, b".job{display:block}", "text/css; charset=utf-8")
            return

        if path in ("/spa/js.html", "/spa/js_many.html"):
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            pg = int((qs.get("page") or ["1"])[0])
            n_img = 120 if path == "/spa/js_many.html" else 2
            imgs = "".join('<img src="/spa/img.png?i=%d">' % i for i in range(n_img))
            body = ("<!doctype html><html><head><title>render-test</title>"
                    "<link rel=\"stylesheet\" href=\"/spa/style.css\"></head><body>"
                    "<div id=\"list\">loading</div>" + imgs +
                    "<script>"
                    "fetch('/spa/api/list?page=%d').then(r=>r.json()).then(d=>{"
                    "  var box=document.getElementById('list'); box.innerHTML='';"
                    "  d.data.items.forEach(function(it){"
                    "    var a=document.createElement('a'); a.className='job';"
                    "    a.href=it.link; a.textContent=it.name; box.appendChild(a);});"
                    "  document.title='render-ok';"
                    "}).catch(function(e){document.getElementById('list').textContent='err';});"
                    "</script></body></html>" % pg).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
            return

        # ---- SPA 实验：空壳页面 + 内嵌 JSON + 后端接口 ----
        if path == "/spa/index.html":
            payload = {"props": {"pageProps": {"items": [
                {"id": "s1", "name": "内嵌一", "link": "/detail/s1"},
                {"id": "s2", "name": "内嵌二", "link": "/detail/s2"}]}}}
            body = ("<!doctype html><html><head><title>spa</title></head><body>"
                    "<div id=\"__next\"></div>"
                    "<script id=\"__NEXT_DATA__\" type=\"application/json\">"
                    + json.dumps(payload, ensure_ascii=False) +
                    "</script></body></html>").encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path == "/spa/api/list":
            # 这里在顶层，q 还没定义 → 自己解析查询串
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            pg = int((qs.get("page") or ["1"])[0])
            items = [{"id": "a%d" % (pg * 10 + i),
                      "name": "接口%d-%d" % (pg, i),
                      "link": "/detail/a%d" % (pg * 10 + i)}
                     for i in range(1, 4)]
            body = json.dumps({"code": 0, "data": {"items": items}},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return


        # ---- 阶段A：Retry-After 实验 ----
        if path == "/ra/retry":
            n = bump("/ra/retry#n")
            mode = (parse_qs(urlparse(self.path).query).get("mode") or ["sec"])[0]
            if n <= 1:
                self.send_response(429)
                if mode == "sec":
                    self.send_header("Retry-After", "2")
                elif mode == "date":
                    from email.utils import format_datetime
                    from datetime import datetime, timedelta, timezone
                    dt = datetime.now(timezone.utc) + timedelta(seconds=3)
                    self.send_header("Retry-After", format_datetime(dt, usegmt=True))
                # mode=none：不给 Retry-After
                body = b"slow down"
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send(200, b"<html><body><div class=item>ok</div></body></html>",
                       "text/html; charset=utf-8")
            return

        # ---- 阶段A：软封对照实验（正常页 / 假页 / canary）----
        if path.startswith("/soft/"):
            bump_hit(path)
            qs2 = parse_qs(urlparse(self.path).query)
            blocked = ((qs2.get("m") or ["blocked"])[0] != "ok")
            # canary：ok 时一定有卡片（它代表"已知有结果的页"）
            if path == "/soft/canary.html":
                if blocked:
                    # 故意和列表页字节数不同（46 vs 50），这样才能验证
                    # 证据里的 resp_bytes 取的是被拦页而不是 canary
                    body = b"<html><body><div>no_page_group c</div></body></html>"
                else:
                    body = (b"<html><body><div class=card>a</div>"
                            b"<div class=card>b</div></body></html>")
                self._send(200, body, "text/html; charset=utf-8")
                return
            # 列表页：两种模式下都是 0 卡片（模拟"这一页/整站被换成了空壳"）
            if blocked:
                body = b"<html><body><div>no_page_group</div></body></html>"
            else:
                body = b"<html><body><div>list-empty</div></body></html>"
            self._send(200, body, "text/html; charset=utf-8")
            return

        # ---- 阶段A：Referer 回显 ----
        if path == "/echo/ref":
            qs = parse_qs(urlparse(self.path).query)
            pg = (qs.get("page") or ["1"])[0]
            ref = self.headers.get("Referer") or ""
            body = json.dumps({"code": 0, "data": {"items": [
                {"name": ref, "link": "/d/%s" % pg}]}},
                ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return

        if path == "/robots.txt":
            if mode == "none":
                self._send(404, b"not found")
            elif mode == "err403":
                self._send(403, b"forbidden")
            elif mode == "forbid-all":
                body = b"User-agent: *\nDisallow: /\n"
                self._send(200, body, "text/plain")
            elif mode == "deny-p2":
                body = b"User-agent: *\nDisallow: /v1/p2.html\n"
                self._send(200, body, "text/plain")
            elif mode == "deny-detail":
                # 列表页允许、详情页禁止 —— 测"详情 URL 也要过 robots"
                body = b"User-agent: *\nDisallow: /detail/\n"
                self._send(200, body, "text/plain")
            elif mode == "deny-files":
                # 附件目录禁止：测 robots 拒附件
                body = b"User-agent: *\nDisallow: /files-deny/\n"
                self._send(200, body, "text/plain")
            elif mode == "html":
                # 200，但内容是 HTML（模拟 WAF / 软 404）——必须 fail-closed
                body = (b"<!doctype html><html><head><title>Access Verification</title>"
                        b"</head><body>verify</body></html>")
                self._send(200, body, "text/html; charset=utf-8")
            elif mode == "robots500":
                # robots.txt 自己 500：不能当作允许
                self._send(500, b"boom")
            elif mode == "robotstimeoutonce":
                # 第一次故意睡 5 秒（超过客户端 2 秒超时），第二次正常返回
                n = bump("/robots.txt#to")
                if n <= 1:
                    time.sleep(5)
                    self._send(200, b"User-agent: *\\nAllow: /\\n", "text/plain")
                else:
                    self._send(200, b"User-agent: *\\nAllow: /\\n", "text/plain")
            elif mode == "robots500once":
                # 第一次 500，第二次 200：测主入口 robots 重试
                n = bump("/robots.txt")
                if n <= 1:
                    self._send(500, b"boom")
                else:
                    self._send(200, b"User-agent: *\\nAllow: /\\n", "text/plain")
            elif mode == "crawldelay":
                body = b"User-agent: *\nAllow: /\nCrawl-delay: 1\n"
                self._send(200, body, "text/plain")
            else:  # allow
                body = b"User-agent: *\nAllow: /\n"
                self._send(200, body, "text/plain")
            return

        if path == "/v1/p6.html":
            self._send(403, b"forbidden")
            return

        # p8: 永远 500 —— 测"重试耗尽后放弃"
        if path == "/v1/p8.html":
            n = bump(path)
            sys.stderr.write("[mock] p8 hit %d -> 500\n" % n)
            self._send(500, b"server error")
            return

        # p9: 前两次 500，第三次 200 —— 测"退避重试后成功"
        if path == "/v1/p9.html":
            n = bump(path)
            sys.stderr.write("[mock] p9 hit %d\n" % n)
            if n <= 2:
                self._send(500, b"server error")
            else:
                self._send(200, build_page(9).encode("utf-8"))
            return

        # p10: 慢响应（默认 3 秒）—— 测"超时不无限等"
        if path == "/v1/p10.html":
            n = bump(path)
            sys.stderr.write("[mock] p10 hit %d -> sleep 3s\n" % n)
            time.sleep(3)
            self._send(200, build_page(10).encode("utf-8"))
            return

        if path in ("/v1/p3.html", "/v1/p4.html", "/v1/p5.html"):
            self._send(200, EMPTY_PAGE.encode("utf-8"))
            return

        # ---- 状态断言用：p1 正常，p2 及以后一律 500（造"部分失败/全失败"）----
        if path.startswith("/mix/p") and path.endswith(".html"):
            try:
                n = int(path[len("/mix/p"):-len(".html")])
            except ValueError:
                self._send(404, b"bad page")
                return
            k = bump(path)
            sys.stderr.write("[mock] mix p%d hit %d\n" % (n, k))
            if n <= 1:
                self._send(200, build_page(n).encode("utf-8"))
            else:
                self._send(500, b"server error")
            return

        # ---- 提案5：页大小探测用（size= 控制卡片数；MOCK_PS_BROKEN=1 时第 2 页与第 1 页重复）----
        if (path.startswith("/ps/p") or path.startswith("/psb/p")) and path.endswith(".html"):
            broken_path = path.startswith("/psb/")
            pref = "/psb/p" if broken_path else "/ps/p"
            try:
                n = int(path[len(pref):-len(".html")])
            except ValueError:
                self._send(404, b"bad page")
                return
            qs4 = parse_qs(urlparse(self.path).query)
            try:
                size = int((qs4.get("size") or [""])[0] or 5)
            except ValueError:
                size = 5
            size = max(1, min(size, 8))
            broken = broken_path or os.environ.get("MOCK_PS_BROKEN") == "1"
            page_for_ids = 1 if (broken and n == 2) else n
            items = "".join(
                "<div class=\"item\"><a href=\"/d/ps-%d-%d\">j%d-%d</a></div>"
                % (page_for_ids, i, page_for_ids, i) for i in range(1, size + 1))
            body = ("<html><body><div class=\"list\">%s</div>"
                    "<div class=\"l5\"><span>%d</span>/3页</div></body></html>"
                    % (items, n))
            self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
            return

        # ---- 提案1：带"共 M 页"声明的列表页（MOCK_TOTAL=none 表示不声明）----
        if path.startswith("/tot/p") and path.endswith(".html"):
            try:
                n = int(path[len("/tot/p"):-len(".html")])
            except ValueError:
                self._send(404, b"bad page")
                return
            qs3 = parse_qs(urlparse(self.path).query)
            total = (qs3.get("t") or [os.environ.get("MOCK_TOTAL", "3")])[0]
            marker = ("" if total in ("", "none")
                      else "<div class=\"l5\"><span>%d</span>/%s页</div>" % (n, total))
            items = "".join("<div class=\"item\"><a href=\"/d/tot-%d-%d\">t%d-%d</a></div>"
                             % (n, i, n, i) for i in range(1, 4))
            body = ("<html><body><div class=\"list\">%s</div>%s</body></html>"
                    % (items, marker))
            self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path.startswith("/v1/p") and path.endswith(".html"):
            try:
                n = int(path[len("/v1/p"):-len(".html")])
            except ValueError:
                self._send(404, b"bad page")
                return
            self._send(200, build_page(n).encode("utf-8"))
            return

        # ---- A5：每页 5 条的变体（对齐真实站 wzrc 的每页条数）----
        # 为什么要它：window 模式的"连续 15 条见过就停"是按 5 条/页算的（3 页=15 条）；
        # 默认 v1 每页只有 3 条，3 页才 9 条，永远到不了 15 → 测不出提前停。
        if path.startswith("/v5/p") and path.endswith(".html"):
            try:
                n = int(path[len("/v5/p"):-len(".html")])
            except ValueError:
                self._send(404, b"bad page")
                return
            self._send(200, build_page(n, count=5).encode("utf-8"))
            return

        # ---- 阶段4：附件下载测试 ----
        if path.startswith("/files/") or path.startswith("/files-deny/"):
            bump_hit(path)
            me = "http://127.0.0.1:%d" % self.server.server_address[1]
            if path == "/files/slowchunk.pdf":
                # 每块只有 4 字节："%PDF-"（5 字节）会被切成两块，
                # 用来验证 magic 校验会先攒够字节再判，而不是拿第一块直接比。
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                data = b"%PDF-1.4\n" + b"E" * 200
                for i in range(0, len(data), 4):
                    part = data[i:i + 4]
                    self.wfile.write(b"%x\r\n" % len(part) + part + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                return
            if path == "/files/fake.pdf":
                # 扩展名是 .pdf，文件头却是 MZ（改名伪装）
                self._send(200, b"MZ" + b"\\x00" * 40, "application/pdf")
                return
            if path == "/files/note.txt":
                self._send(200, b"hello", "text/plain")
                return
            if path == "/files/nolen.pdf":
                # 故意不发 Content-Length，用 chunked 分块传 4096 字节
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                data = b"%PDF-1.4\n" + b"D" * (4096 - 9)
                for i in range(0, len(data), 512):
                    part = data[i:i + 512]
                    self.wfile.write(b"%x\r\n" % len(part) + part + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                return
            if path == "/files/retry.pdf":
                n = bump("/files/retry.pdf#n")
                if n <= 1:
                    self._send(500, b"not yet")     # 5xx = 可重试
                else:
                    self._send(200, b"%PDF-1.4\\nRETRY", "application/pdf")
                return
            if path == "/files/flaky.pdf":
                n = bump_hit(path + "#n")
                if n <= 1:
                    self._send(500, b"boom")
                else:
                    self._send(200, b"%PDF-1.4\nFLAKY", "application/pdf")
                return
            if path == "/files/to-internal.pdf":
                # 302 到内网地址：必须在【发请求前】就拦下
                self.send_response(302)
                self.send_header("Location", "http://10.255.255.1/secret.pdf")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/files/ok.pdf":
                self._send(200, b"%PDF-1.4\n" + b"A" * 40 + b"\n%%EOF\n",
                           "application/pdf")
                return
            if path == "/files/ok2.pdf":
                self._send(200, b"%PDF-1.4\n" + b"B" * 60 + b"\n%%EOF\n",
                           "application/pdf")
                return
            if path == "/files/big.pdf":
                # 精确 2048 字节（测试要断言具体字节数）
                self._send(200, b"%PDF-1.4\n" + b"C" * (2048 - 9), "application/pdf")
                return
            if path == "/files/type.exe":
                self._send(200, b"MZ" + b"\x00" * 30, "application/octet-stream")
                return
            if path == "/files/noctype.bin":
                self._send(200, b"\x89PNG" + b"\x00" * 30, "image/png")
                return
            if path == "/files/redir.pdf":
                # 302 到被 robots 禁止的目录：最终 URL 也要检查
                self.send_response(302)
                self.send_header("Location", me + "/files-deny/secret.pdf")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/files-deny/secret.pdf":
                self._send(200, b"%PDF-1.4\nSECRET", "application/pdf")
                return
            if path == "/files/missing.pdf":
                self._send(404, b"not found")
                return
            self._send(404, b"not found")
            return

        # ---- 阶段3：JSON 接口路由 ----
        if path.startswith("/api/"):
            q = parse_qs(urlparse(self.path).query)

            def send_json(obj, code=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self._send(code, body, "application/json; charset=utf-8")

            if path == "/api/att":
                # 阶段4：带附件的列表。me 用真实端口拼绝对地址
                me = "http://127.0.0.1:%d" % self.server.server_address[1]
                case = (q.get("case") or ["ok"])[0]
                files = {
                    "ok": ["/files/ok.pdf", "/files/ok2.pdf"],
                    "many": ["/files/ok.pdf?i=%d" % i for i in range(1, 8)],
                    "big": ["/files/big.pdf"],
                    "quota": ["/files/big.pdf?q=1", "/files/big.pdf?q=2",
                              "/files/big.pdf?q=3"],
                    "robots": ["/files-deny/secret.pdf"],
                    "redir": ["/files/redir.pdf"],
                    "mixed": ["/files/ok.pdf", "/files/missing.pdf", "/files/type.exe"],
                    "noctype": ["/files/noctype.bin"],
                    "nolen": ["/files/nolen.pdf"],
                    "flaky": ["/files/flaky.pdf"],
                    "tointernal": ["/files/to-internal.pdf"],
                    "dupname": ["/files/ok.pdf?a=1", "/files/ok.pdf?b=2"],
                    "txt": ["/files/note.txt"],
                    "fakepdf": ["/files/fake.pdf"],
                    "dns": ["http://evil.example/x.pdf"],
                    "retry": ["/files/retry.pdf"],
                    "slowchunk": ["/files/slowchunk.pdf"],
                }.get(case, ["/files/ok.pdf"])
                items = [{
                    "name": case,
                    "link": "/detail/att-%s" % case,
                    # 全部附件挂在【同一条记录】上：这样才能测"单条记录附件数上限"
                    # 已经是完整 URL 的原样用，其余补成绝对地址
                    "files": [(f if f.startswith("http") else me + f) for f in files],
                }]
                if case == "dupsame":
                    # 同一页里两条完全相同的记录（detail_url 相同）
                    items = [{"name": "dup-1", "link": "/detail/dup-1",
                              "files": [me + "/files/ok.pdf"]},
                             {"name": "dup-2", "link": "/detail/dup-1",
                              "files": [me + "/files/ok.pdf"]}]
                if case == "optfield":
                    # 两条记录，只有一条带 attachments：字段签名不能被它带偏
                    items = [{"name": "opt-1", "link": "/detail/opt-1",
                              "files": [me + "/files/ok.pdf"]},
                             {"name": "opt-2", "link": "/detail/opt-2"}]
                if case == "dupname":
                    # 再加一条记录，附件同名：用来验证"按记录分目录 + 不覆盖"
                    items.append({
                        "name": case + "-second",
                        "link": "/detail/att-%s-2" % case,
                        "files": [me + "/files/ok.pdf?c=3"],
                    })
                send_json({"code": 0, "data": {"total": len(items), "items": items}})
                return

            if path == "/api/att2":
                # 两页，每页 1 条记录、1 个 2048B 附件：测跨页累计配额
                p = int((q.get("page") or ["1"])[0])
                me2 = "http://127.0.0.1:%d" % self.server.server_address[1]
                send_json({"code": 0, "data": {"total": 1, "items": [{
                    "name": "p%d" % p,
                    "link": "/detail/att2-%d" % p,
                    "files": [me2 + "/files/big.pdf?page=%d" % p],
                }]}})
                return

            if path == "/api/hits":
                target = (q.get("p") or [""])[0]
                send_json({"code": 0, "data": {"hits": _HITS.get(target, 0)}})
                return

            if path == "/api/reltime":

                body = json.dumps({"code": 0, "data": {"total": 3,

                                    "items": build_json_items_reltime(3)}},

                                  ensure_ascii=False).encode("utf-8")

                self._send(200, body, "application/json; charset=utf-8")

                return


            if path == "/api/items":
                n = int((q.get("page") or ["1"])[0])
                # total 只报"这一页能给多少"——多页接口自报总数在 /api/totalwrong 里单独测
                send_json({"code": 0, "msg": "ok",
                           "data": {"total": 3, "page": n,
                                    "items": build_json_items("p%d" % n)}})
                return

            if path == "/api/totalwrong":
                # 自报总数 99，实际只给 3 条 → 必须报 json_total_mismatch
                send_json({"code": 0, "data": {"total": 99,
                                               "items": build_json_items("tw")}})
                return

            if path == "/api/global":
                # 数字分页 + 全局总数 9（每页 3 条）
                n = int((q.get("page") or ["1"])[0])
                send_json({"code": 0, "data": {"total": 9,
                                               "items": build_json_items("g%d" % n)}})
                return

            if path == "/api/globalbad":
                # next 分页 + 全局总数 99（实际只有 9 条）→ 抓完后必须报总数不符
                p = int((q.get("p") or ["1"])[0])
                nxt = "/api/globalbad?p=%d" % (p + 1) if p < 3 else None
                send_json({"code": 0, "data": {"total": 99,
                                               "items": build_json_items("gb%d" % p),
                                               "next": nxt}})
                return

            if path == "/api/post":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                ctype = self.headers.get("Content-Type") or ""
                if "json" in ctype:
                    got = json.loads(raw or b"{}")
                    kind = "json"
                else:
                    got = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
                    kind = "form"
                # 把收到的 page 写进条目名，测试才能断言"第二页的参数真的变了"
                tag = "post%s" % (got.get("page") or "?")
                send_json({"code": 0, "data": {
                    "kind": kind, "received": got,
                    "items": build_json_items(tag)}})
                return

            if path == "/api/mixed":
                # 列表里混进非对象条目：字符串 / null / 数字
                send_json({"code": 0, "data": {"total": 5, "items": [
                    {"name": "好条目-1", "link": "/detail/mx-1", "created": "2026-11-01"},
                    "这不是对象",
                    None,
                    {"name": "好条目-2", "link": "/detail/mx-2", "created": "2026-11-02"},
                    123,
                ]}})
                return

            if path == "/api/cursor0":
                # 游标从 0 开始，0 是合法值，结束值用 -1
                cur = (q.get("cursor") or ["0"])[0]
                step = int(cur)
                nxt = str(step + 1) if step < 2 else "-1"
                send_json({"code": 0, "data": {"items": build_json_items("z%d" % step),
                                               "next_cursor": nxt}})
                return

            if path == "/api/bizerror":
                send_json({"code": 5001, "msg": "quota exceeded", "data": None})
                return

            if path == "/api/empty":
                send_json({"code": 0, "data": {"total": 0, "items": []}})
                return

            if path == "/api/missing":
                # 故意只有 name，没有 link / created
                send_json({"code": 0, "data": {"items": [{"name": "只有名字-1"},
                                                        {"name": "只有名字-2"}]}})
                return

            if path == "/api/next":
                p = int((q.get("p") or ["1"])[0])
                nxt = "/api/next?p=%d" % (p + 1) if p < 3 else None
                send_json({"code": 0, "data": {"items": build_json_items("n%d" % p),
                                               "next": nxt}})
                return

            if path == "/api/cursor":
                cur = (q.get("cursor") or [""])[0]
                step = int(cur) if cur.isdigit() else 1
                nxt = str(step + 1) if step < 3 else None
                send_json({"code": 0, "data": {"items": build_json_items("c%d" % step),
                                               "next_cursor": nxt}})
                return

            if path == "/api/notjson":
                self._send(200, b"<html><body>login required</body></html>")
                return

            send_json({"code": 404, "msg": "no such api"}, 404)
            return

        # ---- 阶段2：next 分页路由 ----
        if path.startswith("/n/"):
            NEXT_MAP = {
                "/n/page1.html": ("page1", "p1", "/n/page2.html"),
                "/n/page2.html": ("page2", "p2", "/n/page3.html"),
                "/n/page3.html": ("page3", "p3", None),
                "/n/loop1.html": ("loop1", "l1", "/n/loop2.html"),
                "/n/loop2.html": ("loop2", "l2", "/n/loop1.html"),
                "/n/self1.html": ("self1", "s1", "/n/self1.html"),
                "/n/dup1.html":  ("dup1", "d1", "/n/dup1.html?b=2&a=1"),
            }
            if path in NEXT_MAP:
                nm, pref, nxt = NEXT_MAP[path]
                self._send(200, build_next_page(nm, pref, nxt).encode("utf-8"))
                return
            # 空页但有下一页：引擎必须继续翻，不能直接收工
            if path == "/n/empty1.html":
                self._send(200, build_next_page("empty1", "e1", "/n/page2.html",
                                               count=0).encode("utf-8"))
                return
            # 空页且没有下一页：按结束处理，但状态要记异常
            if path == "/n/emptyend.html":
                self._send(200, build_next_page("emptyend", "ee", None,
                                               count=0).encode("utf-8"))
                return
            # parse_next 会抛异常：解析器坏了 ≠ 没有下一页
            if path == "/n/boom1.html":
                self._send(200, build_next_page("boom1", "b1", "/n/page2.html",
                                               boom=True).encode("utf-8"))
                return
            if path == "/n/broken1.html":
                self._send(500, b"server error")
                return
            if path.startswith("/n/inf/p") and path.endswith(".html"):
                try:
                    n = int(path[len("/n/inf/p"):-len(".html")])
                except ValueError:
                    self._send(404, b"bad page")
                    return
                self._send(200, build_next_page("inf%d" % n, "i%d" % n,
                                                "/n/inf/p%d.html" % (n + 1)).encode("utf-8"))
                return
            self._send(404, b"not found")
            return

        # ---- 详情阶段测试路由（阶段1）----
        if path.startswith("/d/") and path.endswith("/p1.html"):
            kind = path[len("/d/"):-len("/p1.html")]
            if kind in DETAIL_KINDS:
                self._send(200, build_detail_list(kind).encode("utf-8"))
                return
            self._send(404, b"bad kind")
            return

        if path.startswith("/detail/"):
            name = path[len("/detail/"):]
            kind = name.split("-", 1)[0]
            if kind == "ok":
                self._send(200, build_detail_page(name).encode("utf-8"))
                return
            if kind == "nofield":
                self._send(200, build_detail_page(name, with_pub=False).encode("utf-8"))
                return
            if kind == "fail":
                n = bump(path)
                sys.stderr.write("[mock] detail fail %s hit %d -> 500\n" % (name, n))
                self._send(500, b"server error")
                return
            if kind == "flaky":
                # 每个 URL 第一次 500，之后 200 —— 用来验证"下次运行自动补抓"
                n = bump(path)
                sys.stderr.write("[mock] detail flaky %s hit %d\n" % (name, n))
                if n <= 1:
                    self._send(500, b"server error")
                else:
                    self._send(200, build_detail_page(name).encode("utf-8"))
                return
            if kind == "slow":
                n = bump(path)
                sys.stderr.write("[mock] detail slow %s hit %d -> sleep 3s\n" % (name, n))
                time.sleep(3)
                self._send(200, build_detail_page(name).encode("utf-8"))
                return
            if kind == "forbid":
                self._send(403, b"forbidden")
                return
            # 兼容旧用例：/detail/1-1 这种（没有 kind 前缀）
            self._send(200, b"<html><body>detail</body></html>")
            return

        self._send(404, b"not found")


def serve(port, robots_mode):
    STATE["robots_mode"] = robots_mode
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765,
                    help="0 = 让系统分配空闲端口（测试用；实际端口打印到 stdout）")
    ap.add_argument("--robots", default="none",
                    choices=["none", "allow", "deny-p2", "deny-detail", "deny-files",
                             "robots500", "robots500once", "robotstimeoutonce", "crawldelay",
                             "forbid-all", "err403", "html"])
    args = ap.parse_args()

    srv = serve(args.port, args.robots)
    actual = srv.server_address[1]
    # ⚠ 这一行是测试协议的约定：--port 0 时调用方要靠它知道真正的端口。
    # 必须 flush，否则父进程 readline 会一直等缓冲区。
    print("PORT=%d" % actual, flush=True)
    print("mock site on http://127.0.0.1:%d  robots=%s" % (actual, args.robots), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()