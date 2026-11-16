# -*- coding: utf-8 -*-
"""吉林人才网 列表页侦察：抓 1 页，找卡片结构 / 字段 / 分页（1 请求）。"""
import re, json
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

FIX = Path(r"D:\agent-work\data\raw\fixtures")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
LIST = "https://www.jlrc.com.cn/ww/b/c/wwbc_result.html?jobName=&entName="
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
                  "Referer": "https://www.jlrc.com.cn/ww/index.html"})
r = s.get(LIST, timeout=25)
raw = r.content
(FIX / "probe_jlrc_list.html").write_bytes(raw)
html = raw.decode(r.apparent_encoding or "utf-8", "replace")
print("list: %s / %d B / enc=%s" % (r.status_code, len(raw), r.apparent_encoding))

soup = BeautifulSoup(html, "lxml")
print("title:", (soup.title.string or "").strip()[:60])

# 1) 详情链接（JobInfo.aspx）
det = [a["href"] for a in soup.find_all("a", href=True) if "JobInfo.aspx" in a["href"]]
print("\nJobInfo 链接数:", len(det))
for u in det[:5]:
    print("   ", u[:130])

# 2) 猜候选容器：包含多个 JobInfo 链接的最近公共父元素
if det:
    a0 = soup.find("a", href=lambda h: h and "JobInfo.aspx" in h)
    node = a0
    for _ in range(6):
        node = node.parent
        if node is None:
            break
        cnt = len(node.find_all("a", href=lambda h: h and "JobInfo.aspx" in h))
        if cnt >= 2:
            print("\n可能的卡片容器: <%s class=%s> 含 %d 个详情链接"
                  % (node.name, node.get("class"), cnt))
            print("容器文本预览:", node.get_text(" ", strip=True)[:220])
            break

# 3) 分页线索
pagi = [a.get_text(strip=True) for a in soup.find_all("a", href=True)
        if re.search(r"(page|Page|下一页|末页)", a["href"])]
print("\n分页链接样本:", pagi[:12])
m = re.findall(r"(共\s*\d+\s*页|\d+\s*/\s*\d+\s*页|totalPage\s*[:=]\s*\d+|pageCount\s*[:=]\s*\d+)", html)
print("页数线索:", m[:8])
m2 = re.findall(r"pageSize\s*[:=]\s*\d+|pageNo\s*[:=]\s*\d+|pageNum\s*[:=]\s*\d+", html)
print("分页参数线索:", m2[:10])

# 4) 是否有内联 JSON / XHR
print("\n含 .json / ajax / fetch(: ", bool(re.search(r"\.json|ajax|fetch\(", html)))
print("含 BASE_URL / api: ", re.findall(r"['\"]([^'\"]*(?:api|Api)[^'\"]*)['\"]", html)[:5])