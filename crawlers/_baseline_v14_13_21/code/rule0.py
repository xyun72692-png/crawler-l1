# -*- coding: utf-8 -*-
"""Rule 0：robots / 条款 / 验证码 → 停、记、报（v14 阶段 2 前置）。

**这是全项目优先级最高的一条规则**：它高于 v14 的一切伪装与渲染优化。
通道的存在不等于可以自动用；被拦时**不许升级通道、不许重试到成功**。

本模块只做四件事：
  ① terms_status 三态判定（unknown / allowed / blocked）—— fail-closed
  ② 统一决策块文本（站点 / 信号 / 证据 / 已做 / 三个选项）
  ③ jrzp 授权例外路径（点对点、写死边界、每次留痕）
  ④ 给报告提供 `robots_override` / `override_scope` / `authorized_by` / `authorized_at` 四个字段

**不做**：robots 文本解析（那在 robots_rules.py，v11 已有）、验证码识别（红线）。
"""

from datetime import date

TERMS_UNKNOWN = "unknown"
TERMS_ALLOWED = "allowed"
TERMS_BLOCKED = "blocked"
TERMS_STATES = (TERMS_UNKNOWN, TERMS_ALLOWED, TERMS_BLOCKED)

# jrzp 授权的边界（写死，不许扩大）
OVERRIDE_SCOPE = "js/css"
OVERRIDE_MAX_PAGES = 20
OVERRIDE_SITES_ALLOWED = ("jrzp",)      # 按平台标记，不按域名 —— 仍然一站点对点


# --------------------------------------------------------------------------- #
# ① 条款三态
# --------------------------------------------------------------------------- #
def terms_state(cfg) -> str:
    """站点 CONFIG 里的 terms_status。缺省 unknown（fail-closed：没确认过就不抓）。"""
    v = (cfg or {}).get("terms_status")
    if v is None:
        return TERMS_UNKNOWN
    v = str(v).strip().lower()
    return v if v in TERMS_STATES else TERMS_UNKNOWN


def terms_gate(cfg, cli_terms=None) -> dict:
    """判定本次能不能抓。返回 {ok, status, reason, signal, evidence}。

    cli_terms：命令行 `--terms-status allowed|blocked` 临时覆盖（留痕用）。
    """
    state = (cli_terms or "").strip().lower() if cli_terms else ""
    if state and state not in TERMS_STATES:
        return {"ok": False, "status": "failed", "reason": "bad_terms_status",
                "signal": "条款状态非法", "evidence": "取值 %r 不在 %s 内" % (cli_terms, list(TERMS_STATES))}
    if state:
        src = "--terms-status 显式指定"
    else:
        state = terms_state(cfg)
        src = "站点 CONFIG.terms_status"

    if state == TERMS_ALLOWED:
        return {"ok": True, "status": "ok", "reason": "", "signal": "", "evidence": ""}
    if state == TERMS_BLOCKED:
        return {"ok": False, "status": "failed", "reason": "blocked_terms",
                "signal": "站点条款禁止自动化抓取",
                "evidence": "%s = blocked（人工确认过）" % src}
    # unknown
    return {"ok": False, "status": "failed", "reason": "blocked_terms_pending",
            "signal": "站点条款未确认（默认不抓）",
            "evidence": "%s = unknown；确认不禁止后标 allowed 再跑" % src}


# --------------------------------------------------------------------------- #
# ③ jrzp 授权例外
# --------------------------------------------------------------------------- #
def render_authorized(cfg) -> dict | None:
    """站点 CONFIG 里的点对点授权块。没有就返回 None。"""
    ra = (cfg or {}).get("render_authorized")
    if not isinstance(ra, dict):
        return None
    if not ra.get("by") or not ra.get("at"):
        return None
    return ra


def build_override(cfg, want_js: bool) -> dict:
    """是否启用 robots 例外（为渲染列表而加载 JS/CSS）。

    三个条件全满足才启用，缺一不启用（fail-closed）：
      ① 命令行显式 `--allow-robots-js`
      ② 站点 CONFIG 里有 render_authorized（点对点授权，含 by/at）
      ③ 站点平台标记在 OVERRIDE_SITES_ALLOWED 里（当前只有 jrzp）
    """
    off = {"enabled": False, "scope": "", "authorized_by": "", "authorized_at": "",
           "max_pages": 0, "why": ""}
    if not want_js:
        return dict(off, why="未显式启用")
    ra = render_authorized(cfg)
    if not ra:
        return dict(off, why="站点没有 render_authorized（授权是点对点的，不能套用）")
    plat = str((cfg or {}).get("platform") or "").lower()
    if plat not in OVERRIDE_SITES_ALLOWED:
        return dict(off, why="平台 %r 不在授权名单 %s 内" % (plat, list(OVERRIDE_SITES_ALLOWED)))
    return {"enabled": True,
            "scope": OVERRIDE_SCOPE,
            "authorized_by": ra.get("by", ""),
            "authorized_at": ra.get("at", ""),
            "max_pages": int(ra.get("max_pages") or OVERRIDE_MAX_PAGES),
            "why": "用户点对点授权：为渲染列表加载 JS/CSS"}


def override_report_fields(ov: dict) -> dict:
    """给报告的四个字段（不论启用与否都写，便于审计）。"""
    return {
        "robots_override": bool((ov or {}).get("enabled")),
        "override_scope": (ov or {}).get("scope", ""),
        "authorized_by": (ov or {}).get("authorized_by", ""),
        "authorized_at": (ov or {}).get("authorized_at", ""),
    }


# --------------------------------------------------------------------------- #
# ② 统一决策块
# --------------------------------------------------------------------------- #
OPTIONS = ("A. 放弃这个站（推荐）",
           "B. 降到更低强度通道（渲染 → 人工保存 HTML 离线解析）",
           "C. 明确授权覆盖（--ignore-robots / --allow-robots-js，限本次、写进 overrides）")


def decision_block(host, signal, evidence, done, options=OPTIONS, today=None) -> str:
    """固定格式，别改字段顺序 —— 用户是照这个块做决定的。"""
    d = today or date.today().isoformat()
    lines = ["[!] 触发 Rule 0 —— 已停止，等你决定",
             "    站点   %s" % (host or "(未知)"),
             "    信号   %s" % signal,
             "    证据   %s" % (evidence or "-"),
             "    已做   %s" % (done or "本次未发出任何后续请求"),
             "    日期   %s" % d,
             "    → 可选（按你选的那个执行，都会留痕）："]
    lines += ["       %s" % o for o in options]
    return "\n".join(lines)