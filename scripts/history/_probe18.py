import re
h=open(r"D:\agent-work\data\raw\_probe_yqwzrc_list.html",encoding="utf-8").read()
for kw in ["双休","welfare","salary","education","学历"]:
    idxs=[m.start() for m in re.finditer(kw,h)]
    print(f"=== {kw} 次数={len(idxs)}")
    for i in idxs[:3]:
        print("   ",re.sub(r"\s+"," ",h[max(0,i-220):i+180]))
