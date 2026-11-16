import requests,re,collections
from bs4 import BeautifulSoup
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def page(qs):
    r=requests.get("https://www.yqrc.com/job"+qs,headers=H,timeout=20,verify=False)
    r.encoding=r.apparent_encoding
    soup=BeautifulSoup(r.text,"lxml")
    cards=soup.select("div.jobs-item")
    rows=[]
    for c in cards:
        a=c.select_one("a.jobs-item__main__title")
        title=a.get_text(strip=True) if a else ""
        url=a["href"] if a else ""
        txt=[x.strip() for x in c.get_text("\n",strip=True).split("\n") if x.strip()]
        rows.append((title,url,txt))
    pg=[int(x) for x in re.findall(r"[?&]page=(\d+)",r.text)]
    return rows,max(pg) if pg else 1,r.text
for qs in ["?welfare=5&salary=5","?welfare=5",""]:
    rows,mp,raw=page(qs)
    print(f"=== {qs or '(无筛选)'}  卡片={len(rows)}  最大页码={mp}")
    if rows:
        t,u,txt=rows[0]
        print("   样本:",t,"|"," / ".join(txt[:14]))
    # 统计学历
    edu=collections.Counter()
    for t,u,txt in rows:
        for x in txt[:8]:
            if x in ("初中","高中","中专","中技","大专","本科","硕士","博士","不限","学历不限"):
                edu[x]+=1
    print("   学历分布:",dict(edu))
