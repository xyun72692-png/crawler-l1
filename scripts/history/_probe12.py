import requests,re
from bs4 import BeautifulSoup
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def n(qs):
    r=requests.get("https://www.yqrc.com/job"+qs,headers=H,timeout=20,verify=False)
    r.encoding=r.apparent_encoding
    c=len(BeautifulSoup(r.text,"lxml").select("div.jobs-item"))
    pg=[int(x) for x in re.findall(r"[?&]page=(\d+)",r.text)]
    return c,(max(pg) if pg else 1)
for qs in ["?welfare=5&salary=5&page=2","?welfare=5&salary=5&page=3","?welfare=5&salary=5&page=5",
           "?welfare=5&salary=6&page=1","?welfare=5&salary=7&page=1","?welfare=5&salary=8&page=1",
           "?welfare=5&page=3","?welfare=5&page=10","?welfare=5&page=20"]:
    print(f"{qs:32s}",n(qs))
