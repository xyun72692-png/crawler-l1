# -*- coding: utf-8 -*-
"""
国学资源网 · AList 预览站清单/下载器
=====================================
目标：https://yulan.95959.com  （AList V3，robots.txt = User-agent: * / Allow: /）
机制：/api/fs/list 列目录（无需登录、无需密码）→ /api/fs/get 取签名直链 → GET 直链下载
      直链是签名 URL（天翼云 OSS），只在短时间有效 → 必须"取一个下一个"

目录树结构（实测）：
    /D00001-D09999/D0001-D0099/D0015 蒋大鸿《秘传水龙经》…【9学分】/<文件>

用法：
    # 1) 只扫清单（不下载），抽样 2 个桶 / 每桶最多 10 个资源目录
    python tools\\gxzy_alist_crawl.py --scan --limit-buckets 2 --max-res-dirs 10

    # 2) 全量扫清单（约 400 个桶，每请求间隔 3~5 秒，预计 30~40 分钟，可断点续）
    python tools\\gxzy_alist_crawl.py --scan

    # 3) 按编号下载（清单里查过再下，避免瞎下）
    python tools\\gxzy_alist_crawl.py --download --ids D0015,D2847 --out D:\\agent-work\\data\\gxzy

    # 4) 按关键词下载（匹配目录名里的标题）
    python tools\\gxzy_alist_crawl.py --download --keyword 中医 --max-total-mb 2048

    # 5) 重扫某个桶（清单有变动时）
    python tools\\gxzy_alist_crawl.py --scan --bucket D0001-D0099
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://yulan.95959.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
ROOT = Path(r"D:\agent-work")
OUTDIR = ROOT / "out" / "gxzy"          # 清单目录
STATE = OUTDIR / "_scan_state.json"     # 断点
INVENTORY = OUTDIR / "inventory.jsonl"  # 文件清单

SEGMENTS = ["/D00001-D09999", "/D10000-D19999", "/D20000-D29999", "/D30000-D39999"]
RES_RE = re.compile(r"^(D\d+)\s*(.*?)\s*【\s*(\d+)\s*学分\s*】\s*$")


class AList:
    def __init__(self, delay=(3.0, 5.0), timeout=40, retries=3):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": BASE + "/s/wvxsGu",
                               "Accept-Language": "zh-CN,zh;q=0.9"})
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.requests = 0

    def _post(self, path_api, payload):
        last = None
        for i in range(self.retries):
            try:
                time.sleep(random.uniform(*self.delay))
                r = self.s.post(BASE + path_api, json=payload, timeout=self.timeout)
                self.requests += 1
                j = r.json()
                if j.get("code") != 200:
                    raise RuntimeError(f"api code={j.get('code')} msg={j.get('message')}")
                return j.get("data") or {}
            except Exception as e:               # noqa: BLE001
                last = e
                time.sleep(2 + i * 2)
        raise RuntimeError(f"{path_api} 失败: {last!r}")

    def ls(self, path, per_page=200, page=1):
        return self._post("/api/fs/list",
                          {"path": path, "password": "", "page": page,
                           "per_page": per_page, "refresh": False})

    def get(self, path):
        return self._post("/api/fs/get", {"path": path, "password": ""})

    def raw_url(self, path):
        d = self.get(path)
        return d.get("raw_url") or "", d

    def download(self, path, dest, expect_size=None, chunk=1 << 20):
        url, meta = self.raw_url(path)
        if not url:
            raise RuntimeError("fs/get 未返回 raw_url")
        size = int(meta.get("size") or 0) or expect_size or 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        got = 0
        with self.s.get(url, stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "xml" in ctype or "json" in ctype:
                raise RuntimeError(f"直链返回错误: {r.text[:200]}")
            with open(tmp, "wb") as f:
                for buf in r.iter_content(chunk):
                    if buf:
                        f.write(buf)
                        got += len(buf)
        if size and got != size:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"大小不符 got={got} expect={size}")
        md5 = (meta.get("hash_info") or {}).get("md5") or ""
        if md5:
            import hashlib
            h = hashlib.md5()
            with open(tmp, "rb") as f:
                for buf in iter(lambda: f.read(1 << 20), b""):
                    h.update(buf)
            if h.hexdigest().upper() != md5.upper():
                tmp.unlink(missing_ok=True)
                raise RuntimeError("MD5 校验失败")
        os.replace(tmp, dest)
        return got, md5


def parse_res_dir(name):
    m = RES_RE.match(name)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m2 = re.match(r"^(D\d+)\s*(.*)$", name)
    if m2:
        return m2.group(1), m2.group(2), None
    return None, name, None


def safe_name(s, n=120):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s).strip(" .")
    return (s[:n] or "unnamed")


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text("utf-8"))
    return {"done_buckets": [], "files_done": 0}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), "utf-8")


def do_scan(al, args):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    st = load_state()
    done = set(st["done_buckets"])
    fout = open(INVENTORY, "a", encoding="utf-8")
    buckets = []
    if args.bucket:
        buckets = [args.bucket]
    else:
        for seg in SEGMENTS:
            d = al.ls(seg, per_page=200)
            for it in d.get("content") or []:
                if it.get("is_dir"):
                    buckets.append((seg + "/" + it["name"]).split("/", 1)[1])
        print(f"[scan] 桶目录共 {len(buckets)} 个")
        buckets = ["/" + b for b in buckets]

    if args.limit_buckets:
        buckets = buckets[: args.limit_buckets]

    n_file = n_res = 0
    total_bytes = 0
    for bucket in buckets:
        key = bucket
        if key in done and not args.bucket:
            print(f"[skip] {bucket}")
            continue
        try:
            d = al.ls(bucket, per_page=200)
        except Exception as e:                    # noqa: BLE001
            print(f"[err] {bucket}: {e}")
            continue
        res_dirs = [it for it in d.get("content") or [] if it.get("is_dir")]
        if args.max_res_dirs:
            res_dirs = res_dirs[: args.max_res_dirs]
        for rd in res_dirs:
            rpath = bucket + "/" + rd["name"]
            rid, title, credits = parse_res_dir(rd["name"])
            n_res += 1
            try:
                d2 = al.ls(rpath, per_page=200)
            except Exception as e:               # noqa: BLE001
                print(f"[err] {rpath}: {e}")
                continue
            for f in d2.get("content") or []:
                if f.get("is_dir"):
                    continue
                rec = {
                    "res_id": rid, "title": title, "credits": credits,
                    "res_dir": rd["name"], "path": rpath + "/" + f["name"],
                    "name": f["name"], "size": f.get("size") or 0,
                    "md5": ((f.get("hash_info") or {}) or {}).get("md5") or "",
                    "modified": f.get("modified") or "",
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_file += 1
                total_bytes += rec["size"]
                st["files_done"] += 1
            fout.flush()
        done.add(key)
        st["done_buckets"] = sorted(done)
        save_state(st)
        print(f"[ok] {bucket}  累计资源目录={n_res} 文件={n_file} "
              f"字节={total_bytes / (1 << 30):.2f}GB 请求={al.requests}")
    fout.close()
    print(f"\n[scan 完成] 资源目录 {n_res} / 文件 {n_file} / "
          f"合计 {total_bytes / (1 << 30):.2f} GB / 请求 {al.requests}")
    print(f"清单：{INVENTORY}")


def read_inventory():
    if not INVENTORY.exists():
        sys.exit(f"清单不存在，先跑 --scan：{INVENTORY}")
    recs = []
    for line in INVENTORY.read_text("utf-8").split("\n"):
        line = line.strip()
        if line:
            recs.append(json.loads(line))
    return recs


def do_download(al, args):
    recs = read_inventory()
    ids = {i.strip().upper() for i in (args.ids or "").split(",") if i.strip()}
    picked = []
    for r in recs:
        if ids and (r.get("res_id") or "").upper() not in ids:
            continue
        if args.keyword and args.keyword not in (r.get("res_dir") or ""):
            continue
        if args.max_size_mb and r["size"] > args.max_size_mb * (1 << 20):
            continue
        picked.append(r)

    if not picked:
        sys.exit("没有命中任何文件：检查 --ids / --keyword / 清单是否为空")

    out = Path(args.out) if args.out else (ROOT / "data" / "gxzy")
    budget = (args.max_total_mb or 0) * (1 << 20)
    got_total = 0
    ok = fail = 0
    for r in picked:
        if budget and got_total + r["size"] > budget:
            print(f"[stop] 已达总量上限 {args.max_total_mb} MB")
            break
        dest = out / safe_name(r.get("res_dir") or "unknown") / safe_name(r["name"], 150)
        if dest.exists() and dest.stat().st_size == r["size"]:
            print(f"[skip] 已存在 {dest}")
            got_total += r["size"]
            continue
        try:
            n, _ = al.download(r["path"], dest, r["size"])
            ok += 1
            got_total += n
            print(f"[ok] {n / (1 << 20):.1f}MB  {dest}")
        except Exception as e:                    # noqa: BLE001
            fail += 1
            print(f"[fail] {r['path']}: {e}")
    print(f"\n[download 完成] 成功 {ok} / 失败 {fail} / 共 {got_total / (1 << 30):.2f} GB")
    print(f"落盘：{out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只扫清单，不下载")
    ap.add_argument("--download", action="store_true", help="按清单下载")
    ap.add_argument("--bucket", help='只扫某个桶，如 D0001-D0099')
    ap.add_argument("--limit-buckets", type=int, default=0)
    ap.add_argument("--max-res-dirs", type=int, default=0, help="每个桶最多扫几个资源目录（抽样用）")
    ap.add_argument("--ids", help="按资源编号下载，逗号分隔，如 D0015,D2847")
    ap.add_argument("--keyword", help="按目录名关键词下载")
    ap.add_argument("--max-size-mb", type=int, default=0, help="跳过超过该大小的单文件")
    ap.add_argument("--max-total-mb", type=int, default=0, help="本轮下载总量上限")
    ap.add_argument("--out", help="下载落盘目录")
    ap.add_argument("--delay", default="3,5", help="请求间隔秒，如 3,5")
    args = ap.parse_args()

    if not args.scan and not args.download:
        ap.print_help()
        sys.exit(0)

    dmin, dmax = [float(x) for x in args.delay.split(",")]
    al = AList(delay=(dmin, dmax))
    if args.scan:
        do_scan(al, args)
    if args.download:
        do_download(al, args)


if __name__ == "__main__":
    main()