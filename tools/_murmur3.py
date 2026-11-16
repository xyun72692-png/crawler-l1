# -*- coding: utf-8 -*-
"""
murmur3 x86_32 + favicon hash（纯 Python，零依赖，可离线自测）。

为什么要自己写：
  · favicon hash 的定义是 `murmur3_32(base64(ico字节))`，**base64 必须带换行**
    （Shodan / FOFA 的约定 = Python 的 base64.encodebytes，每 76 字符插一个 \\n）；
    用 b64encode（不带换行）算出来的 hash 拿去查，一个都查不到。
  · 纯 Python 版可以离线跑测试，不引入第三方包，也不影响 v12.3 基线。

自测：
    python tools\\_murmur3.py --selftest
"""

import base64
import sys

MASK32 = 0xFFFFFFFF
C1 = 0xCC9E2D51
C2 = 0x1B873593


def _rotl32(x, r):
    x &= MASK32
    return ((x << r) | (x >> (32 - r))) & MASK32


def murmur3_32(data, seed=0):
    """标准 MurmurHash3 x86_32。返回**有符号** 32 位（与 Python mmh3 库一致）。"""
    if not isinstance(data, (bytes, bytearray)):
        data = bytes(data)
    length = len(data)
    nblocks = length // 4
    h1 = seed & MASK32

    for i in range(nblocks):
        k1 = int.from_bytes(data[i * 4:i * 4 + 4], "little")
        k1 = (k1 * C1) & MASK32
        k1 = _rotl32(k1, 15)
        k1 = (k1 * C2) & MASK32
        h1 ^= k1
        h1 = _rotl32(h1, 13)
        h1 = (h1 * 5 + 0xE6546B64) & MASK32

    tail = data[nblocks * 4:]
    k1 = 0
    if len(tail) >= 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * C1) & MASK32
        k1 = _rotl32(k1, 15)
        k1 = (k1 * C2) & MASK32
        h1 ^= k1

    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & MASK32
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & MASK32
    h1 ^= h1 >> 16
    h1 &= MASK32
    return h1 - 0x100000000 if h1 & 0x80000000 else h1


def b64_newline(raw):
    """等价 base64.encodebytes：每 76 字符插 \\n，结尾也带 \\n。favicon hash 的指定编码。"""
    return base64.encodebytes(raw)


def favicon_hash(raw_bytes):
    """Shodan/FOFA 口径的 favicon hash：murmur3_32(base64_带换行(ico))。"""
    return murmur3_32(b64_newline(raw_bytes))


def favicon_hash_unsigned(raw_bytes):
    return favicon_hash(raw_bytes) & MASK32


# ---------------------------------------------------------------- 自测
VECTORS = [
    # (输入, 期望 hash, 是否需要外部校准)
    (b"", 0, False),
    (b"foo", -156908512, False),      # 0xF6A5C420
    (b"hello", 613153351, True),      # 0x248BFA47，待与 pip mmh3 或在线值核对
]


def selftest():
    ok = 0
    for data, want, needs_calib in VECTORS:
        got = murmur3_32(data)
        good = got == want
        ok += 1 if good else 0
        print("  %-10r → %12d  期望 %12d  %s%s"
              % (data, got, want, "PASS" if good else "FAIL",
                 "（待外部校准）" if needs_calib else ""))

    # base64 换行语义：76 字符一换行，结尾有 \n
    blob = bytes(range(80))
    b = b64_newline(blob)
    lines = b.split(b"\n")
    print("  b64 行数=%d 行长=%s 尾字节=%r"
          % (len([x for x in lines if x]), [len(x) for x in lines if x][:3], b[-1:]))
    assert b.endswith(b"\n"), "base64.encodebytes 必须以换行结尾"
    assert max(len(x) for x in lines) <= 76, "每行不得超过 76 字符"
    assert b.replace(b"\n", b"") == base64.b64encode(blob), "去换行后必须等于 b64encode"

    # 无符号转换
    print("  favicon_hash(b'foo') 有符号=%d 无符号=%d"
          % (favicon_hash(b"foo"), favicon_hash_unsigned(b"foo")))
    print("结论：%d/%d 条向量通过，b64 语义断言通过" % (ok, len(VECTORS)))
    return 0 if ok == len(VECTORS) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)