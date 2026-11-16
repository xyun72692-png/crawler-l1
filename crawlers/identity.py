# -*- coding: utf-8 -*-
"""唯一身份源（v14 阶段 0）。

规则（写死，别绕）：
  1. **全项目只允许本文件出现浏览器版本号**。其他任何地方要 UA / Sec-CH-UA /
     Sec-Fetch-* / Accept-*，一律 `from identity import UA, headers, for_playwright`。
  2. UA 主版本必须由 `version`（真浏览器）或 `impersonate`（curl_cffi 目标）**推导**，
     禁止手写常量。
  3. 同一份身份里 UA / Sec-CH-UA / Sec-Fetch-* 的版本必须一致；
     `identities_consistent()` 就是干这个检查的。
  4. 渲染通道**默认不覆盖 UA**（真浏览器用真 UA）。要覆盖必须同时覆盖 Sec-CH-UA。

为什么默认值是 152 而不是本机的 157：
    curl_cffi 的 impersonate 目标里 chrome 系列到 152；本机 Chrome 是 157。
    差 5 个版本落在"用户没及时更新"的合理区间，且只有 chrome152 这档同时带
    Windows 平台 + Sec-Fetch-*。换成 157 会与 impersonate 对不上，反而制造矛盾。
"""

from __future__ import annotations

import json
import sys

# ---- 全项目唯一的版本号常量（改这里，全项目跟着变）----
DEFAULT_BRAND = "chrome"
DEFAULT_VERSION = "152"
DEFAULT_IMPERSONATE = "chrome152"

_BRAND_LABEL = {
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "chromium": "Chromium",
}
_WIN_PLATFORM = '"Windows"'
_WIN_UA_PLATFORM = "Windows NT 10.0; Win64; x64"


def _major(version) -> str:
    return str(version).split(".")[0]


def build_identity(brand: str = DEFAULT_BRAND,
                   version=DEFAULT_VERSION,
                   impersonate: str | None = DEFAULT_IMPERSONATE,
                   accept_language: str = "zh-CN,zh;q=0.9,en;q=0.8") -> dict:
    """返回一份自洽的身份。四项版本必须同源，否则直接抛错（fail-closed）。"""
    brand = (brand or DEFAULT_BRAND).lower()
    if brand not in _BRAND_LABEL:
        raise ValueError("未知浏览器品牌：%r（只认 %s）" % (brand, list(_BRAND_LABEL)))

    major = _major(version)
    if impersonate:
        # impersonate 形如 chrome152 / chrome136；解析出来必须与 brand+version 一致
        digits = "".join(ch for ch in impersonate if ch.isdigit())
        letters = "".join(ch for ch in impersonate if ch.isalpha()).lower()
        if not digits:
            raise ValueError("impersonate 里没有版本号：%r" % impersonate)
        if digits != major:
            raise ValueError(
                "身份不同源：impersonate=%s 的版本 %s ≠ version=%s"
                % (impersonate, digits, major))
        if letters and letters != brand and not (brand == "msedge" and letters == "edge"):
            raise ValueError(
                "身份不同源：impersonate=%s 的品牌 %s ≠ brand=%s"
                % (impersonate, letters, brand))

    label = _BRAND_LABEL[brand]
    tail = " Edg/%s.0.0.0" % major if brand == "msedge" else ""
    ua = ("Mozilla/5.0 (%s) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/%s.0.0.0 Safari/537.36%s" % (_WIN_UA_PLATFORM, major, tail))

    ident = {
        "brand": brand,
        "version": major,
        "impersonate": impersonate or "",
        "ua": ua,
        "sec_ch_ua": '"Chromium";v="%s", "%s";v="%s", "Not-A.Brand";v="99"'
                     % (major, label, major),
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": _WIN_PLATFORM,
        "sec_fetch_site": "none",
        "sec_fetch_mode": "navigate",
        "sec_fetch_dest": "document",
        "sec_fetch_user": "?1",
        "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "accept_language": accept_language,
        "accept_encoding": "gzip, deflate, br, zstd",
    }
    bad = identities_consistent(ident)
    if bad:
        raise ValueError("身份不自洽：%s" % "；".join(bad))
    return ident


def identities_consistent(ident: dict | None = None) -> list:
    """检查版本/品牌是否同源。返回不一致项列表（空 = 自洽）。"""
    ident = ident or IDENTITY
    bad = []
    major = str(ident.get("version", ""))
    ua = ident.get("ua", "")
    ch = ident.get("sec_ch_ua", "")
    if ("Chrome/%s." % major) not in ua:
        bad.append("UA 主版本与 version 不一致（UA=%r, version=%s）" % (ua[:60], major))
    if ('v="%s"' % major) not in ch:
        bad.append("Sec-CH-UA 主版本与 version 不一致")
    imp = ident.get("impersonate") or ""
    if imp and "".join(c for c in imp if c.isdigit()) != major:
        bad.append("impersonate 与 version 不一致（%s vs %s）" % (imp, major))
    if ident.get("brand") == "msedge" and "Edg/" not in ua:
        bad.append("brand=msedge 但 UA 没有 Edg/ 尾巴")
    if ident.get("brand") == "chrome" and "Edg/" in ua:
        bad.append("brand=chrome 但 UA 带 Edg/ 尾巴（冒充了 Edge）")
    return bad


def headers(ident: dict | None = None, referer: str | None = None,
            sec_fetch: dict | None = None) -> dict:
    """一份完整的请求头。站点/工具只需覆盖自己真正不同的那一项（如 Referer）。"""
    ident = ident or IDENTITY
    h = {
        "User-Agent": ident["ua"],
        "Accept": ident["accept"],
        "Accept-Language": ident["accept_language"],
        "Accept-Encoding": ident["accept_encoding"],
        "sec-ch-ua": ident["sec_ch_ua"],
        "sec-ch-ua-mobile": ident["sec_ch_ua_mobile"],
        "sec-ch-ua-platform": ident["sec_ch_ua_platform"],
        "sec-fetch-site": (sec_fetch or {}).get("site", ident["sec_fetch_site"]),
        "sec-fetch-mode": (sec_fetch or {}).get("mode", ident["sec_fetch_mode"]),
        "sec-fetch-dest": (sec_fetch or {}).get("dest", ident["sec_fetch_dest"]),
        "sec-fetch-user": (sec_fetch or {}).get("user", ident["sec_fetch_user"]),
        "upgrade-insecure-requests": "1",
    }
    if referer:
        h["Referer"] = referer
    return h


def for_playwright(ident: dict | None = None, override_ua: bool = False) -> dict:
    """给 `browser.new_context(**...)` 的参数。

    默认 **不传 user_agent** —— 真浏览器就用它自己的 UA（v14 阶段 2 的第一条：
    删掉 fetch_rendered.py 里那行 `new_context(user_agent=UA)` 覆盖）。
    只有显式 override_ua=True 时才把身份里的 UA 顶上去，且此时 Sec-CH-UA 同源，
    不会出现"假 UA + 真浏览器"的矛盾。
    """
    ident = ident or IDENTITY
    ctx = {
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "viewport": {"width": 1440, "height": 900},
        "extra_http_headers": {
            "Accept-Language": ident["accept_language"],
            "sec-ch-ua": ident["sec_ch_ua"],
            "sec-ch-ua-mobile": ident["sec_ch_ua_mobile"],
            "sec-ch-ua-platform": ident["sec_ch_ua_platform"],
        },
    }
    if override_ua:
        ctx["user_agent"] = ident["ua"]
        ctx["extra_http_headers"]["sec-ch-ua"] = ident["sec_ch_ua"]
        ctx["extra_http_headers"]["sec-ch-ua-platform"] = ident["sec_ch_ua_platform"]
    return ctx


def card(ident: dict | None = None) -> dict:
    """身份卡：启动/验收时打印这个，人工核对四项版本一致。"""
    ident = ident or IDENTITY
    return {
        "brand": ident["brand"],
        "version(真浏览器/期望)": ident["version"],
        "impersonate(curl_cffi)": ident["impersonate"] or "(不冒充)",
        "ua_major(UA 里读出来的)": next(
            (seg.split("/")[1].split(".")[0] for seg in ident["ua"].split()
             if seg.startswith("Chrome/")), "?"),
        "ch_ua_major(Sec-CH-UA 里读出来的)": next(
            (tok.split('v="')[1].rstrip('"') for tok in ident["sec_ch_ua"].split(",")
             if "Chromium" in tok), "?"),
        "consistent": identities_consistent(ident) or "OK",
    }


def print_card(ident: dict | None = None, stream=None) -> dict:
    c = card(ident)
    (stream or sys.stdout).write(json.dumps(c, ensure_ascii=False, indent=2) + "\n")
    return c


def for_playwright_actual(browser_version, override_ua=True) -> dict:
    """按**真实浏览器版本**生成渲染上下文参数（T2 用）。

    与 `for_playwright()` 的区别：
      · `for_playwright()` 用的是模块默认身份（152，T1 的 impersonate 版本）
      · 本函数用 browser.version（本机 157）**重新生成一份身份**，UA 与 Sec-CH-UA 同时覆盖
        → 不会出现"真 Chrome 157 + 假 UA 152"那种自相矛盾
      · 不传 locale：让浏览器用系统语言（否则 navigator.languages 会与真机不一致，
        §4.1.1 第 ⑤ 项会判不过）
    """
    ident = build_identity(brand=DEFAULT_BRAND,
                           version=_major(browser_version),
                           impersonate=None)
    kw = for_playwright(ident, override_ua=override_ua)
    kw.pop("locale", None)          # 交给系统，避免 languages 变成单元素
    return kw


def playwright_identity(browser_version) -> dict:
    """渲染通道用的身份（不覆盖 UA 时用来核对版本）。"""
    return build_identity(brand=DEFAULT_BRAND, version=_major(browser_version),
                          impersonate=None)


# ---- 模块级默认身份（其他文件只 import 这几个）----
IDENTITY = build_identity()
UA = IDENTITY["ua"]


if __name__ == "__main__":
    print_card()