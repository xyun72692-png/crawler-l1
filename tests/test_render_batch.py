# -*- coding: utf-8 -*-
"""render_batch 离线测试（T-RB-1 ~ T-RB-7）。本地 mock_site，0 外网。

跑法：python tests\\test_render_batch.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# --- CI 编码护栏（v14.13.20）------------------------------------------------
# 为什么需要：GitHub 的 windows runner 默认 locale 是 cp1252，子进程（crawler.py）
# 往管道里打中文会抛 UnicodeEncodeError；而本机是中文 Windows（cp936）能编码中文，
# 所以这个坑只在 CI 暴露。v14.13.19 的 test_crawler 就栽在这一点上。
# 这里统一给「本进程 + 它启动的子进程」钉死 UTF-8。
import os as _os_enc
_os_enc.environ.setdefault("PYTHONIOENCODING", "utf-8")
_os_enc.environ.setdefault("PYTHONUTF8", "1")
# ---------------------------------------------------------------------------


sys.dont_write_bytecode = True
AGENT = Path(__file__).resolve().parent.parent
PY = sys.executable

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %-52s %s" % ("PASS" if cond else "FAIL", name, detail))


def start_mock(robots="none"):
    cmd = [PY, str(AGENT / "tests" / "mock_site.py"), "--port", "0"]
    if robots != "none":
        cmd += ["--robots", robots]
    p = subprocess.Popen(cmd,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", cwd=str(AGENT))
    port = None
    for _ in range(200):
        line = p.stdout.readline()
        if not line:
            break
        m = re.search(r"PORT=(\d+)", line)
        if m:
            port = m.group(1)
            break
    if not port:
        p.kill()
        raise RuntimeError("mock 没起来")
    return p, port


def run_render(port, tmp, job, pages=2, url_suffix=None, extra=None, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    env.update({"MOCK_PORT": port,
                "CRAWLER_OUT_DIR": str(tmp / "data"),
                "CRAWLER_LOG_DIR": str(tmp / "log"),
                "CRAWLER_STATE_DIR": str(tmp / "state"),
                "CRAWLER_REPORT_DIR": str(tmp / "report"),
                "CRAWLER_TEST_TMP": str(tmp),
                "CRAWLER_GATE_FORCE": "1",
                "PYTHONIOENCODING": "utf-8"})
    cmd = [PY, str(AGENT / "tools" / "render_batch.py"), "--site", "mockrender",
           "--pages", str(pages), "--job", job]
    if extra:
        cmd += extra
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=str(AGENT), env=env, timeout=300)
    return out


def last_report(tmp, job):
    files = sorted((tmp / "report").glob("report-%s-*.json" % job))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else {}


def main():
    srv, port = start_mock()
    try:
        with tempfile.TemporaryDirectory(prefix="rb_") as td:
            tmp = Path(td)

            # ---------------- T-RB-1 两页渲染 + 抽取 ----------------
            out = run_render(port, tmp, "rb1", pages=2, extra=["--allow-robots-js"])
            ok1 = out.returncode == 0
            check("T-RB-1 正常跑完（rc=0）", ok1, "rc=%s %s" % (out.returncode, out.stderr[-120:]))

            rows_p = tmp / "data" / "rb1.jsonl"
            rows = [json.loads(l) for l in rows_p.read_text(encoding="utf-8").splitlines() if l.strip()] \
                if rows_p.exists() else []
            check("T-RB-1 记录数 6（2 页 × 3 条）", len(rows) == 6, "rows=%d" % len(rows))
            check("T-RB-1 每条都带 detail_url + 标题",
                  all(r.get("detail_url") and r.get("title") for r in rows))
            check("T-RB-1 记录了渲染血缘（_render.job/page）",
                  all((r.get("_render") or {}).get("job") == "rb1" for r in rows))

            # ---------------- T-RB-2 报告口径 ----------------
            rep = last_report(tmp, "rb1")
            st = rep.get("stats") or {}
            check("T-RB-2 导航计数 = 2（子资源不计入）", st.get("navigations") == 2,
                  "nav=%s" % st.get("navigations"))
            check("T-RB-2 子资源有统计且 >0", (st.get("subresources") or 0) > 0,
                  "sub=%s 均 %s/页" % (st.get("subresources"), st.get("subresources_per_page")))
            check("T-RB-2 均子资源 ≤ 80", (st.get("subresources_per_page") or 0) <= 80,
                  "均 %s" % st.get("subresources_per_page"))
            check("T-RB-2 报告里有 terms_status=allowed", rep.get("terms_status") == "allowed",
                  str(rep.get("terms_status")))
            check("T-RB-2 授权例外留痕（robots_override/scope/by）",
                  rep.get("robots_override") is True and rep.get("override_scope") == "js/css"
                  and rep.get("authorized_by") == "user",
                  "%s/%s/%s" % (rep.get("robots_override"), rep.get("override_scope"),
                                rep.get("authorized_by")))
            check("T-RB-2 status=success", rep.get("status") == "success", str(rep.get("status")))

            # ---------------- T-RB-3 渲染后的 HTML 落盘 ----------------
            rd = tmp / "data" / "_rendered" / "rb1"
            htmls = sorted(rd.glob("p*.html")) if rd.exists() else []
            check("T-RB-3 每页 HTML 落盘（p1/p2）", len(htmls) == 2,
                  "files=%d" % len(htmls))
            if htmls:
                body = htmls[0].read_text(encoding="utf-8")
                check("T-RB-3 落盘的是渲染后 DOM（含 a.job）", "class=\"job\"" in body)

            # ---------------- T-RB-4 未授权时例外不生效 ----------------
            out4 = run_render(port, tmp, "rb4", pages=1)
            rep4 = last_report(tmp, "rb4")
            check("T-RB-4 没给 --allow-robots-js → robots_override=False",
                  rep4.get("robots_override") is False, str(rep4.get("robots_override")))
            check("T-RB-4 未授权也不影响正常渲染", out4.returncode == 0, "rc=%s" % out4.returncode)

            # ---------------- T-RB-5 单页子资源超限 → 记 anomaly 并停 ----------------
            out5 = run_render(port, tmp, "rb5", pages=1, extra=["--keep-resources"])
            # 用同一页对比：默认拦 image/font/media vs --keep-resources 全加载
            s1 = (last_report(tmp, "rb1").get("stats") or {})
            s5 = (last_report(tmp, "rb5").get("stats") or {})
            check("T-RB-5 默认拦 image/font/media（blocked>0）",
                  (s1.get("subresources_blocked") or 0) > 0
                  and s1.get("resource_blocking") is True,
                  "blocked=%s" % s1.get("subresources_blocked"))
            check("T-RB-5 --keep-resources 时不拦（blocked=0）",
                  (s5.get("subresources_blocked") or 0) == 0
                  and s5.get("resource_blocking") is False,
                  "blocked=%s" % s5.get("subresources_blocked"))

            # ---------------- T-RB-6 Rule 0：terms_status=blocked ----
            env = dict(os.environ, MOCK_PORT=port, CRAWLER_OUT_DIR=str(tmp / "data"),
                       CRAWLER_LOG_DIR=str(tmp / "log"), CRAWLER_REPORT_DIR=str(tmp / "report"),
                       CRAWLER_STATE_DIR=str(tmp / "state"), PYTHONIOENCODING="utf-8")
            out6 = subprocess.run(
                [PY, str(AGENT / "tools" / "render_batch.py"), "--site", "mockrender",
                 "--pages", "1", "--job", "rb6", "--terms-status", "blocked"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(AGENT), env=env, timeout=120)
            check("T-RB-6 terms_status=blocked → rc=2 且不打浏览器",
                  out6.returncode == 2 and "触发 Rule 0" in (out6.stdout + out6.stderr),
                  "rc=%s" % out6.returncode)

            # ---------------- T-RB-8 robots 200+HTML → fail-closed ----------------
            srv8, port8 = start_mock("html")
            try:
                out8 = run_render(port8, tmp, "rb8", pages=2, extra=["--allow-robots-js"],
                                  env_extra={"MOCK_RESPECT_ROBOTS": "1"})
                rep8 = last_report(tmp, "rb8")
                reason8 = rep8.get("reason") or ""
                rows8 = tmp / "data" / "rb8.jsonl"
                check("T-RB-8 robots 200+HTML → reason=robots_denied",
                      out8.returncode == 3 and reason8.startswith("robots_denied"),
                      "rc=%s reason=%s" % (out8.returncode, reason8))
                check("T-RB-8 记录数 0", (not rows8.exists()) or rows8.stat().st_size == 0)
            finally:
                srv8.terminate()
                try:
                    srv8.wait(timeout=5)
                except Exception:
                    srv8.kill()

            # ---------------- T-RB-7 代码零域名 ----------------
            src = (AGENT / "tools" / "render_batch.py").read_text(encoding="utf-8")
            dom = re.findall(r"[\w-]+\.(?:com|cn|net)\b", src)
            check("T-RB-7 render_batch.py 里没有具体域名", not dom, str(dom[:3]))

    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())