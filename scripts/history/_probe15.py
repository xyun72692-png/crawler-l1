import re
h=open(r"D:\agent-work\data\raw\_probe_wzrc.html",encoding="utf-8").read()
print("=== 乐清 出现次数:",h.count("乐清"))
for m in list(re.finditer("乐清",h))[:5]:
    i=m.start(); print("   ...",re.sub(r"\s+"," ",h[max(0,i-260):i+140]))
print()
print("=== 表单里的 select/input ===")
for m in list(re.finditer(r"<(select|input)[^>]*>",h))[:40]:
    s=m.group(0)
    if any(k in s.lower() for k in ["city","area","edu","salary","welfare","keyword","district","trade"]):
        print("  ",re.sub(r"\s+"," ",s)[:200])
