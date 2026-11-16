import requests,re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
u="https://yq.wzrc.net/index.php?m=&c=jobs&a=jobs_list"
r=requests.get(u,headers=H,timeout=25,verify=False); r.encoding=r.apparent_encoding
h=r.text
open(r"D:\agent-work\data\raw\_probe_yqwzrc_list.html","w",encoding="utf-8").write(h)
print("status",r.status_code,"len",len(h))
soup=BeautifulSoup(h,"lxml")
# 卡片
cards=soup.select("div.job-item, li.job-item, div.jobs-item, div.list-item")
print("候选卡片容器:",[c.get("class") for c in cards[:1]],"count",len(cards))
links=[a for a in soup.find_all("a",href=True) if "jobs_show" in a["href"]]
print("jobs_show links:",len(links))
a=links[0]
chain=[];p=a
while p is not None and len(chain)<6:
    chain.append(f"{p.name}.{'.'.join(p.get('class',[]))}"); p=p.parent
print("父链:"," < ".join(chain))
card=a
for _ in range(3):
    card=card.parent
    t=card.get_text(" | ",strip=True)
    if len(t)>60: print("卡片文本:",re.sub(r"\|+","|",t)[:500]); break
# 分页
pg=[int(x) for x in re.findall(r"[?&]page=(\d+)",h)]
print("page max:",max(pg) if pg else 1)
