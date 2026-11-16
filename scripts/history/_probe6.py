import re
html=open(r"D:\agent-work\data\raw\_probe_yqrc_job.html",encoding="utf-8").read()
i=html.find('id="education_select"')
print(re.sub(r"\s+"," ",html[i-200:i+1500]))
