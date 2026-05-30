'''
MVC 控制器模块 — 协调 GUI 和核心业务逻辑。

职责:
    - URL 规范化（格式校验、协议补全、去重）
    - 抓取流程编排（fetch_html → parse_resources）
    - 下载状态管理（成功/失败/停止分类）

此类不依赖任何 GUI 框架（PyQt5/Tkinter），可独立测试。
'''

import re
import logging
from typing import Optional

from core.fetcher import fetch_html
from core.parser import parse_resources, Resource
from core.asmr_one import is_asmr_one

_log = logging.getLogger('controller')

# 下载停止标记（与 downloader.STOPPED_MARKER 一致）
STOPPED_MARKER: str = '__STOPPED__'


def normalize_urls(raw_text: str) -> list[str]:
    '''从用户输入的原始文本中提取并规范化 URL。

    支持逗号、换行、分号分隔的多个 URL；自动补全 https:// 协议。

    Args:
        raw_text: 用户输入的原始文本。

    Returns:
        规范化后的 URL 列表（已去重），空文本返回空列表。

    Example:
        >>> normalize_urls('example.com, https://site.com')
        ['https://example.com', 'https://site.com']
    '''
    if not raw_text.strip():
        return []

    candidates = [u.strip() for u in re.split(r'[,\n;]+', raw_text) if u.strip()]

    seen: set[str] = set()
    result: list[str] = []
    for u in candidates:
        if not u.startswith(('http://', 'https://')):
            u = 'https://' + u
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def fetch_resources(urls: list[str], status_cb=None) -> list[Resource]:
    '''批量抓取网页的资源列表。

    对每个 URL 执行 fetch_html + parse_resources，汇总去重后返回。

    Args:
        urls: 目标页面 URL 列表。
        status_cb: 可选的状态回调函数，接收字符串消息。

    Returns:
        Resource 对象列表。单个 URL 失败不影响其他 URL 的结果。

    Example:
        >>> res = fetch_resources(['https://example.com'])
        >>> len(res) >= 0
        True
    '''
    all_resources: list[Resource] = []
    seen_urls: set[str] = set()

    for i, url in enumerate(urls):
        try:
            if status_cb:
                status_cb(f'正在加载页面 ({i+1}/{len(urls)})…')
            html: str = fetch_html(url)
            if status_cb:
                status_cb(f'正在解析资源 ({i+1}/{len(urls)})…')
            parsed: list[Resource] = parse_resources(html, url, source_url=url)
            count = 0
            for r in parsed:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_resources.append(r)
                    count += 1
            if status_cb:
                status_cb(f'已找到 {len(all_resources)} 个资源 ({i+1}/{len(urls)})…')
        except Exception as e:
            _log.warning(f'[controller] {url[:60]} 抓取失败: {e}')

    return all_resources


def classify_download_results(
    results: list[tuple[str, str]],
) -> tuple[list[tuple[str, str, int]], list[tuple[str, str]], list[tuple[str, str]]]:
    '''将下载结果分类为成功 / 失败 / 停止三组。

    依赖：
        - 成功的结果中，第二项是本地文件路径（Path.exists() 为 True）
        - 被停止的结果，第二项为 STOPPED_MARKER

    Args:
        results: download_all() 的返回值 [(url, path_or_error), ...]。

    Returns:
        (ok_list, fail_list, stop_list) 三元组。
        ok_list 每项为 (url, path, filesize_bytes)。
        fail_list 每项为 (url, error_message)。
        stop_list 每项为 (url, STOPPED_MARKER)。
    '''
    from pathlib import Path

    ok: list[tuple[str, str, int]] = []
    fail: list[tuple[str, str]] = []
    stopped: list[tuple[str, str]] = []

    for url, result in results:
        if result == STOPPED_MARKER:
            stopped.append((url, result))
        elif result and Path(result).exists():
            try:
                sz: int = Path(result).stat().st_size
                ok.append((url, result, sz))
            except OSError:
                ok.append((url, result, 0))
        else:
            fail.append((url, result or '下载失败'))

    return ok, fail, stopped


def get_label_for_urls(urls: list[str]) -> str:
    '''根据 URL 列表生成显示标签。

    Args:
        urls: URL 列表。

    Returns:
        单 URL 返回 URL 本身，多 URL 返回 'N 个网页'。
    '''
    if len(urls) == 1:
        return urls[0]
    return f'{len(urls)} 个网页'
