import requests,re
from bs4 import BeautifulSoup
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
r=requests.get("https://www.yqrc.com/job?salary=5&welfare=5",headers=H,timeout=20,verify=False)
r.encoding=r.apparent_encoding
open(r"D:\agent-work\data\raw\_probe_sw.html","w",encoding="utf-8").write(r.text)
soup=BeautifulSoup(r.text,"lxml")
items=[li for li in soup.select("div.jobs-list-container li, div.jobs-list li, ul li") if li.find("a",href=re.compile("jobinfo_"))]
print("items",len(items))
if items:
    print(re.sub(r"\n\s*\n","\n",items[0].prettify())[:2500])
# 分页
pg=[int(x) for x in re.findall(r"[?&]page=(\d+)",r.text)]
print("max page seen:",max(pg) if pg else None)
m=re.search(r"共([\d,]+)\s*个?职位",r.text)
print("total text:",m.group(0) if m else "n/a")
