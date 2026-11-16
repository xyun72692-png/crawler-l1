import requests,re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
u="https://www.yqrc.com/job"
r=requests.get(u,headers=H,timeout=20,verify=False); r.encoding=r.apparent_encoding
html=r.text
open(r"D:\agent-work\data\raw\_probe_yqrc_job.html","w",encoding="utf-8").write(html)
print("status",r.status_code,"len",len(html))
soup=BeautifulSoup(html,"lxml")
# 找职位详情链接
links=[a for a in soup.find_all("a",href=True) if "jobinfo_" in a["href"]]
print("jobinfo links:",len(links))
for a in links[:8]:
    print("  ",a.get_text(" ",strip=True)[:60],"|",urljoin(u,a["href"]))
# 分页
print("--- 分页/筛选类链接 ---")
for a in soup.find_all("a",href=True):
    h=a["href"]; t=a.get_text(strip=True)
    if any(k in h for k in ["page","edu","salary","welfare","area","region"]) and len(t)<12:
        print(f"  {t:12s} {h[:80]}")
