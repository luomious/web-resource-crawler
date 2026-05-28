# -*- coding: utf-8 -*-
'''
Core package — Web Resource Crawler 业务逻辑层。

子模块:
    constants   — 全局常量（User-Agent / 扩展名 / 超时等）
    unpacker    — JS 混淆解码（Dean Edwards Packer）
    fetcher     — HTTP 抓取 + 多 URL 并发
    parser      — HTML 资源解析 + Resource 数据类
    asmr_one    — asmr.one API 集成
    translator  — 翻译工具
    scraper     — 向后兼容层（重导出，新代码请直接导入子模块）
    downloader  — 并发下载器 + HLS 流媒体
    config      — 统一配置管理（JSON 持久化）
    controller  — MVC 控制器（协调业务逻辑）
'''

# -- 精确重导出常用符号（不再 from core.scraper import *）--------
from core.constants import (
    USER_AGENTS, TIMEOUT, CONNECT_TIMEOUT, MAX_RETRIES,
    IMG_EXTS, AUDIO_EXTS, VIDEO_EXTS, DOC_EXTS,
    CSS_EXTS, JS_EXTS, CHUNK_SIZE, MAX_FETCH_WORKERS,
    MAX_DOWNLOAD_WORKERS, HLS_DOWNLOAD_WORKERS, HLS_DOWNLOAD_WORKER_LIMIT,
    DOWNLOAD_TIMEOUT,
    DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_CHUNK_SIZE,
    DEFAULT_USER_AGENT, STOPPED_MARKER,
    ASMR_API_WORK_INFO, ASMR_API_TRACKS,
)
from core.parser import Resource, classify, extract_name, parse_resources
from core.unpacker import unpack_js, extract_m3u8_from_html
from core.fetcher import make_session, fetch_html, fetch_all_urls
from core.asmr_one import is_asmr_one, parse_asmr_one
from core.translator import translate_to_zh, translate_chapters
from core.config import (
    get_config_int, load_config, save_config, load_history, save_history,
    get_proxy,
)

__all__ = [
    'Resource', 'parse_resources', 'fetch_html', 'fetch_all_urls',
    'classify', 'extract_name', 'unpack_js', 'extract_m3u8_from_html',
    'is_asmr_one', 'parse_asmr_one', 'make_session',
    'translate_to_zh', 'translate_chapters',
    'get_config_int', 'load_config', 'save_config', 'load_history', 'save_history',
    'get_proxy',
    'USER_AGENTS', 'IMG_EXTS', 'AUDIO_EXTS', 'VIDEO_EXTS',
    'DOC_EXTS', 'CSS_EXTS', 'JS_EXTS',
    'TIMEOUT', 'CONNECT_TIMEOUT', 'MAX_RETRIES',
    'CHUNK_SIZE', 'MAX_FETCH_WORKERS', 'MAX_DOWNLOAD_WORKERS',
    'HLS_DOWNLOAD_WORKERS', 'HLS_DOWNLOAD_WORKER_LIMIT',
    'DOWNLOAD_TIMEOUT', 'DOWNLOAD_CONNECT_TIMEOUT',
    'DOWNLOAD_CHUNK_SIZE', 'DEFAULT_USER_AGENT', 'STOPPED_MARKER',
    'APP_VERSION', 'APP_NAME',
    'ASMR_API_WORK_INFO', 'ASMR_API_TRACKS',
]
