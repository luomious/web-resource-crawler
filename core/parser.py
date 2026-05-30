"""
资源解析模块 — 从 HTML 中提取图片/音频/视频/HLS/文档等资源。

包含 10 层解析策略 + 时间轴章节提取。
架构：parse_resources() 作为调度器，各策略提取为独立子函数。
"""

import logging
import re
from typing import Optional, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.constants import (
    IMG_EXTS,
    AUDIO_EXTS,
    VIDEO_EXTS,
    DOC_EXTS,
    CSS_EXTS,
    JS_EXTS,
    SUBTITLE_EXTS,
)
from core.unpacker import extract_m3u8_from_html

_log = logging.getLogger("parser")

# img 懒加载属性全覆盖
_IMG_LAZY_ATTRS = [
    "src", "data-src", "data-original", "data-actualsrc",
    "data-lazy-src", "data-url", "data-img", "load-src",
    "_src", "src2", "layz-src", "original",
]

# script JSON 播放器正则（6 种常见格式）
_AUDIO_JSON_PATTERNS = [
    r'["\'](?:m4a|mp3|mp4|oga|ogg)["\']\s*:\s*"([^"]+)"',
    r'["\']url["\']\s*:\s*"(https?://[^"]*?\.(?:mp3|m4a|wav|flac|ogg|aac|opus|mp4|webm|m3u8)[^"]*)"',
    r'["\']src["\']\s*:\s*"(https?://[^"]*?\.(?:mp3|m4a|wav|flac|mp4|webm|m3u8)[^"]*)"',
    r'["\']audio["\']\s*:\s*"([^"\']*?\.(?:mp3|m4a|wav|flac|ogg|aac|opus|m3u8)[^"\']*?)"',
    r'["\']sound["\']\s*:\s*"([^"\']*?\.(?:mp3|m4a|wav|flac|ogg|aac|opus|m3u8)[^"\']*?)"',
    r'["\']source["\']\s*:\s*"([^"\']*?\.(?:mp3|m4a|wav|flac|mp4|webm|m3u8)[^"\']*?)"',
]


# ── 数据类 ────────────────────────────────────────────────────────

from dataclasses import dataclass
from typing import Optional


@dataclass
class Resource:
    """抓取到的资源对象。

    Attributes:
        url: 资源完整 URL。
        rtype: 资源类型（图片 / 音频 / 视频 / 音频-HLS / 视频-HLS / 样式 / 脚本 / 文档）。
        name: 文件名（从 URL 提取并解码）。
        size: 文件大小字符串（预留字段，当前未使用）。
        checked: 是否默认勾选（GUI 用）。
        source: 来源页面 URL。
        chapters: 时间轴章节列表 [(start_sec, end_sec, title), ...]（ASMR 站点）。
    """
    url: str
    rtype: str
    name: str
    size: str = ""
    checked: bool = True
    source: str = ""
    chapters: Optional[list] = None


# ── 工具函数 ─────────────────────────────────────────────────────

def classify(url: str, candidate_type: str = "") -> str:
    """根据 URL 扩展名对资源进行分类。"""
    lower = url.lower()
    for ext in IMG_EXTS:
        if ext in lower:
            return "图片"
    for ext in AUDIO_EXTS:
        if ext in lower:
            return "音频"
    for ext in VIDEO_EXTS:
        if ext in lower:
            return "视频"
    if ".m3u8" in lower:
        # 根据 URL 关键词区分视频/音频 HLS
        if any(kw in lower for kw in ("video", "mp4", "movie", "vid")):
            return "视频-HLS"
        return "音频-HLS"
    for ext in CSS_EXTS:
        if ext in lower:
            return "样式"
    for ext in JS_EXTS:
        if ext in lower:
            return "脚本"
    for ext in DOC_EXTS:
        if ext in lower:
            return "文档"
    for ext in SUBTITLE_EXTS:
        if ext in lower:
            return "字幕"
    return candidate_type or "其他"


def extract_name(url: str) -> str:
    """从 URL 中提取文件名（支持 query 参数 fallback）。"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    name = parsed.path.split("/")[-1]

    if not name or "." not in name:
        for part in parsed.query.split("&"):
            if part.startswith(("src=", "url=", "file=", "name=")):
                name = part.split("=", 1)[1].split("/")[-1]
                break
        if not name:
            name = "untitled"

    try:
        name = name.encode("latin1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        _log.debug(f"[extract_name] 编码修复失败: {url[:80]}")
    return name


def extract_chapters(soup: BeautifulSoup, html: str) -> Optional[list]:
    """从 ASMR 页面提取时间轴章节 [(start, end, title), ...]."""
    chapter_div = (
        soup.find("div", id="chapter")
        or soup.find("div", class_="chapter")
    )
    if not chapter_div:
        for tab in soup.select(".tab_content"):
            c = tab.find("div", id="chapter")
            if c:
                chapter_div = c
                break

    if not chapter_div:
        return None

    items = []
    for a in chapter_div.find_all("a"):
        try:
            start = int(float(a.get("data-value", "0")))
        except (ValueError, TypeError):
            continue
        text = re.sub(r'\s*\d{2}:\d{2}:\d{2}\s*$', '', a.get_text(strip=True))
        items.append((start, None, text.strip() or f"章节 {len(items) + 1}"))

    if len(items) < 2:
        return None

    result = []
    for i in range(len(items) - 1):
        result.append((items[i][0], items[i + 1][0], items[i][2]))
    result.append((items[-1][0], items[-1][0] + 99999, items[-1][2]))
    return result


def _make_add(
    source_url: str,
    resources: list,
    seen_urls: set,
) -> Callable[[str, str], None]:
    """创建资源收集函数（闭包，捕获 shared state）。"""
    def _add(url: str, rtype: str) -> None:
        if not url or url.startswith(("data:", "mailto:", "javascript:", "#", "blob:")):
            return
        # 处理包装 URL（?url=...）
        if "?url=" in url:
            m = re.search(r'[?&]url=([^&]+)', url)
            if m:
                url = m.group(1)
        full = urljoin(source_url, url)
        if full in seen_urls:
            return
        seen_urls.add(full)
        rtype = rtype or "其他"
        if rtype == "其他":
            rtype = classify(full, rtype)
        resources.append(Resource(
            url=full,
            rtype=rtype,
            name=extract_name(full),
            source=source_url,
        ))
    return _add


# ── 各层解析子函数 ──────────────────────────────────────────────

def _parse_hls(html: str, _add: Callable) -> None:
    """层1：m3u8 HLS 流（直接引用 + JS 混淆解码）。"""
    for url in extract_m3u8_from_html(html):
        _add(url, "")  # let classify decide audio/video HLS


def _parse_imgs(soup: BeautifulSoup, _add: Callable) -> None:
    """层2：<img> 标签（含懒加载属性 + srcset）。"""
    for img in soup.select("img"):
        for attr in _IMG_LAZY_ATTRS:
            _add(img.get(attr) or "", "图片")
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        if srcset:
            for part in srcset.split(","):
                url_part = part.strip().split()[0]
                if url_part:
                    _add(url_part, "图片")


def _parse_media_tags(soup: BeautifulSoup, _add: Callable) -> None:
    """层3：<video> / <audio> / <source> 含 data-* 属性。"""
    for tag_name, default_type in [("video", "视频"), ("audio", "音频")]:
        for el in soup.find_all(tag_name):
            _add(el.get("src") or "", default_type)
            _add(el.get("poster") or "", "图片")
            for src_el in el.find_all("source"):
                _add(src_el.get("src") or "", default_type)
            for attr in [
                "data-src", "data-url", "data-mp3", "data-audio",
                "data-video", "data-source", "data-m4a",
            ]:
                _add(el.get(attr) or "", default_type)


def _parse_media_links(soup: BeautifulSoup, _add: Callable) -> None:
    """层4：<a> 直链（音视频扩展名）。"""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        ext = "." + lower.split(".")[-1].split("?")[0] if "." in lower else ""
        if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
            _add(href, classify(href))
        elif ".m3u8" in lower:
            _add(href, classify(href))  # classify handles audio/video HLS


def _parse_css_js(soup: BeautifulSoup, _add: Callable) -> None:
    """层5：CSS/JS 链接。"""
    for link in soup.select("link[rel='stylesheet']"):
        _add(link.get("href") or "", "样式")
    for script in soup.select("script[src]"):
        _add(script.get("src") or "", "脚本")


def _parse_script_json(soup: BeautifulSoup, _add: Callable) -> None:
    """层6：<script> JSON 播放器配置（6 种正则）。"""
    for script in soup.find_all("script"):
        text = script.string or ""
        if not text or len(text) < 20:
            continue
        for pat in _AUDIO_JSON_PATTERNS:
            for m in re.finditer(pat, text, re.I):
                url = m.group(1).strip("'\"\\")
                _add(url, classify(url))


def _parse_html_fulltext(html: str, _add: Callable) -> None:
    """层7：HTML 全文中音视频直链。"""
    for pat, rtype in [
        (r'(https?://[^\s"\'<>&]+\.(?:mp3|m4a|wav|flac|ogg|opus|aac|ape|wma)(?:\?[^\s"\'<>&]*)?)', "音频"),
        (r'(https?://[^\s"\'<>&]+\.(?:mp4|webm|mkv|avi|mov|flv|m4v)(?:\?[^\s"\'<>&]*)?)', "视频"),
    ]:
        for m in re.finditer(pat, html, re.I):
            _add(m.group(1).rstrip("'\"\\"), rtype)


def _parse_css_background(html: str, _add: Callable) -> None:
    """层8：CSS 背景图 url(...)。"""
    for m in re.finditer(r'url\(\s*(["\']?)([^)]*?)\1\s*\)', html):
        raw = m.group(2).strip()
        if raw and raw.startswith("http") and not raw.startswith("data:"):
            _add(raw, "图片")


def _parse_doc_links(soup: BeautifulSoup, seen_urls: set, _add: Callable) -> None:
    """层9：<a> 普通文档链接。"""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        ext = "." + lower.split(".")[-1].split("?")[0] if "." in lower else ""
        if ext in DOC_EXTS and href not in seen_urls:
            _add(href, "文档")


# ── 主调度函数 ───────────────────────────────────────────────────

def parse_resources(html: str, base_url: str, source_url: str = "") -> list:
    """解析 HTML，提取所有可用资源。

    10 层解析策略（按优先级）：
    1. m3u8 HLS 流（直接引用 + JS 混淆解码）
    2. <img> 标签（含懒加载属性 + srcset）
    3. <video> / <audio> / <source>
    4. <a> 直链（音视频扩展名）
    5. CSS/JS 链接
    6. <script> JSON 播放器配置（6 种正则）
    7. HTML 全文中音视频直链
    8. CSS 背景图 url(...)
    9. <a> 普通文档链接
    10. 时间轴章节（附到 HLS 资源上）

    Args:
        html: 页面 HTML 源码。
        base_url: 页面基础 URL（用于拼接相对路径）。
        source_url: 来源页面 URL（写入 Resource.source 字段）。

    Returns:
        Resource 对象列表。
    """
    from core.asmr_one import is_asmr_one, parse_asmr_one

    # asmr.one 走专用 API
    if is_asmr_one(base_url):
        return parse_asmr_one(base_url)

    soup = BeautifulSoup(html, "lxml")
    resources: list = []
    seen_urls: set = set()
    effective_source = source_url or base_url

    _add = _make_add(effective_source, resources, seen_urls)

    # 依次执行各层解析
    _parse_hls(html, _add)
    _parse_imgs(soup, _add)
    _parse_media_tags(soup, _add)
    _parse_media_links(soup, _add)
    _parse_css_js(soup, _add)
    _parse_script_json(soup, _add)
    _parse_html_fulltext(html, _add)
    _parse_css_background(html, _add)
    _parse_doc_links(soup, seen_urls, _add)

    # 层10：时间轴章节附到 HLS 资源
    chapters = extract_chapters(soup, html)
    if chapters:
        _log.info(f"[parse] 提取到 {len(chapters)} 个时间轴章节")
        for r in resources:
            if "HLS" in r.rtype or ".m3u8" in r.url:
                r.chapters = chapters

    _log.info(
        f"[parse] {base_url} -> {len(resources)} 资源 "
        f"(HLS:{sum(1 for r in resources if 'HLS' in r.rtype)}, "
        f"图:{sum(1 for r in resources if r.rtype=='图片')}, "
        f"音:{sum(1 for r in resources if '音频' in r.rtype)}, "
        f"视:{sum(1 for r in resources if '视频' in r.rtype)})"
    )
    return resources
