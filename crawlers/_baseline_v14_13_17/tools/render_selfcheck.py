#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""§4.1.1 渲染指纹自检（v14 阶段 2 开工前必跑，0 HTTP 请求）。

六项（任一不过 → 先修 identity，不许开批量渲染）：
  ① navigator.webdriver === false
  ② UA 与 Sec-CH-UA 的品牌/版本一致（Chrome 152 就都得是 152）
  ③ WebGL vendor/renderer 不是 SwiftShader / ANGLE 软件渲染
  ④ navigator.plugins.length > 0
  ⑤ 与同机真 Chrome 对比：UA / Sec-CH-UA / Accept-Language / 时区 四项一致
  ⑥ 页面能正常执行 JS（setTimeout 写 DOM）

用法：
    python tools/render_selfcheck.py            # 用 identity 的默认身份
    python tools/render_selfcheck.py --json-out out/render_selfcheck.json
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "crawlers"))
sys.dont_write_bytecode = True

import identity  # noqa: E402
import stealth   # noqa: E402

import http.server
import json as _json
import socketserver
import threading

ECHO = {}          # 服务端最后一次收到的请求头（给主流程读）


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/echo"):
            ECHO.clear()
            for k, v in self.headers.items():
                ECHO[k.lower()] = v
            self._send(200, _json.dumps(dict(ECHO), ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        else:
            body = (b"<html><head><title>selfcheck</title></head><body>"
                    b"<div id='out'>pending</div><div id='echo'>pending</div>"
                    b"<script>"
                    b"setTimeout(function(){document.getElementById('out').textContent='js-ok';},50);"
                    b"fetch('/echo').then(r=>r.text()).then(t=>{document.getElementById('echo').textContent=t;});"
                    b"</script></body></html>")
            self._send(200, body)


def start_echo_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _EchoHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]

PROBE_JS = """() => {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
  let vendor = '', renderer = '';
  if (gl) {
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    if (ext) {
      vendor = gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) || '';
      renderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '';
    } else {
      vendor = gl.getParameter(gl.VENDOR) || '';
      renderer = gl.getParameter(gl.RENDERER) || '';
    }
  }
  const uaData = navigator.userAgentData || null;
  return {
    webdriver: navigator.webdriver,
    ua: navigator.userAgent,
    brands: uaData ? uaData.brands : null,
    platform_ua: uaData ? uaData.platform : null,
    languages: navigator.languages,
    plugins: navigator.plugins ? navigator.plugins.length : 0,
    hw: navigator.hardwareConcurrency,
    webgl_vendor: vendor,
    webgl_renderer: renderer,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    out_text: (document.getElementById('out') || {}).textContent || '',
  };
}"""


def launch(p):
    """按 chrome → msedge → bundled 顺序找可用浏览器；统一带 stealth 启动参数。"""
    for ch in ("chrome", "msedge", None):
        try:
            b = p.chromium.launch(**stealth.launch_kwargs(channel=ch, headless=True))
            return b, (ch or "bundled")
        except Exception:
            continue
    raise RuntimeError("没有可用的浏览器通道（chrome / msedge / bundled 都不行）")


def read_page(browser, ctx_kwargs, url, wait_ms=600):
    ctx = browser.new_context(**ctx_kwargs)
    stealth.prepare_context(ctx)
    page = ctx.new_page()
    page.goto(url)
    page.wait_for_timeout(wait_ms)
    data = page.evaluate(PROBE_JS)
    try:
        data["echo"] = _json.loads(page.evaluate(
            "() => document.getElementById('echo').textContent") or "{}")
    except Exception:
        data["echo"] = {}
    ctx.close()
    return data


def ver_of(ua):
    for seg in (ua or "").split():
        if seg.startswith("Chrome/"):
            return seg.split("/")[1].split(".")[0]
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=str(ROOT / "out" / "render_selfcheck.json"))
    args = ap.parse_args()

    ident = identity.IDENTITY
    want = ident["version"]           # T1（curl_cffi）身份版本
    results = []

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, channel = launch(p)

        real_version = browser.version          # 例：157.0.8103.51
        srv, port = start_echo_server()
        url = "http://127.0.0.1:%d/selfcheck" % port
        # 我们的渲染上下文：按真实版本生成身份，UA 与 Sec-CH-UA 同时覆盖
        ours = read_page(browser, identity.for_playwright_actual(real_version), url)
        # 基线：完全默认上下文（只用于对齐语言/时区，UA 因 headless 带 HeadlessChrome 不作数）
        real = read_page(browser, {}, url)
        srv.shutdown()

        real_major = str(real_version).split(".")[0]
        t2_ident = identity.playwright_identity(real_version)
        browser.close()

    def add(name, ok, detail=""):
        results.append({"check": name, "ok": bool(ok), "detail": detail})
        print("  %s %-46s %s" % ("PASS" if ok else "FAIL", name, detail))

    print("浏览器通道：%s ｜ 真实版本：%s ｜ T1 身份版本：%s" % (channel, real_version, want))

    # ① webdriver
    add("① navigator.webdriver === false", ours["webdriver"] is False,
        "webdriver=%r" % ours["webdriver"])

    # ② UA 与 Sec-CH-UA 同源（都等于 identity.version）
    ua_major = ver_of(ours["ua"])
    hdr_ua = (ours.get("echo") or {}).get("user-agent", "")
    hdr_ch = (ours.get("echo") or {}).get("sec-ch-ua", "")
    ch_major = "?"
    import re as _re
    m = _re.search(r'Chromium";v="(\d+)"', hdr_ch)
    if m:
        ch_major = m.group(1)
    ok2 = (ua_major == real_major) and (ch_major == real_major) and (ver_of(hdr_ua) == real_major)
    add("② UA 与 Sec-CH-UA 版本一致（且等于真实浏览器）", ok2,
        "js_UA=%s / hdr_UA=%s / CH-UA=%s / 真实=%s"
        % (ua_major, ver_of(hdr_ua), ch_major, real_major))

    # ③ WebGL 不是软渲染
    rnd = (ours.get("webgl_renderer") or "").lower()
    soft = ("swiftshader" in rnd) or ("software" in rnd) or (rnd == "")
    add("③ WebGL 非软渲染", not soft,
        "%s / %s" % ((ours.get("webgl_vendor") or "?")[:28], (ours.get("webgl_renderer") or "?")[:40]))

    # ④ plugins
    add("④ navigator.plugins.length > 0", int(ours.get("plugins") or 0) > 0,
        "plugins=%s" % ours.get("plugins"))

    # ⑤ 与真 Chrome 四项一致
    diffs = []
    if ua_major != real_major:
        diffs.append("UA 主版本 ours=%s real=%s" % (ua_major, real_major))
    if real.get("brands") and ours.get("brands") != real.get("brands"):
        diffs.append("Sec-CH-UA ours=%r real=%r" % (ours.get("brands"), real.get("brands")))
    if ours.get("languages") != real.get("languages"):
        diffs.append("语言 ours=%r real=%r" % (ours.get("languages"), real.get("languages")))
    if ours.get("tz") != real.get("tz"):
        diffs.append("时区 ours=%r real=%r" % (ours.get("tz"), real.get("tz")))
    add("⑤ 与同机真 Chrome 四项一致（主版本/品牌/语言/时区）", not diffs,
        "；".join(diffs)[:150] or "四项全同")

    # ⑥ JS 能执行
    add("⑥ JS 能正常执行（setTimeout 写 DOM）", ours.get("out_text") == "js-ok",
        "out=%r" % ours.get("out_text"))

    payload = {
        "channel": channel,
        "expected_version": want,
        "real_browser_version": real_version,
        "t2_identity": t2_ident,
        "identity_card": identity.card(),
        "checks": results,
        "ours": ours,
        "echo_headers": ours.get("echo"),
        "real_chrome": real,
        "passed": sum(1 for r in results if r["ok"]),
        "total": len(results),
        "verdict": "OK" if all(r["ok"] for r in results) else "FIX_IDENTITY_FIRST",
    }
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n结果：%d/%d 通过 → %s" % (payload["passed"], payload["total"], payload["verdict"]))
    print("→", out)
    return 0 if payload["verdict"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())