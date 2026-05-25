"""
统一资源抓取 + 解析模块
提取图片 / 音频 / 视频 / HLS流 / CSS / JS / 文档
"""
import json
import re
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_log = logging.getLogger("scraper")

# ── 配置 ──────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]
TIMEOUT = 10
CONNECT_TIMEOUT = 5
MAX_RETRIES = 3
MAX_WORKERS = 6
CHUNK_SIZE = 65536

# 支持的文件扩展
IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".opus", ".wma", ".ape"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".m4v", ".ts"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".7z"}
CSS_EXTS = {".css"}
JS_EXTS = {".js"}


@dataclass
class Resource:
    """抓取到的资源"""
    url: str
    rtype: str          # 图片 / 音频 / 视频 / 音频-HLS / 样式 / 脚本 / 文档
    name: str           # 文件名
    size: str = ""      # 文件大小
    checked: bool = True
    source: str = ""    # 来源 URL
    chapters: list = None  # [(start_sec, end_sec, title), ...] 时间轴章节


def _make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=MAX_RETRIES, connect=MAX_RETRIES, read=MAX_RETRIES,
                  redirect=3, status_forcelist={500, 502, 503, 504, 429},
                  backoff_factor=1.0)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16))
    s.mount("http://", HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16))
    return s


def fetch_html(url: str) -> str:
    """下载页面 HTML"""
    s = _make_session()
    headers = {
        "User-Agent": USER_AGENTS[0],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
    resp = s.get(url, headers=headers, timeout=(CONNECT_TIMEOUT, TIMEOUT), allow_redirects=True)
    resp.raise_for_status()

    # 编码推断
    html = resp.text
    if resp.apparent_encoding and resp.apparent_encoding.lower() != "utf-8":
        try:
            html = resp.content.decode(resp.apparent_encoding)
        except Exception:
            html = resp.content.decode("utf-8", errors="replace")
    return html


# ══════════════════════════════════════════════════════════
#  JS 混淆解码 (Dean Edwards Packer)
# ══════════════════════════════════════════════════════════

def _unpack_js(packed: str) -> Optional[str]:
    """解码 eval(function(p,a,c,k,e,d){...}(...)) 格式的 JS"""
    m = re.search(
        r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)\s*\{.*?\}\s*\("
        r"'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\s*\.split\s*\(\s*'\|'\s*\)\s*,\s*0\s*,\s*\{\s*\}\s*\)\s*\)",
        packed, re.DOTALL
    )
    if not m:
        return None
    p, a, c, k = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).split('|')

    def _e(v):
        r = ''
        if v >= a:
            r = _e(v // a)
        mod = v % a
        r += chr(mod + 29) if mod > 35 else '0123456789abcdefghijklmnopqrstuvwxyz'[mod]
        return r

    d = {}
    for i in range(c - 1, -1, -1):
        key = _e(i)
        d[key] = k[i] if i < len(k) and k[i] else key

    code = p
    for i in range(c - 1, -1, -1):
        key = _e(i)
        if key in d:
            code = re.sub(r'\b' + re.escape(key) + r'\b', d[key], code)
    return code


def _extract_m3u8_from_html(html: str) -> list[str]:
    """从 HTML 中提取 m3u8 URL（直接引用 + 解码混淆 JS）"""
    urls = []
    seen = set()

    # 直接引用
    for m in re.finditer(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html):
        u = m.group(1).rstrip("'\"\\()")
        if u not in seen:
            seen.add(u)
            urls.append(u)

    # 解码 eval-packer 混淆的 JS
    for m in re.finditer(
        r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)\s*\{.*?\}\s*\("
        r"'.*?'\s*,\s*\d+\s*,\s*\d+\s*,\s*'.*?'\.split\('\|'\)\s*,\s*0\s*,\s*\{\s*\}\s*\)\s*\)",
        html, re.DOTALL
    ):
        decoded = _unpack_js(m.group(0))
        if not decoded:
            continue
        for u in re.finditer(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded):
            url = u.group(0).rstrip("'\"\\()")
            if url not in seen:
                seen.add(url)
                urls.append(url)
        # loadSource('...')
        for u in re.finditer(r"loadSource\s*\(\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", decoded):
            urls.append(u.group(1).rstrip("\\"))

    return urls


# ══════════════════════════════════════════════════════════
#  资源解析
# ══════════════════════════════════════════════════════════

def _classify(url: str, candidate_type: str = "") -> str:
    """根据 URL 扩展名分类"""
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
    return candidate_type or "其他"


def _extract_name(url: str) -> str:
    """从 URL 提取文件名"""
    parsed = urlparse(url)
    name = parsed.path.split("/")[-1]
    if not name or "." not in name:
        for part in parsed.query.split("&"):
            if part.startswith(("src=", "url=", "file=", "name=")):
                name = part.split("=", 1)[1].split("/")[-1]
                break
        if not name:
            name = "untitled"
    # URL 解码
    try:
        name = name.encode("latin1").decode("utf-8")
    except Exception:
        pass
    return name


def parse_resources(html: str, base_url: str, source_url: str = "") -> list[Resource]:
    """解析 HTML，提取所有可用资源"""
    resources = []
    seen_urls = set()
    soup = BeautifulSoup(html, "lxml")

    def _add(url, rtype):
        if not url or url.startswith(("data:", "mailto:", "javascript:", "#", "blob:")):
            return
        if "?url=" in url:
            # 提取包装 URL 中的真实 URL
            m = re.search(r'[?&]url=([^&]+)', url)
            if m:
                url = m.group(1)
        full = urljoin(base_url, url)
        if full in seen_urls:
            return
        seen_urls.add(full)
        if not rtype or rtype == "其他":
            rtype = _classify(full, rtype)
        name = _extract_name(full)
        resources.append(Resource(url=full, rtype=rtype, name=name, source=source_url))

    # ── 1. m3u8 HLS 流（优先，针对 ASMR 站点）────
    for url in _extract_m3u8_from_html(html):
        _add(url, "音频-HLS")

    # ── 2. <img> 标签（含懒加载属性全覆盖）────
    img_attrs = ["src", "data-src", "data-original", "data-actualsrc",
                  "data-lazy-src", "data-url", "data-img", "load-src",
                  "_src", "src2", "layz-src", "original"]
    for img in soup.select("img"):
        for attr in img_attrs:
            _add(img.get(attr) or "", "图片")
        # srcset 属性
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        if srcset:
            for part in srcset.split(","):
                url_part = part.strip().split()[0]
                if url_part:
                    _add(url_part, "图片")

    # ── 3. <video> / <audio> / <source> ──────────
    for tag_name, default_type in [("video", "视频"), ("audio", "音频")]:
        for el in soup.find_all(tag_name):
            _add(el.get("src") or "", default_type)
            _add(el.get("poster") or "", "图片")
            for src_el in el.find_all("source"):
                _add(src_el.get("src") or "", default_type)
            for attr in ["data-src", "data-url", "data-mp3", "data-audio",
                         "data-video", "data-source", "data-m4a"]:
                _add(el.get(attr) or "", default_type)

    # ── 4. <a> 直接音视频链接 ──────────────────────
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        ext = "." + lower.split(".")[-1].split("?")[0] if "." in lower else ""
        if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
            _add(href, _classify(href))
        elif ".m3u8" in lower:
            _add(href, "音频-HLS")

    # ── 5. CSS/JS ──────────────────────────────────
    for link in soup.select("link[rel='stylesheet']"):
        _add(link.get("href") or "", "样式")
    for script in soup.select("script[src]"):
        _add(script.get("src") or "", "脚本")

    # ── 6. <script> JSON 播放器配置 ────────────────
    audio_patterns = [
        r'["\'](?:m4a|mp3|mp4|oga|ogg)["\']\\s*:\\s*"([^"]+)"',
        r'["\']url["\']\\s*:\\s*"(https?://[^"]*?\.(?:mp3|m4a|wav|flac|ogg|aac|opus|mp4|webm|m3u8)[^"]*)"',
        r'["\']src["\']\\s*:\\s*"(https?://[^"]*?\.(?:mp3|m4a|wav|flac|mp4|webm|m3u8)[^"]*)"',
        r'["\']audio["\']\\s*:\\s*"([^"\']*?\.(?:mp3|m4a|wav|flac|ogg|aac|opus|m3u8)[^"\']*?)"',
        r'["\']sound["\']\\s*:\\s*"([^"\']*?\.(?:mp3|m4a|wav|flac|ogg|m3u8)[^"\']*?)"',
        r'["\']source["\']\\s*:\\s*"([^"\']*?\.(?:mp3|m4a|wav|flac|mp4|webm|m3u8)[^"\']*?)"',
    ]
    for script in soup.find_all("script"):
        text = script.string or ""
        if not text or len(text) < 20:
            continue
        for pat in audio_patterns:
            for m in re.finditer(pat, text, re.I):
                url = m.group(1).strip("'\"\\")
                _add(url, _classify(url))

    # ── 7. HTML 全文中音视频链接 ───────────────────
    for pat, rtype in [
        (r'(https?://[^\s"\'<>&]+\.(?:mp3|m4a|wav|flac|ogg|opus|aac|ape|wma)(?:\?[^\s"\'<>&]*)?)', "音频"),
        (r'(https?://[^\s"\'<>&]+\.(?:mp4|webm|mkv|avi|mov|flv|m4v)(?:\?[^\s"\'<>&]*)?)', "视频"),
    ]:
        for m in re.finditer(pat, html, re.I):
            _add(m.group(1).rstrip("'\"\\"), rtype)

    # ── 8. CSS 背景图 ──────────────────────────────
    for m in re.finditer(r'url\(\s*(["\']?)([^)]*?)\1\s*\)', html):
        raw = m.group(2).strip()
        if raw and raw.startswith("http") and not raw.startswith("data:"):
            _add(raw, "图片")

    # ── 9. <a> 普通文档链接 ────────────────────────
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        ext = "." + lower.split(".")[-1].split("?")[0] if "." in lower else ""
        if ext in DOC_EXTS and href not in seen_urls:
            _add(href, "文档")

    # ── 10. 时间轴章节（ASMR 站点等）─────────────────
    chapters = _extract_chapters(soup, html)
    if chapters:
        # 把章节信息附到 HLS 资源上
        for r in resources:
            if "HLS" in r.rtype or ".m3u8" in r.url:
                r.chapters = chapters
    if chapters:
        _log.info(f"[parse] 提取到 {len(chapters)} 个时间轴章节")

    _log.info(f"[parse] {base_url} -> {len(resources)} 资源 "
              f"(HLS:{sum(1 for r in resources if 'HLS' in r.rtype)}, "
              f"图:{sum(1 for r in resources if r.rtype=='图片')}, "
              f"音:{sum(1 for r in resources if '音频' in r.rtype)}, "
              f"视:{sum(1 for r in resources if r.rtype=='视频')})")
    return resources


def _extract_chapters(soup: BeautifulSoup, html: str) -> list[tuple[int, int, str]] | None:
    """从 ASMR 页面提取时间轴章节 [(start_sec, end_sec, title), ...]"""
    chapter_div = soup.find("div", id="chapter") or soup.find("div", class_="chapter")
    if not chapter_div:
        # 尝试找 tab_content 中的 chapter
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
        text = a.get_text(strip=True)
        # 去掉末尾时间戳
        text = re.sub(r'\s*\d{2}:\d{2}:\d{2}\s*$', '', text)
        title = text.strip()
        if not title:
            title = f"章节 {len(items)+1}"
        items.append((start, None, title))  # end 稍后推算

    if len(items) < 2:
        return None

    # 推算 end_sec（每个章节的结束时间 = 下一个章节的开始时间）
    result = []
    for i in range(len(items) - 1):
        result.append((items[i][0], items[i + 1][0], items[i][2]))
    # 最后一个章节用很大的值（到文件末尾）
    result.append((items[-1][0], items[-1][0] + 99999, items[-1][2]))
    return result


# ══════════════════════════════════════════════════════════
#  翻译工具（日/英 → 中文）
# ══════════════════════════════════════════════════════════

@lru_cache(maxsize=200)
def translate_to_zh(text: str) -> str:
    """翻译文本为中文，缓存结果"""
    if not text or not text.strip():
        return text
    # 检测日文：含假名 → 需翻译；含韩文 → 需翻译；纯中文 → 跳过
    has_kana = bool(re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    has_hangul = bool(re.search(r'[\uac00-\ud7af]', text))
    has_cjk = any('\u4e00' <= c <= '\u9fff' for c in text)
    # 只有汉字没有假名/韩文 → 可能是中文，跳过
    if has_cjk and not has_kana and not has_hangul:
        return text
    # 也无汉字 → 纯数字/英文，跳过
    if not has_cjk and not has_kana and not has_hangul:
        return text
    try:
        from deep_translator import GoogleTranslator
        src = 'ja' if has_kana else ('ko' if has_hangul else 'auto')
        result = GoogleTranslator(source=src, target='zh-CN').translate(text[:500])
        return result if result else text
    except Exception:
        return text


def translate_chapters(chapters: list) -> list:
    """翻译时间轴章节标题 [(start, end, 原题), ...] → [(start, end, 原题, 中译), ...]"""
    if not chapters:
        return chapters
    result = []
    for start, end, title in chapters:
        zh = translate_to_zh(title)
        result.append((start, end, title, zh if zh != title else ""))
    return result
