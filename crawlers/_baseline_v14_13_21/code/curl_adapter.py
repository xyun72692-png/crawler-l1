# -*- coding: utf-8 -*-
"""T1 传输层适配器（v14 阶段 1）。

**这不是"换 Session 类"，是适配层。**
`crawlers/crawler.py` 的闸门挂在 `GatedSession.send()` 上；而 `curl_cffi.requests.Session`
不是 `requests.Session` 的子类，直接替换会同时打断：

  · gate.before() —— 速率/预算/时长全失效
  · 重定向逐跳计数 —— 302 不计入预算，实际请求数被低估
  · requests.RequestException 异常族 —— 引擎的 except 分支匹配不上
  · 附件 stream + iter_content
  · r.apparent_encoding（curl_cffi 没有这个属性）

所以这里做的事：
  1. 对外接口与 requests.Session 一致：.get / .request / .send / .cookies / .headers / .close
  2. **每个真实 HTTP 请求（含每一跳重定向）都过 gate.before()**
  3. 重定向手动逐跳跟随（allow_redirects=False），并逐跳计数
  4. curl_cffi 的异常包装成 requests.RequestException 家族
  5. 响应包一层，补 apparent_encoding / iter_content / close，其余属性透传

默认**不启用**：站点 CONFIG 里写 `"transport": "cffi"` 才会用到它。
（`"plain"` = 现在的 GatedSession，默认值；`"browser"` = v14 阶段 2 的渲染通道）
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import requests

try:                                     # curl_cffi 没装时不能把整个引擎拖死
    from curl_cffi import requests as cffi_requests
    from curl_cffi import CurlError
    HAVE_CFFI = True
except Exception:                        # pragma: no cover
    cffi_requests = None
    CurlError = Exception
    HAVE_CFFI = False

import identity

DEFAULT_IMPERSONATE = identity.DEFAULT_IMPERSONATE
MAX_REDIRECTS = 10
_REDIRECT_CODES = (301, 302, 303, 307, 308)


# --------------------------------------------------------------------------- #
# 响应包装：让引擎看到的东西与 requests.Response 一致
# --------------------------------------------------------------------------- #
class CurlResponse:
    """把 curl_cffi 的响应包成"引擎认识的样子"。

    引擎实际用到的只有：status_code / text / content / headers / encoding /
    apparent_encoding / url / iter_content / close。其余属性透传。
    """

    def __init__(self, raw, url=None, hops=None):
        self._raw = raw
        self.url = url or getattr(raw, "url", "") or ""
        self.redirect_hops = hops or 0
        self.history = []                # 与 requests 一致：只用于记录，不参与判定
        self.status_code = getattr(raw, "status_code", 0)
        self.headers = getattr(raw, "headers", {}) or {}
        self._content = None
        self._text = None

    # -- 内容 ---------------------------------------------------------- #
    @property
    def content(self):
        if self._content is None:
            self._content = self._raw.content or b""
        return self._content

    @property
    def encoding(self):
        return getattr(self._raw, "encoding", None)

    @encoding.setter
    def encoding(self, value):
        try:
            self._raw.encoding = value
        except Exception:
            pass

    @property
    def apparent_encoding(self):
        """curl_cffi 没有这个属性；按字节自己判断（引擎会在没声明 charset 时用它）。

        注意：**不能直接信 self.encoding** —— curl_cffi 默认给的可能是 utf-8，
        但页面实际是 GBK（引擎历史上就踩过这个）。只信 Content-Type/meta 里显式写的
        charset，其余一律用字节严格解码来定。
        """
        ct = (self.headers.get("Content-Type") or "").lower()
        m0 = re.search(r'charset=["\']?([\w-]+)', ct)
        if m0:
            return m0.group(1)
        body = self.content
        if not body:
            return "utf-8"
        head = body[:4096].decode("latin-1", errors="ignore").lower()
        m = re.search(r'charset=["\']?([\w-]+)', head)
        if m:
            return m.group(1)
        try:
            body.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
        for cand in ("gb18030", "gbk", "big5"):
            try:
                body.decode(cand)
                return cand
            except UnicodeDecodeError:
                continue
        return "utf-8"

    @property
    def text(self):
        if self._text is None:
            body = self.content
            enc = self.encoding
            if enc and enc.lower() not in ("iso-8859-1", "ascii"):
                try:
                    self._text = body.decode(enc)          # 严格解码：失败就说明声明错了
                except (UnicodeDecodeError, LookupError):
                    self._text = body.decode(self.apparent_encoding or "utf-8",
                                             errors="replace")
            else:
                self._text = body.decode(self.apparent_encoding or "utf-8",
                                         errors="replace")
        return self._text

    # -- 流式（附件用）------------------------------------------------- #
    def iter_content(self, chunk_size=65536, decode_unicode=False):
        return self._raw.iter_content(chunk_size=chunk_size)

    def raise_for_status(self):
        if 400 <= self.status_code:
            raise requests.HTTPError("%s for %s" % (self.status_code, self.url))

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass

    def __getattr__(self, item):
        return getattr(self._raw, item)


# --------------------------------------------------------------------------- #
# 会话适配器
# --------------------------------------------------------------------------- #
class CurlSessionAdapter:
    """对外像 requests.Session，内里是 curl_cffi（TLS 指纹冒充）。"""

    def __init__(self, impersonate=DEFAULT_IMPERSONATE, headers=None, timeout=20):
        if not HAVE_CFFI:
            raise RuntimeError("curl_cffi 没装：pip install curl_cffi==0.17.0")
        self.impersonate = impersonate
        self.timeout = timeout
        self._sess = cffi_requests.Session(impersonate=impersonate)
        # 身份统一由 identity 决定：UA / Sec-CH-UA / Sec-Fetch-* 同源
        base = identity.headers()
        if headers:
            base.update(headers)
        self._sess.headers.update(base)
        self.headers = self._sess.headers
        self.cookies = self._sess.cookies
        self.requests_made = 0           # 本会话真实请求数（含每跳重定向）

    # -- 闸门 ---------------------------------------------------------- #
    def _gate(self, url):
        """每个真实请求（含每一跳）都要过。闸门没开时静默跳过。"""
        import crawler                    # 延迟导入，避免循环引用
        host = (urlsplit(url).hostname or "").lower()
        g = crawler.gate_mod.current_gate()
        if g is not None and not crawler.gate_mod.host_exempt(host):
            g.before(host)
        crawler._note_request(host)
        self.requests_made += 1

    # -- 核心 ---------------------------------------------------------- #
    def _one(self, url, method="GET", headers=None, timeout=None, stream=False, **kw):
        self._gate(url)
        try:
            return self._sess.request(
                method, url, headers=headers or None,
                timeout=timeout or self.timeout,
                allow_redirects=False, stream=stream, **kw)
        except CurlError as e:                              # 网络层错误
            raise requests.ConnectionError(str(e)) from e
        except Exception as e:                              # 其它一律按请求异常处理
            if isinstance(e, requests.RequestException):
                raise
            raise requests.RequestException(str(e)) from e

    def request(self, method, url, headers=None, timeout=None, allow_redirects=True,
                stream=False, **kw):
        """GET/POST 通用入口。重定向**手动逐跳**跟随，每跳都过闸门。"""
        hops = 0
        cur = url
        r = self._one(cur, method=method, headers=headers, timeout=timeout,
                      stream=stream, **kw)
        while allow_redirects and r.status_code in _REDIRECT_CODES and hops < MAX_REDIRECTS:
            loc = (r.headers or {}).get("Location") or (r.headers or {}).get("location")
            if not loc:
                break
            try:
                r.close()
            except Exception:
                pass
            cur = urljoin(cur, loc)
            hops += 1
            r = self._one(cur, method="GET", headers=headers, timeout=timeout,
                          stream=stream)
        return CurlResponse(r, url=cur, hops=hops)

    def get(self, url, **kw):
        kw.pop("allow_redirects", None) if False else None
        return self.request("GET", url, **kw)

    def post(self, url, data=None, json=None, **kw):
        if json is not None:
            kw["json"] = json
        elif data is not None:
            kw["data"] = data
        return self.request("POST", url, **kw)

    # 引擎里只剩这两处会用到 send()（附件重定向逐跳那套自己管）
    def send(self, prepared, **kw):
        kw.pop("allow_redirects", None)
        return self.request(prepared.method, prepared.url,
                            headers=getattr(prepared, "headers", None), **kw)

    def close(self):
        try:
            self._sess.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 工厂：给 crawler.py 用
# --------------------------------------------------------------------------- #
def build_session(transport="plain", **kw):
    """transport: plain → None（由引擎自己造 GatedSession）；cffi → CurlSessionAdapter。

    返回 None 表示"请引擎用默认的 GatedSession"。
    """
    t = (transport or "plain").lower()
    if t in ("plain", "", "requests"):
        return None
    if t in ("cffi", "curl", "curl_cffi"):
        return CurlSessionAdapter(**kw)
    if t == "browser":
        raise RuntimeError("transport=browser 属于 v14 阶段 2（渲染通道），当前未接入")
    raise ValueError("未知 transport：%r（只认 plain / cffi / browser）" % transport)