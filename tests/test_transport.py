# -*- coding: utf-8 -*-
"""v14 阶段 1：传输层适配器离线测试（T-TR-1 ~ T-TR-8）。

全部用本地 http.server，零外网。跑法：python tests\\test_transport.py
"""
import http.server
import os
import socket
import socketserver
import sys
import threading
from pathlib import Path

sys.dont_write_bytecode = True
AGENT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT / "crawlers"))

# 关键：测试环境里 gate.host_exempt() 会豁免回环地址（is_test_env 为真时），
# 那样就测不到"闸门有没有被调用"。CRAWLER_GATE_FORCE=1 强制不豁免。
os.environ["CRAWLER_GATE_FORCE"] = "1"

import requests                      # noqa: E402
import crawler                       # noqa: E402
import curl_adapter                  # noqa: E402
import identity                      # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %-52s %s" % ("PASS" if cond else "FAIL", name, detail))


# --------------------------------------------------------------------------- #
# 本地站点：/ok /302 → /302b → /ok /gbk /big /loop
# --------------------------------------------------------------------------- #
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ok":
            self._send(200, b"<html><title>OK</title><body>ok</body></html>")
        elif self.path == "/302":
            self._send(302, b"", extra={"Location": "/302b"})
        elif self.path == "/302b":
            self._send(302, b"", extra={"Location": "/ok"})
        elif self.path == "/gbk":
            body = "<html><body>南京人才网</body></html>".encode("gbk")
            self._send(200, body, ctype="text/html")
        elif self.path == "/big":
            self._send(200, b"x" * 200_000, ctype="application/octet-stream")
        elif self.path == "/loop":
            self._send(302, b"", extra={"Location": "/loop"})
        else:
            self._send(404, b"nope")


def start_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


class FakeGate:
    """只记账，不做限速——用来断言"每个真实请求都过闸门"。"""

    def __init__(self):
        self.hosts = []

    def before(self, host=""):
        self.hosts.append(host)


def main():
    srv, port = start_server()
    base = "http://127.0.0.1:%d" % port
    orig_current = crawler.gate_mod.current_gate

    # ---------------- T-TR-1 默认仍是 plain ----------------
    crawler.CONFIG["transport"] = "plain"
    s = crawler.session_factory()
    check("T-TR-1 默认 transport=plain → GatedSession", isinstance(s, crawler.GatedSession),
          type(s).__name__)
    s.close()

    # ---------------- T-TR-2 cffi 分支 + 身份一致 ----------------
    crawler.CONFIG["transport"] = "cffi"
    a = crawler.session_factory()
    ok2 = isinstance(a, curl_adapter.CurlSessionAdapter)
    ua_ok = a.headers.get("User-Agent") == identity.UA
    check("T-TR-2 transport=cffi → CurlSessionAdapter", ok2, type(a).__name__)
    check("T-TR-2 适配层 UA == identity.UA", ua_ok, a.headers.get("User-Agent", "")[:50])
    check("T-TR-2 impersonate 已生效", a.impersonate == identity.DEFAULT_IMPERSONATE, a.impersonate)
    check("T-TR-2 身份卡四项一致", identity.card()["consistent"] == "OK")

    # ---------------- T-TR-3 每个请求过闸门 ----------------
    fg = FakeGate()
    crawler.gate_mod.current_gate = lambda: fg
    try:
        r = a.get(base + "/ok", timeout=10)
        check("T-TR-3 单次请求 → 闸门 1 次", len(fg.hosts) == 1, "gate=%d" % len(fg.hosts))
        check("T-TR-3 记到的 host 是 127.0.0.1", fg.hosts[:1] == ["127.0.0.1"], str(fg.hosts[:2]))

        # ---------------- T-TR-4 302 逐跳计数 ----------------
        fg.hosts.clear()
        a.requests_made = 0
        r2 = a.get(base + "/302", timeout=10)
        check("T-TR-4 302 链跟到底（最终 200）", r2.status_code == 200, str(r2.status_code))
        check("T-TR-4 两跳各计一次（共 3 次）", a.requests_made == 3, "made=%d" % a.requests_made)
        check("T-TR-4 闸门也记 3 次", len(fg.hosts) == 3, "gate=%d" % len(fg.hosts))
        check("T-TR-4 redirect_hops == 2", r2.redirect_hops == 2, str(r2.redirect_hops))

        # 重定向上限：自环不能死循环
        a.requests_made = 0
        r3 = a.get(base + "/loop", timeout=10)
        check("T-TR-4 自环停在 MAX_REDIRECTS", a.requests_made <= curl_adapter.MAX_REDIRECTS + 1,
              "made=%d" % a.requests_made)
    finally:
        crawler.gate_mod.current_gate = orig_current

    # ---------------- T-TR-5 响应接口兼容 ----------------
    r = a.get(base + "/ok", timeout=10)
    for attr in ("status_code", "text", "content", "headers", "url",
                 "apparent_encoding", "encoding", "iter_content", "close"):
        pass
    ok5 = all(hasattr(r, x) for x in ("status_code", "text", "content", "headers", "url",
                                      "apparent_encoding", "encoding"))
    check("T-TR-5 响应字段齐全", ok5)
    check("T-TR-5 text 解出 OK", "OK" in r.text, r.text[:30])

    g = a.get(base + "/gbk", timeout=10)
    check("T-TR-5 无 charset 的 GBK 页能解对",
          "南京人才网" in (g.text or ""), repr((g.text or "")[:24]))
    check("T-TR-5 apparent_encoding 认成 gb 系",
          (g.apparent_encoding or "").lower().startswith(("gb", "gb18030")),
          str(g.apparent_encoding))

    # ---------------- T-TR-6 异常映射 ----------------
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()                                     # 端口空出来 → 连接必拒
    try:
        a.get("http://127.0.0.1:%d/x" % free_port, timeout=3)
        check("T-TR-6 连接失败抛 requests.ConnectionError", False, "没抛异常")
    except requests.ConnectionError:
        check("T-TR-6 连接失败抛 requests.ConnectionError", True)
    except Exception as e:
        check("T-TR-6 连接失败抛 requests.ConnectionError", False, type(e).__name__)

    # ---------------- T-TR-7 流式（附件）----------------
    st = a.get(base + "/big", timeout=10, stream=True)
    total = 0
    for chunk in st.iter_content(chunk_size=65536):
        total += len(chunk or b"")
    check("T-TR-7 stream + iter_content 读满 200KB", total == 200_000, "total=%d" % total)
    st.close()

    # ---------------- T-TR-8 transport 取值校验 ----------------
    try:
        curl_adapter.build_session("browser")
        check("T-TR-8 browser 明确拒绝（阶段 2 未接）", False)
    except RuntimeError:
        check("T-TR-8 browser 明确拒绝（阶段 2 未接）", True)
    try:
        curl_adapter.build_session("whatever")
        check("T-TR-8 未知 transport 抛 ValueError", False)
    except ValueError:
        check("T-TR-8 未知 transport 抛 ValueError", True)
    check("T-TR-8 plain 返回 None（引擎自造 GatedSession）",
          curl_adapter.build_session("plain") is None)

    # ---------------- T-TR-9 闸门参数边界 ----------------
    import gate as gate_mod
    bad_kw = [dict(max_rpm=0), dict(window_sec=0), dict(max_requests=-1),
              dict(max_seconds=-1), dict(jitter=(6, 4)), dict(jitter=(-1, 5)),
              dict(jitter=(float("inf"), 5))]
    ok_n = 0
    for kw in bad_kw:
        try:
            gate_mod.RequestGate(**kw)
        except ValueError:
            ok_n += 1
    check("T-TR-9 非法闸门参数一律 ValueError", ok_n == len(bad_kw),
          "%d/%d" % (ok_n, len(bad_kw)))
    # 0 预算是合法语义（立刻 fail-closed），不能被拒
    ok_zero = 0
    for kw in (dict(max_requests=0), dict(max_seconds=0)):
        try:
            gate_mod.RequestGate(**kw)
            ok_zero += 1
        except ValueError:
            pass
    check("T-TR-9b max_requests/max_seconds = 0 仍可构造", ok_zero == 2,
          "%d/2" % ok_zero)

    a.close()
    srv.shutdown()

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())