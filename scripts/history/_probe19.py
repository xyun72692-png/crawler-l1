import re
h=open(r"D:\agent-work\data\raw\_probe_yqwzrc_list.html",encoding="utf-8").read()
# 所有 jobs_list 筛选链接
pairs=re.findall(r"location\.href='/index\.php\?m=&c=Jobs&a=jobs_list&(\w+)=(\d+)'\"[^>]*>([^<]{1,10})<",h)
import collections
groups=collections.defaultdict(list)
for k,v,t in pairs: groups[k].append((v,t))
for k,v in groups.items():
    print(f"--- {k} ({len(v)}) ---")
    print("   "," ".join(f"{t}={c}" for c,t in v))
