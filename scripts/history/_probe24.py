import requests,re
from bs4 import BeautifulSoup
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B="https://yq.wzrc.net/index.php?m=&c=Jobs&a=jobs_list"
r=requests.get(B+"&jobtag=147&page=2",headers=H,timeout=25,verify=False); r.encoding=r.apparent_encoding
s=BeautifulSoup(r.text,"lxml")
print("div.yli 全部:",len(s.select("div.yli")))
print("div.J_jobsList:",len(s.select("div.J_jobsList")))
ls=[a for a in s.find_all("a",href=True) if "jobs_show" in a["href"]]
print("jobs_show:",len(ls))
for a in ls:
    print("   ",a.get_text(strip=True)[:40])
