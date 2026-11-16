# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
离线修附件文件名（不改内容、不重新下载）。

背景：早期版本用链接文字（"附件："）当文件名，也没按真实扩展名判断，
于是落盘名出现 `附件：`、`1.新兽药注册目录` 这种没有扩展名的。
现在要做的只是：把记录里的 name/path 改成 URL 里的真实文件名，磁盘上跟着改名。

安全措施（顺序固定）：
    1. 先备份原始 jsonl 到 archive\\<job>.pre-fix-<时间戳>.jsonl
    2. 默认 --dry-run，只打印打算怎么做
    3. --apply 才动手：逐个 os.replace 改名（同卷原子），最后整体重写 jsonl（tmp + replace）
    4. 用 sha256 校验：改名前后内容哈希必须一致（我们只改名字，不动字节）
    5. 重算 content_hash（用的是规范化算法，与文件名/路径无关）

用法：
    python tests\\fix_attachment_names.py --job foodlaw_att1            # 预览
    python tests\\fix_attachment_names.py --job foodlaw_att1 --apply    # 真改
"""
import argparse
import re
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(_HOME / "crawlers"))
import crawler  # noqa: E402

AGENT = Path(str(_HOME))
RAW = AGENT / "data" / "raw"
ARCHIVE = AGENT / "archive"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="foodlaw_att1")
    ap.add_argument("--apply", action="store_true", help="真的改（默认只预览）")
    args = ap.parse_args()

    src = RAW / ("%s.jsonl" % args.job)
    if not src.exists():
        print("数据文件不存在：%s" % src)
        return 2

    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    print("=" * 74)
    print("离线修附件名：%s（%d 条记录）  模式=%s"
          % (src.name, len(rows), "APPLY" if args.apply else "DRY-RUN"))
    print("=" * 74)

    plan = []      # (row_idx, att_idx, old_path, new_path, old_name, new_name)
    for i, r in enumerate(rows):
        for j, a in enumerate(r.get("attachments") or []):
            if not isinstance(a, dict) or a.get("status") != "ok":
                continue
            old_path = a.get("path") or ""
            if not old_path:
                continue
            url = a.get("url") or ""
            url_ext = os.path.splitext(os.path.basename(url.split("?")[0]))[1].lower()
            old_name = os.path.basename(old_path)

            def real_ext(n):
                e = os.path.splitext(n)[1].lower()
                # 只有"像扩展名"的才算（点+字母数字，且短）；
                # 否则 "1. 依法设置的...申请书" 会被切成 stem="1"
                return e if (e and len(e) <= 6 and re.fullmatch(r"\.[a-z0-9]+", e)) else ""

            old_ext = real_ext(old_name)
            if url_ext and old_ext == url_ext:
                continue                      # 扩展名已经对了，保留人名（可读性更好）
            stem = old_name[:len(old_name) - len(old_ext)] if old_ext else old_name
            # "附件："这种没有信息量的名字，换用 URL 文件名
            if not re.sub(r"[附件:：\s]", "", stem):
                stem = os.path.splitext(os.path.basename(url.split("?")[0]))[0]
            new_name = crawler._safe_filename(stem, url, j + 1)
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            plan.append((i, j, old_path, new_path, old_name, new_name))

    print("需要改名：%d 个" % len(plan))
    for (i, j, op, np_, on, nn) in plan:
        print("  [%2d.%d] %-40s -> %s" % (i, j, on[:40], nn[:60]))

    if not plan:
        print("没有要改的，结束。")
        return 0
    if not args.apply:
        print("\n（预览模式，没有改动任何文件。确认无误后加 --apply）")
        return 0

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ARCHIVE / ("%s.pre-fix-%s.jsonl" % (args.job, stamp))
    shutil.copy2(src, backup)
    print("\n已备份原文件 → %s" % backup)

    ok_rename = 0
    bad_hash = 0
    for (i, j, op, np_, on, nn) in plan:
        if not os.path.exists(op):
            print("  !! 源文件不存在，跳过：%s" % op)
            continue
        if os.path.exists(np_):
            print("  !! 目标已存在，跳过：%s" % np_)
            continue
        h_before = sha256_of(op)
        os.replace(op, np_)
        h_after = sha256_of(np_)
        if h_before != h_after:
            bad_hash += 1
            print("  !! 改名后哈希不一致：%s" % np_)
            continue
        rec = rows[i]["attachments"][j]
        rec["path"] = np_
        rec["name"] = nn
        ok_rename += 1

    for r in rows:
        r["content_hash"] = crawler.content_hash_of(r)

    tmp = str(src) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, src)

    print("改名成功 %d / 计划 %d，哈希异常 %d" % (ok_rename, len(plan), bad_hash))
    print("jsonl 已原子重写，content_hash 已按规范化算法重算")
    return 0 if bad_hash == 0 else 1


if __name__ == "__main__":
    sys.exit(main())