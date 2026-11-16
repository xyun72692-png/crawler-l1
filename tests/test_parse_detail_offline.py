# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
阶段1 · 离线解析回归：新 parse_detail 必须和旧 parse_detail 输出一致。

做法（不发一次网络请求）：
    1. 从阶段0 基线里把【旧版】sites/foodlaw.py 按文件路径加载进来
    2. 加载【新版】sites/foodlaw.py
    3. 喂同一份真实详情页 HTML（samples/_foodlaw_detail1.html）
    4. 逐个字段比对：旧版返回的 8 个字段必须一模一样；
       新版允许【多】返回 valid_status / status_confirmed（这是阶段1 的设计：
       状态映射只依赖图标文件名，属于纯解析，所以放在 parse_detail 里）

跑法：python tests\\test_parse_detail_offline.py
退出码：0 一致 / 1 有差异
"""
import importlib.util
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 不要生成 .pyc！基线目录是只读证据，importlib 会在同目录建 __pycache__，
# 等于往冻结的基线里塞垃圾（2026-11-10 真的发生过，靠 verify 的多余文件检查才发现）。
sys.dont_write_bytecode = True

AGENT = Path(str(_HOME))
OLD_PATH = AGENT / "crawlers/_baseline_v1/code/sites/foodlaw.py"
NEW_DIR = AGENT / "crawlers"
SAMPLE = AGENT / "crawlers/_baseline_v1/samples/_foodlaw_detail1.html"

OLD_KEYS = ["title", "publish_date", "status_img", "effective_date",
            "abolish_date", "issuer", "doc_no", "attr"]
NEW_EXTRA = ["valid_status", "status_confirmed", "attachments"]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    print("=" * 70)
    print("阶段1 · 离线解析回归（不发网络请求）")
    print("=" * 70)

    for p in (OLD_PATH, SAMPLE):
        if not p.exists():
            print("缺少文件：%s" % p)
            return 2

    if str(NEW_DIR) not in sys.path:
        sys.path.insert(0, str(NEW_DIR))

    old = load_module(OLD_PATH, "foodlaw_old")
    new = load_module(NEW_DIR / "sites/foodlaw.py", "foodlaw_new")
    html = SAMPLE.read_text(encoding="utf-8", errors="replace")

    d_old = old.parse_detail(html)
    d_new = new.parse_detail(html)

    print("\n样本：%s（%d 字节）" % (SAMPLE.name, len(html)))
    print("\n%-18s %-30s %-30s %s" % ("字段", "旧版", "新版", "结论"))
    print("-" * 78)

    bad = 0
    for k in OLD_KEYS:
        a = d_old.get(k)
        b = d_new.get(k)
        same = (a == b)
        if not same:
            bad += 1
        print("%-18s %-30s %-30s %s"
              % (k, json.dumps(a, ensure_ascii=False)[:29],
                 json.dumps(b, ensure_ascii=False)[:29], "一致" if same else "!! 不同"))

    print("-" * 78)
    for k in NEW_EXTRA:
        present = k in d_new
        print("%-18s %-30s %-30s %s"
              % (k, "(旧版没有)", json.dumps(d_new.get(k), ensure_ascii=False)[:29],
                 "新增" if present else "!! 缺失"))
        if not present:
            bad += 1

    extra = set(d_new) - set(OLD_KEYS) - set(NEW_EXTRA)
    if extra:
        print("\n!! 新版多出了计划外的字段：%s" % sorted(extra))
        bad += 1

    print("\n" + "=" * 70)
    if bad == 0:
        print("结论：一致（8 个字段逐字相同，新增 %d 个派生字段）" % len(NEW_EXTRA))
        return 0
    print("结论：%d 处不一致，不能删旧逻辑" % bad)
    return 1


if __name__ == "__main__":
    sys.exit(main())