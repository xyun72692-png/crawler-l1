import requests,re
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
B="https://www.yqrc.com/job"
def probe(qs):
    r=requests.get(B+qs,headers=H,timeout=20,verify=False); r.encoding=r.apparent_encoding
    t=r.text
    n=t.count("jobinfo_")
    m=re.search(r"共\s*<[^>]*>(\d+)<",t) or re.search(r"(\d+)\s*个职位",t)
    pages=re.findall(r"page=(\d+)",t)
    mx=max([int(x) for x in pages],default=1)
    return r.status_code,n,mx,len(t)
for qs in ["","?welfare=5","?salary=5","?salary=5&welfare=5","?salary=6&welfare=5",
           "?education=1&salary=5&welfare=5","?education=2&salary=5&welfare=5",
           "?education=3&salary=5&welfare=5","?education=4&salary=5&welfare=5",
           "?education=5&salary=5&welfare=5","?education=6&salary=5&welfare=5"]:
    print(f"{qs:40s}",probe(qs))
