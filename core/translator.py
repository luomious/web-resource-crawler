"""
翻译工具模块 — 日/韩/英 → 中文。

使用 MyMemory 免费翻译 API（无需 API Key，国内可访问），
自动检测源语言并缓存结果。当翻译不可用时优雅降级返回原文。
"""

import logging
import re
from functools import lru_cache
from typing import Optional
from urllib.parse import quote

import requests

from core.constants import TIMEOUT, CONNECT_TIMEOUT

_log = logging.getLogger("translator")

# MyMemory 免费翻译 API（无需 Key，日均 5000 次调用限额）
_MYMEMORY_API = "https://api.mymemory.translated.net/get"


@lru_cache(maxsize=200)
def translate_to_zh(text: str) -> str:
    """将文本翻译为简体中文。

    自动跳过以下情况（返回原文）：
    - 纯中文文本
    - 纯数字/英文/符号文本
    - 空文本或空白文本

    Args:
        text: 待翻译的源文本（日文/韩文/英文等）。

    Returns:
        翻译后的简体中文文本；若翻译失败或无需翻译则返回原文。

    Example:
        >>> translate_to_zh("こんにちは")
        "你好"
        >>> translate_to_zh("你好世界")
        "你好世界"  # 已是中文，直接返回
    """
    if not text or not text.strip():
        return text

    has_kana = bool(re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    has_hangul = bool(re.search(r'[\uac00-\ud7af]', text))
    has_cjk = any('\u4e00' <= c <= '\u9fff' for c in text)

    # 纯中文 → 跳过
    if has_cjk and not has_kana and not has_hangul:
        return text
    # 纯数字/英文 → 跳过
    if not has_cjk and not has_kana and not has_hangul:
        return text

    # 确定源语言代码
    src = 'ja' if has_kana else ('ko' if has_hangul else 'en')

    try:
        # MyMemory API: GET ?q=text&langpair=src|zh-CN
        resp = requests.get(
            _MYMEMORY_API,
            params={
                "q": text[:500],
                "langpair": f"{src}|zh-CN",
            },
            timeout=(CONNECT_TIMEOUT, TIMEOUT),
        )
        resp.raise_for_status()
        data = resp.json()

        translated = data.get("responseData", {}).get("translatedText", "")
        # MyMemory 在无法翻译时会返回原文全大写，此时降级
        if translated and translated.upper() != text.upper():
            return translated

        # 尝试从 matches 中取最佳结果
        matches = data.get("matches", [])
        for m in matches:
            t = m.get("translation", "")
            if t and t.upper() != text.upper():
                return t

    except Exception as e:
        _log.warning(f"[translate] 翻译失败: {text[:30]}... — {e}")

    return text


def translate_chapters(
    chapters: list[tuple[int, int, str]],
) -> list[tuple[int, int, str, str]]:
    """翻译时间轴章节标题。

    为每个章节添加中文翻译字段。

    Args:
        chapters: 原始章节列表 [(start_sec, end_sec, 原标题), ...]。

    Returns:
        扩展后的章节列表 [(start_sec, end_sec, 原标题, 中译), ...]。
        若原文已是中文则中译字段为空字符串。

    Example:
        >>> translate_chapters([(0, 120, "第1話")])
        [(0, 120, "第1話", "第一话")]
    """
    if not chapters:
        return chapters

    result: list[tuple[int, int, str, str]] = []
    for start, end, title in chapters:
        zh = translate_to_zh(title)
        result.append((start, end, title, zh if zh != title else ""))
    return result
