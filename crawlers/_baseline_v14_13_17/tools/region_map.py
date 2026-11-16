# -*- coding: utf-8 -*-
"""地区 → 省份映射（foodmate 的 region 值是"商丘市/湖州市"这种市名，不带省）。

用途：foodmate 列表是全国岗位，robots 又禁了 search.php，**浙江/江苏只能本地筛**。
这层映射就是"本地筛"能不能落地的前提。

覆盖：浙江 11 个地级市 + 江苏 13 个地级市 + 两地常见的县级市/区。
取不到就返回 ""（**不猜**，绝不默认成浙江或江苏）。
"""

ZHEJIANG = [
    "杭州市", "宁波市", "温州市", "嘉兴市", "湖州市", "绍兴市", "金华市",
    "衢州市", "舟山市", "台州市", "丽水市",
]
JIANGSU = [
    "南京市", "无锡市", "徐州市", "常州市", "苏州市", "南通市", "连云港市",
    "淮安市", "盐城市", "扬州市", "镇江市", "泰州市", "宿迁市",
]
# 县级市/区（浙江）
ZJ_COUNTY = [
    "义乌市", "诸暨市", "余姚市", "慈溪市", "乐清市", "瑞安市", "温岭市",
    "海宁市", "桐乡市", "平湖市", "临海市", "玉环市", "嵊州市", "兰溪市",
    "东阳市", "永康市", "江山市", "龙泉市", "建德市", "余杭区", "萧山区",
    "鄞州区", "柯桥区", "吴兴区", "南湖区", "婺城区", "定海区", "椒江区", "莲都区",
]
# 县级市/区（江苏）
JS_COUNTY = [
    "江阴市", "宜兴市", "昆山市", "张家港市", "常熟市", "太仓市", "丹阳市",
    "扬中市", "句容市", "溧阳市", "如皋市", "海安市", "启东市", "东台市",
    "高邮市", "仪征市", "兴化市", "靖江市", "泰兴市", "沭阳县", "吴江区",
    "武进区", "江宁区", "锡山区", "铜山区", "淮安区", "盐都区", "广陵区",
    "京口区", "海陵区", "宿城区", "连云区", "泉山区", "天宁区", "虎丘区",
]

CITY_TO_PROVINCE = {}
for c in ZHEJIANG + ZJ_COUNTY:
    CITY_TO_PROVINCE[c] = "浙江"
for c in JIANGSU + JS_COUNTY:
    CITY_TO_PROVINCE[c] = "江苏"


def province_of(region, default=""):
    """'湖州市' → '浙江'；'商丘市' → ''（不在两地就不猜）。"""
    r = (region or "").strip()
    if not r:
        return default
    if r in CITY_TO_PROVINCE:
        return CITY_TO_PROVINCE[r]
    # 站上偶尔写成"浙江-湖州"或"浙江省湖州市"
    for name, prov in CITY_TO_PROVINCE.items():
        if name in r:
            return prov
    if "浙江" in r:
        return "浙江"
    if "江苏" in r:
        return "江苏"
    return default


def in_target(region):
    return province_of(region) in ("浙江", "江苏")