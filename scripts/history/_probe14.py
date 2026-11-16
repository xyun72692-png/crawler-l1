import requests,re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
u="https://www.wzrc.net/index.php?m=&c=jobs&a=jobs_list"
r=requests.get(u,headers=H,timeout=25,verify=False); r.encoding=r.apparent_encoding
print("status",r.status_code,"len",len(r.text))
open(r"D:\agent-work\data\raw\_probe_wzrc.html","w",encoding="utf-8").write(r.text)
soup=BeautifulSoup(r.text,"lxml")
# 找职位链接
links=[a for a in soup.find_all("a",href=True) if "jobs_show" in a["href"]]
print("jobs_show links:",len(links))
for a in links[:6]:
    print("  ",a.get_text(" ",strip=True)[:40],"|",a["href"][:80])
# 地区/筛选
print("--- 筛选参数 ---")
seen=set()
for a in soup.find_all("a",href=True):
    h=a["href"]; t=a.get_text(strip=True)
    if any(k in h for k in ["city","area","jobs_welfare","salary","edu","page","jobs_list"]) and len(t)<14:
        key=(t,h[:70])
        if key not in seen:
            seen.add(key); print(f"  {t:12s} {h[:70]}")
