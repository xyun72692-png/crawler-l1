import requests,re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
for u in ["https://yq.wzrc.net/robots.txt","https://yq.wzrc.net/"]:
    r=requests.get(u,headers=H,timeout=25,verify=False); r.encoding=r.apparent_encoding
    print("===",u,r.status_code,len(r.text))
    if "robots" in u: print(r.text[:400]); continue
    open(r"D:\agent-work\data\raw\_probe_yqwzrc.html","w",encoding="utf-8").write(r.text)
    soup=BeautifulSoup(r.text,"lxml")
    seen=set()
    for a in soup.find_all("a",href=True):
        t=a.get_text(strip=True); hh=urljoin(r.url,a["href"])
        if any(k in t for k in ["职位","找工作","招聘"]) and hh not in seen and len(t)<12:
            seen.add(hh); print("  ",t,"→",hh[:90])
