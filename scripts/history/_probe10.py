import re
from bs4 import BeautifulSoup
h=open(r"D:\agent-work\data\raw\_probe_sw.html",encoding="utf-8").read()
soup=BeautifulSoup(h,"lxml")
links=[a for a in soup.find_all("a",href=re.compile("jobinfo_"))]
print("total jobinfo links:",len(links))
a=links[3]
chain=[];p=a
while p is not None and len(chain)<7:
    chain.append(f"{p.name}.{'.'.join(p.get('class',[]))}")
    p=p.parent
print("父链:", " < ".join(chain))
print("---卡片文本---")
card=a
for _ in range(4):
    card=card.parent
    txt=card.get_text(" | ",strip=True)
    if len(txt)>40:
        print(re.sub(r"\|+","|",txt)[:600]); break
