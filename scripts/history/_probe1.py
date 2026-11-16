import requests, sys
requests.packages.urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
sites=[
 ("温州人才网","https://www.wzrc.com/"),
 ("温州人才网2","https://www.wzrc.net/"),
 ("乐清人才网","https://www.leqingrc.com/"),
 ("乐清人才网2","https://www.yqrc.com/"),
 ("乐清人才网3","https://www.lqrcw.com/"),
 ("乐清政府","https://www.yueqing.gov.cn/"),
 ("乐清人社","http://hrss.yueqing.gov.cn/"),
 ("温州人社","http://hrss.wenzhou.gov.cn/"),
 ("58乐清","https://lq.58.com/job/"),
 ("智联","https://www.zhaopin.com/"),
 ("51job","https://www.51job.com/"),
 ("BOSS","https://www.zhipin.com/"),
 ("百姓网","https://wenzhou.baixing.com/gongzuo/"),
]
for name,u in sites:
    try:
        r=requests.get(u,headers=H,timeout=12,verify=False,allow_redirects=True)
        t=r.text
        print(f"{name:10s} {r.status_code} len={len(t):6d} final={r.url[:70]}")
    except Exception as e:
        print(f"{name:10s} ERR {type(e).__name__} {str(e)[:60]}")
