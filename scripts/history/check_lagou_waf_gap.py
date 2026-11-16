# -*- coding: utf-8 -*-
"""离线复核三件事（0 请求）：
① 阿里云 WAF 原始 HTML 里是否含 probe_one 的 CAPTCHA_HINTS 中文提示词
② 把 WAF 页当 robots.txt 喂给 RobotFileParser，会判允许还是禁止
③ 引擎 crawler.load_robots 对同一份内容怎么判
"""
import io, sys
from pathlib import Path
from urllib.robotparser import RobotFileParser

RAW = Path(r"D:\agent-work\data\raw\_probe_lagou")
home = RAW.joinpath("home.html").read_text(encoding="utf-8", errors="replace")
robots = RAW.joinpath("robots.txt").read_text(encoding="utf-8", errors="replace")

HINTS = ("身份验证", "安全验证", "验证码", "人机验证", "请完成验证",
         "访问验证", "访问受限", "滑动验证")
print("== ① probe_one 的 CAPTCHA_HINTS 在 WAF 原始 HTML 里命中情况 ==")
for h in HINTS:
    print(f"   {h!r:12} -> {'命中' if h in home else '未命中'}")

print("\n== ② 标准 RobotFileParser 解析这张 WAF 页 ==")
rp = RobotFileParser()
rp.parse(io.StringIO(robots).readlines())
for u in ("https://www.lagou.com/wn/jobs?kd=java&pn=1",
          "https://www.lagou.com/wn/",
          "https://www.lagou.com/anything/private"):
    print(f"   can_fetch('*', {u[:52]}) = {rp.can_fetch('*', u)}")
print("   解析出的规则条数 entries =", len(rp.entries), " / default_entry.allowed =",
      rp.default_entry.allowed)

print("\n== ③ 引擎 crawler.load_robots 的口径 ==")
sys.path.insert(0, r"D:\agent-work\crawlers")
try:
    import crawler
    import inspect
    src = inspect.getsource(crawler.load_robots)
    print(src[:1800])
except Exception as e:
    print("读源码失败:", type(e).__name__, e)