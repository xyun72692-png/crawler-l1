# -*- coding: utf-8 -*-
"""P1a：把相对时间落成绝对时间（一个函数，五个站共用）。

**只做解析正确性**，不碰 hash、不碰报告口径（那是 P1b，等真要做周报再定）。

设计口径（每条都有对应测试）：
  ① 锚点是**抓取时刻**（fetched_at），不是 now()；算完就存进记录，永不重算
  ② 精度必须记录：minute / hour / day / unknown —— 不假装是精确时间
  ③ 空值**绝不 fallback** 到 fetched_at：那会把"不知道"变成"刚发布"，
     周报里全是假新增。空 → published_at="" + quality="unknown"
  ④ 时区固定 +08:00（站点给的是本地时间，混 UTC 会整体错 8 小时）
  ⑤ 无年份（11-13）若解析结果晚于锚点 → 减一年（一月份不炸）
  ⑥ "昨天" 锚到 anchor - 1天的同一时刻，不锚 00:00
  ⑦ 幂等：同一 (text, anchor) 必须产出逐字节一致的结果
"""

from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))

# 精度枚举
P_MINUTE, P_HOUR, P_DAY, P_UNKNOWN = "minute", "hour", "day", "unknown"
Q_OK, Q_UNKNOWN = "ok", "unknown"

_REL = (
    ("秒前", "second"),
    ("刚刚", "minute"),
    ("分钟前", "minute"),
    ("小时前", "hour"),
    ("天前", "day"),
    ("周前", "day"),
)

_ABS_PATTERNS = (
    # 2026-11-14 21:05 / 2026-11-14 21:05:30
    ("%Y-%m-%d %H:%M:%S", r"^\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2}:\d{2}$"),
    ("%Y-%m-%d %H:%M", r"^\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2}$"),
    ("%Y-%m-%d", r"^\d{4}-\d{1,2}-\d{1,2}$"),
    ("%Y/%m/%d %H:%M", r"^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}$"),
    ("%Y/%m/%d", r"^\d{4}/\d{1,2}/\d{1,2}$"),
    # 无年份：11-14 / 11/14 / 11月14日
    ("%m-%d", r"^\d{1,2}-\d{1,2}$"),
    ("%m/%d", r"^\d{1,2}/\d{1,2}$"),
)


def _ensure_tz(dt):
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def _iso(dt):
    return _ensure_tz(dt).isoformat(timespec="minutes")


def parse_relative_time(text, anchor=None):
    """返回 (published_at, precision, quality)。

    text   : 原始字符串（"30分钟前" / "2026-11-14" / "11-14" / ""）
    anchor : 抓取时刻（带时区的 datetime）；默认取当前时间（**生产里必须显式传**）
    """
    import re
    raw = (text or "").strip()
    if anchor is None:
        anchor = datetime.now(TZ)
    anchor = _ensure_tz(anchor)

    # ③ 空值不猜
    if not raw:
        return "", P_UNKNOWN, Q_UNKNOWN

    # 绝对日期
    for fmt, pat in _ABS_PATTERNS:
        if re.match(pat, raw):
            try:
                dt = datetime.strptime(raw, fmt)
            except ValueError:
                continue
            if "%Y" not in fmt:
                # ⑤ 无年份：先按锚点年份，若结果晚于锚点 → 减一年
                dt = dt.replace(year=anchor.year)
                dt = _ensure_tz(dt)
                if dt > anchor:
                    dt = dt.replace(year=anchor.year - 1)
            else:
                dt = _ensure_tz(dt)
            prec = P_MINUTE if "%H" in fmt else P_DAY
            return _iso(dt), prec, Q_OK

    # 中文绝对日期：2026年11月14日
    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", raw)
    if m:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ)
        return _iso(dt), P_DAY, Q_OK
    m = re.match(r"^(\d{1,2})月(\d{1,2})日$", raw)
    if m:
        dt = datetime(anchor.year, int(m.group(1)), int(m.group(2)), tzinfo=TZ)
        if dt > anchor:
            dt = dt.replace(year=anchor.year - 1)
        return _iso(dt), P_DAY, Q_OK

    # 刚刚 / 刚刚发布 → 就是锚点本身（精度 minute）
    if raw in ("刚刚", "刚刚发布", "刚刚更新"):
        return _iso(anchor), P_MINUTE, Q_OK

    # 昨天 / 前天（⑥ 锚到同一时刻，不锚 00:00）
    if raw in ("昨天", "昨日"):
        return _iso(anchor - timedelta(days=1)), P_DAY, Q_OK
    if raw in ("前天",):
        return _iso(anchor - timedelta(days=2)), P_DAY, Q_OK
    if raw in ("今天", "今日"):
        return _iso(anchor), P_DAY, Q_OK

    # 相对：N秒前 / N分钟前 / N小时前 / N天前 / N周前
    m = re.match(r"^(\d+)\s*(秒|分钟|小时|天|周)前$", raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"秒": timedelta(seconds=n),
                 "分钟": timedelta(minutes=n),
                 "小时": timedelta(hours=n),
                 "天": timedelta(days=n),
                 "周": timedelta(weeks=n)}[unit]
        prec = {"秒": "second", "分钟": P_MINUTE, "小时": P_HOUR,
                "天": P_DAY, "周": P_DAY}[unit]
        return _iso(anchor - delta), prec, Q_OK

    # 认不出 → 不知道（不猜）
    return "", P_UNKNOWN, Q_UNKNOWN


def looks_relative(text):
    """运行期守卫用：这个值看起来是相对时间吗？"""
    raw = (text or "").strip()
    if not raw:
        return False
    if raw in ("昨天", "昨日", "前天", "今天", "今日", "刚刚"):
        return True
    for token, _p in _REL:
        if raw.endswith(token):
            return True
    return False