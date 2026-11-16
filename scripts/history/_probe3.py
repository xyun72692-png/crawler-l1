import requests,re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
r=requests.get("https://www.yqrc.com/",headers=H,timeout=15,verify=False)
r.encoding=r.apparent_encoding
soup=BeautifulSoup(r.text,"lxml")
seen=set()
print("--- 招聘相关链接 ---")
for a in soup.find_all("a",href=True):
    t=a.get_text(strip=True); h=urljoin(r.url,a["href"])
    if any(k in t for k in ["招聘","职位","找工作","求职","人才"]) and h not in seen:
        seen.add(h); print(f"{t[:22]:24s} {h}")
