import re
h=open(r"D:\agent-work\data\raw\_probe_sw.html",encoding="utf-8").read()
i=h.find("jobinfo_")
seg=h[max(0,i-2500):i+2500]
print(re.sub(r"\s+"," ",seg))
