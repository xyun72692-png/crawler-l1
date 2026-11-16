import re
from bs4 import BeautifulSoup
h=open(r"D:\agent-work\data\raw\_probe_yqwzrc_list.html",encoding="utf-8").read()
s=BeautifulSoup(h,"lxml")
box=s.select_one("div.listb.J_allListBox") or s.select_one("div.listb")
items=box.find_all("div",class_="yli")
print("yli 数量:",len(items))
print(re.sub(r"\n\s*\n","\n",items[0].prettify())[:2600])
