# -*- coding: utf-8 -*-
"""Rule 0 离线测试（T-R0-1 ~ T-R0-9）。0 请求，除最后一条会起一个 rr=2 的子进程。

跑法：python tests\\test_rule0.py
"""
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
AGENT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT / "crawlers"))

import rule0  # noqa: E402

# --- CI 编码护栏（v14.13.20）------------------------------------------------
# 为什么需要：GitHub 的 windows runner 默认 locale 是 cp1252，子进程（crawler.py）
# 往管道里打中文会抛 UnicodeEncodeError；而本机是中文 Windows（cp936）能编码中文，
# 所以这个坑只在 CI 暴露。v14.13.19 的 test_crawler 就栽在这一点上。
# 这里统一给「本进程 + 它启动的子进程」钉死 UTF-8。
import os as _os_enc
_os_enc.environ.setdefault("PYTHONIOENCODING", "utf-8")
_os_enc.environ.setdefault("PYTHONUTF8", "1")
# ---------------------------------------------------------------------------


PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %-56s %s" % ("PASS" if cond else "FAIL", name, detail))


def main():
    # ---------------- T-R0-1 三态解析 ----------------
    check("T-R0-1 缺省 = unknown", rule0.terms_state({}) == "unknown")
    check("T-R0-1 非法值 → unknown", rule0.terms_state({"terms_status": "已确认"}) == "unknown")
    check("T-R0-1 大小写/空格容错",
          rule0.terms_state({"terms_status": "  ALLOWED "}) == "allowed")

    # ---------------- T-R0-2/3/4 terms_gate ----------------
    g = rule0.terms_gate({})
    check("T-R0-2 unknown → 不抓 + blocked_terms_pending",
          (not g["ok"]) and g["reason"] == "blocked_terms_pending", g["reason"])
    g = rule0.terms_gate({"terms_status": "blocked"})
    check("T-R0-3 blocked → blocked_terms",
          (not g["ok"]) and g["reason"] == "blocked_terms", g["reason"])
    g = rule0.terms_gate({"terms_status": "allowed"})
    check("T-R0-4 allowed → 放行", g["ok"] and g["reason"] == "", str(g["ok"]))
    g = rule0.terms_gate({"terms_status": "allowed"}, cli_terms="blocked")
    check("T-R0-4 CLI 覆盖优先（allowed→blocked）",
          (not g["ok"]) and g["reason"] == "blocked_terms", g["reason"])
    g = rule0.terms_gate({}, cli_terms="乱写")
    check("T-R0-4 CLI 非法值 → bad_terms_status",
          (not g["ok"]) and g["reason"] == "bad_terms_status", g["reason"])

    # ---------------- T-R0-5 授权例外的三道闸 ----------------
    auth_cfg = {"platform": "jrzp",
                "render_authorized": {"by": "user", "at": "2026-11-14", "max_pages": 20}}
    o = rule0.build_override({}, want_js=False)
    check("T-R0-5 没开 --allow-robots-js → 不启用", not o["enabled"], o["why"])
    o = rule0.build_override({"platform": "jrzp"}, want_js=True)
    check("T-R0-5 无 render_authorized → 不启用",
          (not o["enabled"]) and "点对点" in o["why"], o["why"][:40])
    o = rule0.build_override({"platform": "qscms74", "render_authorized":
                              {"by": "user", "at": "2026-11-14"}}, want_js=True)
    check("T-R0-5 平台不在授权名单 → 不启用",
          (not o["enabled"]) and "平台" in o["why"], o["why"][:40])
    o = rule0.build_override(auth_cfg, want_js=True)
    check("T-R0-5 三闸齐 → 启用（scope=js/css, max_pages=20）",
          o["enabled"] and o["scope"] == "js/css" and o["max_pages"] == 20
          and o["authorized_by"] == "user", str({k: o[k] for k in ("enabled", "scope", "max_pages")}))

    # ---------------- T-R0-6 报告七字段 ----------------
    f = rule0.override_report_fields(o)
    check("T-R0-6 报告四字段齐全",
          set(f) == {"robots_override", "override_scope", "authorized_by", "authorized_at"},
          str(sorted(f)))
    f0 = rule0.override_report_fields({"enabled": False})
    check("T-R0-6 未启用时 robots_override=False 且 scope 空",
          f0["robots_override"] is False and f0["override_scope"] == "")

    # ---------------- T-R0-7 决策块格式 ----------------
    blk = rule0.decision_block("example.tld", "robots 禁止", "Disallow: /*.js*（第 12 行）",
                               "本次未发出任何请求")
    need = ["[!] 触发 Rule 0", "站点", "信号", "证据", "已做", "A. 放弃", "B. 降到", "C. 明确授权"]
    miss = [n for n in need if n not in blk]
    check("T-R0-7 决策块含固定字段与三个选项", not miss, "缺：%s" % miss if miss else "8 项齐全")

    # ---------------- T-R0-8 CLI：blocked 时 rc=2 且 0 请求 ----------------
    out = subprocess.run([sys.executable, str(AGENT / "crawlers" / "crawler.py"),
                          "--site", "quotes", "--pages", "1",
                          "--terms-status", "blocked", "--job", "r0_cli_probe"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         cwd=str(AGENT), timeout=120)
    ok8 = (out.returncode == 2) and ("触发 Rule 0" in (out.stdout + out.stderr))
    check("T-R0-8 --terms-status blocked → rc=2 且打印决策块", ok8,
          "rc=%s" % out.returncode)

    # ---------------- T-R0-9 所有站点都已标 terms_status ----------------
    sites = [p for p in (AGENT / "crawlers" / "sites").glob("*.py") if not p.name.startswith("_")]
    missing = [p.name for p in sites if '"terms_status"' not in p.read_text(encoding="utf-8")]
    check("T-R0-9 每个站点模块都有 terms_status（防漏标）", not missing,
          "缺：%s" % missing if missing else "%d 个站点全部已标" % len(sites))

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())