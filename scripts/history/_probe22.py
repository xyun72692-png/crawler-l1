import re
from bs4 import BeautifulSoup
print("########## yqrc.com 卡片 ##########")
h=open(r"D:\agent-work\data\raw\_probe_sw.html",encoding="utf-8").read()
s=BeautifulSoup(h,"lxml")
c=s.select("div.jobs-item")[0]
print(re.sub(r"\n\s*\n","\n",c.prettify())[:2200])
