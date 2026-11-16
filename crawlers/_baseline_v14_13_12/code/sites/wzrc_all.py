# -*- coding: utf-8 -*-
"""
站点配置：温州人才网（www.wzrc.net，74cms 系）按筛选条件抓职位

筛选参数（实测有效的组合）：
    citycategory  全温州=wenzhou / 市本级=shibenji / 鹿城区=luchengqu / 瓯海区=haiqu
                  龙湾区=longwanqu / 洞头区=dongtouxian / 乐清市=leqingshi / 瑞安市=ruianshi
                  永嘉县=yongjiaxian / 文成县=wenchengxian / 平阳县=pingyangxian
                  泰顺县=taishunxian / 苍南县=cangnanxian / 龙港市=longgangshi / 海经区=oujiangkou
    jobtag=147    双休标签
    wage          56=1K~1.5K 57=1.5K~2K 58=2K~3K 59=3K~5K 60=5K~10K 61=10K以上
    education     65=初中 66=高中 67=中技 68=中专 69=大专 70=本科 71=硕士 72=博士 73=博后
    page=N        数字分页

⚠ keyword 参数实测无效（各种关键词返回同一批结果），所以只能全量抓 + 本地关键词过滤。

验证状态（别写成"已验证"）：
    settr=3/7/15/30   【已验证】来源：站方自己页面的时间筛选链接（data/raw/_probe_wzrc.html）
    pagesize          【未验证】正常页（77KB）里没有任何该参数的痕迹，阶段B 才探测

环境变量控制（同一次运行只抓一个组合）：
    WZ_CITY   地区码，默认 wenzhou（全温州）
    WZ_TAG    jobtag，默认 147（双休）；传 "0" 表示不筛双休
    WZ_WAGE   wage 档，默认空（不筛薪资）
    WZ_PAGES  结束页

列表卡片 div.J_jobsList（与乐清分站同一套选择器，已实测兼容）。
"""

import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ._common import TOTAL_PAGES_PATTERN
from .families.qscms74 import parse_jobs

BASE = "https://www.wzrc.net"
CITY = os.environ.get("WZ_CITY", "wenzhou")
TAG = os.environ.get("WZ_TAG", "147")
WAGE = os.environ.get("WZ_WAGE", "")
TRADE = os.environ.get("WZ_TRADE", "")
WZKEY = os.environ.get("WZ_KEY", "")
JOBSUFFIX = os.environ.get("WZ_SUFFIX", "")
PAGES = int(os.environ.get("WZ_PAGES", "150"))  # 安全上限 150（站点声明值会把它夹紧）
# 为什么不是 40：全温州 949 页，40 页会漏掉大半；为什么不是 949：
# 先给一个"够用但不出事"的上限，真实页数由页面声明的 M 决定（见 total_pages_pattern）
# settr：站方时间筛选。已验证只接受 3/7/15/30（来源：站方 HTML 的时间筛选链接）
SETTR = os.environ.get("WZ_SETTR", "").strip()
if SETTR and SETTR not in ("3", "7", "15", "30"):
    raise SystemExit("WZ_SETTR=%r 非法：只接受 3/7/15/30（已从站方页面确认）" % SETTR)
# pagesize：**未验证**，正常页 HTML 里没有这个参数的痕迹。只留探测用，默认不加。
PAGE_SIZE = os.environ.get("WZ_PAGE_SIZE", "").strip()

CITY_NAME = {
    "wenzhou": "全温州", "shibenji": "市本级", "luchengqu": "鹿城区", "haiqu": "瓯海区",
    "longwanqu": "龙湾区", "dongtouxian": "洞头区", "leqingshi": "乐清市", "ruianshi": "瑞安市",
    "yongjiaxian": "永嘉县", "wenchengxian": "文成县", "pingyangxian": "平阳县",
    "taishunxian": "泰顺县", "cangnanxian": "苍南县", "longgangshi": "龙港市", "oujiangkou": "海经区",
}.get(CITY, CITY)
WAGE_NAME = {"56": "1K-1.5K", "57": "1.5K-2K", "58": "2K-3K", "59": "3K-5K",
             "60": "5K-10K", "61": "10K以上"}.get(WAGE, WAGE or "不限")
TRADE_NAME = {
    "1": "计算机软件/硬件", "2": "计算机系统/维修", "3": "通信", "4": "互联网/电子商务",
    "5": "网络游戏", "6": "电子/半导体", "7": "仪器仪表/工业自动化", "8": "会计/审计",
    "9": "金融(投资/证券)", "10": "金融(银行/保险)", "11": "贸易/进出口", "12": "批发/零售",
    "13": "消费品", "14": "服装/纺织/皮革", "15": "家具/家电/工艺品/玩具", "16": "办公用品及设备",
    "17": "机械/设备/重工", "18": "汽车/摩托车/零配件", "19": "制药/生物工程",
    "20": "医疗/美容/保健/卫生", "21": "医疗设备/器械", "22": "广告/市场推广", "23": "会展/博览",
    "24": "影视/媒体/艺术/出版", "25": "印刷/包装/造纸", "26": "房地产开发",
    "27": "建筑与工程", "28": "家居/室内设计/装潢", "29": "物业管理/商业中心",
    "30": "中介服务/家政服务", "31": "专业服务/财会/法律", "32": "检测/认证",
    "33": "教育/培训", "34": "学术/科研", "35": "餐饮/娱乐/休闲", "36": "酒店/旅游",
    "37": "交通/运输/物流", "38": "航天/航空", "41": "电力/水利/新能源",
    "42": "政府部门/事业单位", "43": "非盈利机构/行业协会", "45": "其他行业",
}.get(TRADE, TRADE)

_q = "m=&c=Jobs&a=jobs_list&citycategory=" + CITY
if WZKEY:
    from urllib.parse import quote as _quote
    _q += "&key=" + _quote(WZKEY)
if TAG and TAG != "0":
    _q += "&jobtag=" + TAG
if WAGE:
    _q += "&wage=" + WAGE
if TRADE:
    _q += "&trade=" + TRADE
if SETTR:
    _q += "&settr=" + SETTR
if PAGE_SIZE:
    # 仅探针：写进 CONFIG，报告里才看得到（page_size / page_size_probe）
    CONFIG["page_size"] = PAGE_SIZE
    CONFIG["page_size_probe"] = True
    # 未验证参数：只在探测时用，别写进正式任务
    _q += "&pagesize=" + PAGE_SIZE
_q += "&page={page}"

CONFIG = {
    # Rule 0（v14）：条款已人工确认：该站公开岗位页允许访问
    "terms_status": "allowed",
    "job": "wzrc_kw" + (JOBSUFFIX or "x"),
    "url_template": BASE + "/index.php?" + _q,
    "paginate": "number",
    "page_start": 1,
    "page_end": PAGES,

    # 站点级降载：2026-11-11 实测约 150 次请求就被 IP 级限流，
    # 所以这里 3~5 秒 + 只重试 1 次（不是全局默认，别的站不受影响）
    "delay_min": 3.0,
    "delay_max": 5.0,
    "timeout": 25,
    "retries": 1,
    "backoff": 2.0,

    "respect_robots": True,
    # v14.4：TLS 指纹对齐（A/B 已验证结果一致：foodmate 200/200、wzrc 46/46、foodlaw 20/20）
    "transport": "cffi",
    # v14.5：published 常见"30分钟前"这种相对时间，会随抓取时刻变；
    # 它不属于内容变化，排除出 content_hash（P1 会补 published_at 绝对时间）
    "hash_exclude": ["published"],
    "dedup_key": "detail_url",
    # 页面里 <span>1</span>/M页 → 声明总页数（读不到就按配置跑）
    "total_pages_pattern": TOTAL_PAGES_PATTERN,   # 唯一副本见 _common.py

    "detail": {"enabled": False},
    "attachments": {"enabled": False},

    # 软封判定：空页时用「双休第 1 页」做 canary（这页一定有结果）
    "soft_block": {
        "enabled": True,
        "canary_url": BASE + "/index.php?m=&c=Jobs&a=jobs_list&citycategory=wenzhou&jobtag=147&page=1",
        "cooldown_sec": [7200, 21600, 86400],
        # 同一家站的子域共用一把锁：WAF 通常按 IP 封，子站会一起死
        "group": "wzrc",
    },

    "out_dir": r"D:\agent-work\data\raw",
    "log_dir": r"D:\agent-work\logs",
    "state_dir": r"D:\agent-work\manifests",
    "report_dir": r"D:\agent-work\out\reports",
}


def parse_list(html, page_url):
    return parse_jobs(html, page_url,
                      source_site="温州人才网(温州/关键词:%s)" % (WZKEY or "无"),
                      keep_area=True)
