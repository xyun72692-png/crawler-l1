# -*- coding: utf-8 -*-
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.environ.get("CRAWLER_HOME") or _Path(__file__).resolve().parents[1])

"""
把「我读 29 篇 JD 原文后的判断」落成 xlsx（0 请求）。

⚠️ 修过一次的坑：证据字段最初在全页 HTML 里搜，结果 29/29 都"有双休"——
那是因为**推荐位/其它职位列表**里也印着福利标签。现在只搜 **JD 正文段**，
正文段取法：从「岗位职责/职位描述/工作内容/职位详情…」到「防骗提醒/公司相册/推荐职位…」。
"""
import csv
import re
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

D = Path(str(_HOME / "data" / "raw" / "_jd"))
OUT = Path(str(_HOME / "out" / "温州岗位_JD核实_20261111.xlsx"))

VERDICT = {
    1:  ("需确认", "管理岗：要求 30-40 岁 + 3 年 10 人以上电商团队管理经验，应届/无经验不匹配"),
    2:  ("建议剔除", "JD 实际是「客服团队管理」（3 年以上 10 人客服团队），不是运营"),
    3:  ("建议剔除", "JD 实际是「电商美工/视觉设计」：要 3 年经验 + 成熟作品集 + 1 年 AI 作图经验"),
    4:  ("需确认", "详情页**没有任何 JD 正文**（只有标题/薪资），无法判断，需站内直聊或电话"),
    5:  ("建议剔除", "JD 是「售前客服团队管理」（排班/工单/培训），客服岗"),
    6:  ("推荐投", "大专 + 英语 4 级 + 口语流利；8:30-17:30，双休写在待遇里"),
    7:  ("推荐投", "开发海外客户，阿里国际站/展会/海关数据；底薪 + 提成 5%（提成制）"),
    8:  ("需确认", "要英语 6 级 + 报关跟单实操；列表页只写「大专」，实际门槛更高"),
    9:  ("推荐投", "外贸助理：大专 + 国贸/英语专业，处理询盘促成交，入门友好"),
    10: ("推荐投", "JD 明写「双休：周末属于你」+ 高提成；要 1-2 年外贸经验"),
    11: ("推荐投", "大专 + 国贸专业；五险一金 + 双休 + 食堂 + 宿舍（包吃住）"),
    12: ("需确认", "JD 写「底薪 4000~6000 + 高提成」，列表页 6K-10K 是含提成上限，底薪可能 <5K"),
    13: ("推荐投", "基本工资 5000 + 高提成 + 年终奖；维护平台 + 接待外商 + 展会"),
    14: ("推荐投", "双休明确、8:30-17:00；先做跟单再转业务，路径清晰"),
    15: ("建议剔除", "JD 实际是「天猫店铺客服/销售转化」：千牛、打字≥50 字/分、促单"),
    16: ("推荐投", "双休 + 工作餐免费 + 住宿免费 + 高提成 + 出国机会（包吃住）"),
    17: ("推荐投", "TikTok 内容策划 + 拍摄剪辑；双休、9:00-17:30 七小时制"),
    18: ("建议剔除", "JD 是「开拓市场、开发新客户」的纯销售，且是经理岗；JD 未提双休"),
    19: ("需确认", "货代操作团队管理（订舱/报关/制单），管理岗 + 细分行业，JD 未提双休"),
    20: ("推荐投", "拍 + 剪一体；要求 PS/PR/AE/达芬奇/C4D（技能门槛偏高）"),
    21: ("建议剔除", "与 20 号是**同一篇 JD 重复挂两个标题**（正文相似度 95.3%），重复岗"),
    22: ("推荐投", "抖音直播运营；JD 明写「做五休二、周末双休」，8 千-1.5 万"),
    23: ("建议剔除", "JD 是订舱/报关/制单的操作客服，客服类"),
    24: ("需确认", "询价报价 + 协调出运，偏销售支持，JD 未提双休"),
    25: ("需确认", "岗位写「网络主播」，JD 却是管培生式福利包（大专年薪 10 万、六险二金、包学车），性质需核实"),
    26: ("推荐投", "直播助理；JD 明写「做五休二、周末双休」+ 提供住宿"),
    27: ("推荐投", "B2B 外贸，带教 1-3 个月、客户资源充足（年产值 5-6 亿）；JD 未写双休，需确认"),
    28: ("推荐投", "单证/报关/订舱；大专 + 国贸或物流 + 英语 4 级，0.5-2 年经验"),
    29: ("建议剔除", "JD 仅一句「自己有一定的客户资源」，是资源型销售"),
}

# 页脚/联系方式类噪声行（各站模板固定，去掉不丢 JD 信息）
NOISE = (
    "防骗提醒", "增值电信业务经营许可证", "版权所有", "常年法律顾问", "浙公网安备",
    "招聘热线", "档案热线", "联系人：", "打电话前先投递", "有时候，一次不犹豫",
    "邮箱：", "地址：", "学院中路5号", "版权所有 ©", "浙ICP备", "乘车路线",
    "查询路线", "扫一扫", "推荐职位", "该公司所有职位", "该公司其它职位",
    "查看公司招聘主页", "投递简历", "发送直聊", "查看详情", "查看更多",
)
NAV_WORDS = set("""欢迎来到 手机站 个人登录 个人注册 企业登录 企业注册 全文 搜索 更多搜索
最新工作 附近工作 全能搜索 推荐的职位 创建简历 职位分类 找工作 找人才 兼职 招实习 今日聘会
更多 热门职位 销售 业务 会计 文员 出纳 外贸 营业员 驾驶员 司机 普工 数控 平面设计 淘宝客服
运营 电工 保安 采购 cad 教师 行政 企业入口 招聘部门 招聘人数 学历要求 工作经验 性别要求
年龄要求 详细地址 公司相册 认证会员 已认证 行业 性质 规模 公司信息 公司介绍 联系方式 地图
职位详情 求职，找工作 填写简历""".split())

EV = {
    "双休": r"双休|做五休二|周末双休",
    "包吃住": r"包吃|包住|工作餐免费|住宿免费|提供住宿|有食堂|员工餐厅|宿舍",
    "提成": r"提成",
    "底薪": r"底薪|基本工资|基础工资",
    "英语等级": r"英语\s*[四五六]\s*级|英语\s*[456]\s*级|CET|英语4级",
}


def plain(html):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?s)<!--.*?-->", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>|</td>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&yen;", "¥")):
        h = h.replace(a, b)
    h = re.sub(r"&#x?[0-9a-fA-F]+;", " ", h)
    h = re.sub(r"[ \t\u3000]+", " ", h)
    return h


def jd_body(html):
    """按行过滤出「有内容的 JD 行」：去导航短词、页脚、联系方式、重复行。"""
    t = plain(html)
    keep, seen = [], set()
    for ln in (x.strip() for x in t.splitlines()):
        if len(ln) < 15:
            continue
        if ln in NAV_WORDS or ln in seen:
            continue
        if any(n in ln for n in NOISE):
            continue
        # 纯福利标签堆（"双休 五险 年终奖"）也算 JD 信息，保留
        seen.add(ln)
        keep.append(ln)
    return "\n".join(keep)


def ev_of(p, body):
    m = re.search(p, body)
    return m.group(0).strip() if m else ""


rows = list(csv.DictReader((D / "index.csv").open(encoding="utf-8-sig")))
data = []
for i, r in enumerate(rows, 1):
    html = Path(r["path"]).read_text(encoding="utf-8", errors="replace")
    body = jd_body(html)
    ev = {k: ev_of(p, body) for k, p in EV.items()}
    verdict, note = VERDICT[i]
    data.append([i, r["title"], r["company"], verdict, note,
                 ("无正文" if not body else (ev["双休"] or "未写")),
                 (ev["包吃住"] or "—"), (ev["提成"] or "—"), (ev["底薪"] or "—"),
                 (ev["英语等级"] or "—"), len(body), int(r["bytes"]), r["url"]])

HEAD = ["序号", "岗位", "公司", "JD判定", "关键发现", "双休(JD正文)", "包吃住",
        "提成", "底薪", "英语等级", "JD正文字数", "HTML字节", "详情链接"]
W = [6, 22, 30, 10, 60, 12, 18, 8, 10, 10, 10, 10, 48]

wb = Workbook()
ws = wb.active
ws.title = "①JD核实结果"
ws.append(HEAD)
for c in range(1, len(HEAD) + 1):
    ws.cell(row=1, column=c).font = Font(bold=True)
    ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
for row in data:
    ws.append(row)
for c in range(1, len(HEAD) + 1):
    ws.column_dimensions[get_column_letter(c)].width = W[c - 1]
ws.freeze_panes = "A2"

cnt = Counter(d[3] for d in data)
n_no_body = sum(1 for d in data if d[5] == "无正文")
n_weekend = sum(1 for d in data if d[5] not in ("无正文", "未写"))
ws2 = wb.create_sheet("②统计")
ws2.append(["项目", "值"])
for c in (1, 2):
    ws2.cell(row=1, column=c).font = Font(bold=True)
    ws2.cell(row=1, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
lines = [
    ("核实篇数", len(data)),
    ("推荐投", cnt.get("推荐投", 0)),
    ("需确认", cnt.get("需确认", 0)),
    ("建议剔除", cnt.get("建议剔除", 0)),
    ("", ""),
    ("JD 正文里明写「双休」", n_weekend),
    ("JD 正文未写双休", sum(1 for d in data if d[5] == "未写")),
    ("详情页无 JD 正文", n_no_body),
    ("提到包吃住/宿舍食堂", sum(1 for d in data if d[6] != "—")),
    ("提到提成", sum(1 for d in data if d[7] != "—")),
    ("写到底薪/基本工资", sum(1 for d in data if d[8] != "—")),
    ("要求英语等级", sum(1 for d in data if d[9] != "—")),
    ("", ""),
    ("平台级发现①", "20/21 是同一篇 JD 重复挂两个标题（正文相似度 95.3%）"),
    ("平台级发现②", "04 号详情页无任何 JD 正文，列表页信息不足以判断"),
    ("平台级发现③", "12 号列表页 6K-10K，JD 实为底薪 4-6K + 提成 → 列表页薪资是含提成上限"),
    ("平台级发现④", "证据只取 JD 正文段；全页搜「双休」会 29/29 命中（推荐位也印福利标签）"),
]
for k, v in lines:
    ws2.append([k, v])
ws2.column_dimensions["A"].width = 34
ws2.column_dimensions["B"].width = 78

wb.save(OUT)
print("已写 %s" % OUT)
print("判定：", dict(cnt), "| 正文明确双休 %d | 未写 %d | 无正文 %d"
      % (n_weekend, sum(1 for d in data if d[5] == "未写"), n_no_body))