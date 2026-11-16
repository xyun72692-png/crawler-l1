import re
html=open(r"D:\agent-work\data\raw\_probe_yqrc_job.html",encoding="utf-8").read()
for kw in ["学历","edu","jobedu","degree"]:
    idxs=[m.start() for m in re.finditer(kw,html)][:6]
    print("=== ",kw,len(idxs))
    for i in idxs[:4]:
        print("   ...",re.sub(r"\s+"," ",html[max(0,i-160):i+120]))
