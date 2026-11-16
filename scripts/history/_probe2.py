import requests
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
for u in ["https://www.yqrc.com/robots.txt","https://www.wzrc.net/robots.txt"]:
    try:
        r=requests.get(u,headers=H,timeout=12,verify=False)
        print("=== ",u,r.status_code)
        print(r.text[:1200])
    except Exception as e:
        print("ERR",u,e)
