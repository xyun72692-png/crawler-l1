import requests,re
from bs4 import BeautifulSoup
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B="https://yq.wzrc.net/index.php?m=&c=Jobs&a=jobs_list"
def probe(qs):
    r=requests.get(B+qs,headers=H,timeout=25,verify=False); r.encoding=r.apparent_encoding
    soup=BeautifulSoup(r.text,"lxml")
    cards=soup.select("div.J_jobsList")
    links=[a for a in soup.find_all("a",href=True) if "jobs_show" in a["href"]]
    pg=[int(x) for x in re.findall(r"[?&]page=(\d+)",r.text)]
    return len(cards),len(links),(max(pg) if pg else 1)
for qs in ["&jobtag=147","&jobtag=147&page=2","&jobtag=147&page=5","&jobtag=147&page=10","&jobtag=147&page=20",
           "&jobtag=147&wage=60","&jobtag=147&wage=61","&jobtag=147&education=69"]:
    print(f"{qs:32s} cards/links/maxpage =",probe(qs))
