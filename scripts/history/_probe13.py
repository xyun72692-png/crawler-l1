import requests,re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
r=requests.get("https://www.wzrc.net/",headers=H,timeout=20,verify=False); r.encoding=r.apparent_encoding
soup=BeautifulSoup(r.text,"lxml")
print("--- 职位/招聘频道 ---")
seen=set()
for a in soup.find_all("a",href=True):
    t=a.get_text(strip=True); h=urljoin(r.url,a["href"])
    if any(k in t for k in ["职位","招聘","找工作","岗位"]) and h not in seen and len(t)<14:
        seen.add(h); print(f"  {t:14s} {h}")
