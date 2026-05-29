"""
统一常量定义模块。

将散落在 scraper.py / downloader.py 中的常量集中管理，避免魔法数字和重复定义。
"""

from typing import Final

# ── 版本号 ─────────────────────────────────────────────
APP_VERSION: Final[str] = "1.1.8"
APP_NAME: Final[str] = "Web Resource Crawler"

# ── HTTP 请求 ──────────────────────────────────────────

USER_AGENTS: Final[list[str]] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

TIMEOUT: Final[int] = 10
CONNECT_TIMEOUT: Final[int] = 5
MAX_RETRIES: Final[int] = 3
DOWNLOAD_TIMEOUT: Final[int] = 60       # 大文件下载读超时（原 30s 太短）
DOWNLOAD_CONNECT_TIMEOUT: Final[int] = 10

# ── 并发控制 ──────────────────────────────────────────
MAX_FETCH_WORKERS: Final[int] = 6
MAX_DOWNLOAD_WORKERS: Final[int] = 16    # 普通文件并发数
HLS_DOWNLOAD_WORKERS: Final[int] = 24     # HLS 分片并发数
HLS_DOWNLOAD_WORKER_LIMIT: Final[int] = 48  # HLS 分片并发上限

# ── 文件扩展名分类 ────────────────────────────────────
IMG_EXTS: Final[set[str]] = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif"}
AUDIO_EXTS: Final[set[str]] = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".opus", ".wma", ".ape"}
VIDEO_EXTS: Final[set[str]] = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".m4v", ".ts"}
DOC_EXTS: Final[set[str]] = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".7z"}
CSS_EXTS: Final[set[str]] = {".css"}
JS_EXTS: Final[set[str]] = {".js"}
SUBTITLE_EXTS: Final[set[str]] = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".lrc"}

# ── 下载器 ────────────────────────────────────────────
CHUNK_SIZE: Final[int] = 65536              # scraper 侧
DOWNLOAD_CHUNK_SIZE: Final[int] = 1048576   # downloader 侧 (1MB)

# ── asmr.one ──────────────────────────────────────────
ASMR_ONE_PATTERN_STR: Final[str] = r'asmr\.one/work/(RJ\d+)'
ASMR_API_WORK_INFO: Final[str] = "https://api.asmr.one/api/workInfo/{}"
ASMR_API_TRACKS: Final[str] = "https://api.asmr.one/api/tracks/{}"

# ── 默认用户代理 (downloader 用) ─────────────────────
DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
)

# ── 停止标记 ───────────────────────────────────────────
STOPPED_MARKER: Final[str] = "__STOPPED__"
