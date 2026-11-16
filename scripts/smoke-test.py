# smoke-test.py -- prove the venv toolchain actually works end to end.
# Checks: import, HTTP fetch, HTML parse, DataFrame build, XLSX write, XLSX read back.
# ASCII-only output to avoid Windows console encoding traps.

import json
import os
import sys
import time

result = {"python": sys.version.split()[0], "exe": sys.executable, "steps": [], "ok": False}

def step(name, fn):
    t0 = time.time()
    try:
        info = fn()
        result["steps"].append({"step": name, "ok": True, "info": info,
                                "sec": round(time.time() - t0, 2)})
        return True
    except Exception as e:
        result["steps"].append({"step": name, "ok": False,
                                "error": "%s: %s" % (type(e).__name__, e),
                                "sec": round(time.time() - t0, 2)})
        return False

def s_import():
    import requests, httpx, bs4, lxml, pandas, openpyxl
    return {
        "requests": requests.__version__,
        "httpx": httpx.__version__,
        "beautifulsoup4": bs4.__version__,
        "lxml": lxml.__version__,
        "pandas": pandas.__version__,
        "openpyxl": openpyxl.__version__,
    }

def s_fetch():
    import requests
    r = requests.get("https://cn.bing.com/", timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    r.raise_for_status()
    return {"status": r.status_code, "bytes": len(r.content),
            "encoding_guess": r.encoding}

def s_parse():
    import requests
    from bs4 import BeautifulSoup
    r = requests.get("https://cn.bing.com/", timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    links = len(soup.find_all("a"))
    return {"title": title[:60], "anchor_count": links, "parser": "lxml"}

def s_httpx():
    import httpx
    with httpx.Client(timeout=15, follow_redirects=True) as c:
        r = c.get("https://cn.bing.com/")
        return {"status": r.status_code, "http_version": r.http_version}

def s_dataframe():
    import pandas as pd
    df = pd.DataFrame({
        "source_url": ["https://cn.bing.com/"] * 3,
        "title": ["alpha", "beta", "gamma"],
        "fetched_at": ["2026-11-09T22:00:00+08:00"] * 3,
        "http_status": [200, 200, 200],
        "content_hash": ["h1", "h2", "h3"],
        "run_id": ["smoke-001"] * 3,
    })
    outdir = r"D:\agent-work\out"
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "smoke-test.xlsx")
    df.to_excel(path, index=False, engine="openpyxl")
    return {"rows": len(df), "cols": list(df.columns), "file": path,
            "size_kb": round(os.path.getsize(path) / 1024, 1)}

def s_readback():
    import pandas as pd
    path = r"D:\agent-work\out\smoke-test.xlsx"
    df = pd.read_excel(path, engine="openpyxl")
    return {"rows": len(df), "cols": list(df.columns),
            "first_title": str(df.iloc[0]["title"]) if len(df) else ""}

ok = True
ok &= step("import all six packages", s_import)
ok &= step("HTTP GET via requests (cn.bing.com)", s_fetch)
ok &= step("HTML parse via BeautifulSoup + lxml", s_parse)
ok &= step("HTTP GET via httpx", s_httpx)
ok &= step("build DataFrame with lineage columns", s_dataframe)
ok &= step("read the xlsx back via pandas + openpyxl", s_readback)

result["ok"] = bool(ok)
print(json.dumps(result, ensure_ascii=True, indent=2))
sys.exit(0 if ok else 1)