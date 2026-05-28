"""
JS 混淆解码模块 — Dean Edwards Packer 反混淆。

支持从 eval(function(p,a,c,k,e,d){...}) 格式的压缩 JS 中提取 m3u8 流地址。
"""

import re
import logging
from typing import Optional

from core.constants import CHUNK_SIZE

_log = logging.getLogger("unpacker")


def unpack_js(packed: str) -> Optional[str]:
    """解码 Dean Edwards Packer 格式的 eval 压缩 JS。

    解析 eval(function(p,a,c,k,e,d){...}(...)) 结构，还原原始代码。

    Args:
        packed: 包含 Packer 压缩的 JS 代码段。

    Returns:
        解码后的 JS 代码字符串；若输入格式不匹配则返回 None。

    Example:
        >>> unpack_js("eval(function(p,a,c,k,e,d){...}(...))")
        "var test = 'hello'"
    """
    m = re.search(
        r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)\s*\{.*?\}\s*\("
        r"'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\s*\.split\s*\(\s*'\|'\s*\)\s*,\s*0\s*,\s*\{\s*\}\s*\)\s*\)",
        packed, re.DOTALL,
    )
    if not m:
        return None

    p, a, c, k = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).split('|')

    def _e(v: int) -> str:
        """辅助函数：将数字 v 转为 base-a 编码的 key 字符串。"""
        r = ''
        if v >= a:
            r = _e(v // a)
        mod = v % a
        r += chr(mod + 29) if mod > 35 else '0123456789abcdefghijklmnopqrstuvwxyz'[mod]
        return r

    # 构建字典：key → 对应的词
    d: dict[str, str] = {}
    for i in range(c - 1, -1, -1):
        key = _e(i)
        d[key] = k[i] if i < len(k) and k[i] else key

    # 用词替换 key
    code = p
    for i in range(c - 1, -1, -1):
        key = _e(i)
        if key in d:
            code = re.sub(r'\b' + re.escape(key) + r'\b', d[key], code)

    return code


def extract_m3u8_from_html(html: str) -> list[str]:
    """从 HTML 源码中提取 m3u8 URL。

    覆盖两种来源：
    1. 直接引用的 .m3u8 地址（如 video src、iframe、a 标签等）
    2. Packer 混淆 JS 中的 .m3u8 地址（解码后提取，支持 loadSource 调用）

    Args:
        html: 完整的 HTML 页面源码。

    Returns:
        去重后的 m3u8 URL 列表。

    Example:
        >>> extract_m3u8_from_html('<script>eval(function(p,a,c,k...</script>')
        ['https://cdn.example.com/stream.m3u8']
    """
    urls: list[str] = []
    seen: set[str] = set()

    # ── 1. 直接引用 ──
    for m in re.finditer(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html):
        u = m.group(1).rstrip("'\"\\()")
        if u not in seen:
            seen.add(u)
            urls.append(u)

    # ── 2. 解码 eval-packer 混淆 ──
    packer_pattern = (
        r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)\s*\{.*?\}\s*\("
        r"'.*?'\s*,\s*\d+\s*,\s*\d+\s*,\s*'.*?'\.split\('\|'\)\s*,\s*0\s*,\s*\{\s*\}\s*\)\s*\)"
    )
    for m in re.finditer(packer_pattern, html, re.DOTALL):
        decoded = unpack_js(m.group(0))
        if not decoded:
            continue

        # 直接 m3u8 URL
        for u in re.finditer(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded):
            url = u.group(0).rstrip("'\"\\()")
            if url not in seen:
                seen.add(url)
                urls.append(url)

        # loadSource('...m3u8')
        for u in re.finditer(r"loadSource\s*\(\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", decoded):
            urls.append(u.group(1).rstrip("\\"))

    return urls