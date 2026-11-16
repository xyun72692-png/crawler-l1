import requests,re
from bs4 import BeautifulSoup
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B="https://yq.wzrc.net/index.php?m=&c=Jobs&a=jobs_list"
def first_titles(qs):
    r=requests.get(B+qs,headers=H,timeout=25,verify=False); r.encoding=r.apparent_encoding
    soup=BeautifulSoup(r.text,"lxml")
    ts=[a.get_text(strip=True) for a in soup.find_all("a",href=True) if "jobs_show" in a["href"]]
    return ts[:4]
for qs in ["&jobtag=147","&jobtag=147&page=2","&jobtag=147&page=3"]:
    print(qs, first_titles(qs))
# 分页控件
r=requests.get(B+"&jobtag=147",headers=H,timeout=25,verify=False); r.encoding=r.apparent_encoding
soup=BeautifulSoup(r.text,"lxml")
print("--- 分页区 ---")
for a in soup.find_all("a",href=True):
    if a.get_text(strip=True) in ("下一页","最后一页","2","3","1"):
        print(f"  {a.get_text(strip=True):6s} {a['href']}")
