"""
HTTP 抓取模块 — Session 管理 + 页面下载 + 多 URL 并发。

统一管理 HTTP 连接池、重试策略和请求头，避免各模块各自创建 Session。
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.constants import (
    USER_AGENTS,
    TIMEOUT,
    CONNECT_TIMEOUT,
    MAX_RETRIES,
    MAX_FETCH_WORKERS,
)
from core.parser import parse_resources, Resource

_log = logging.getLogger("fetcher")


def make_session() -> requests.Session:
    """创建带重试策略和连接池复用的 Session。

    自动处理 5xx / 429 状态码的重试，指数退避（backoff_factor=1.0）。
    自动读取代理配置。

    Returns:
        配置好 Retry + HTTPAdapter + 代理的 requests.Session 实例。
    """
    from core.config import get_proxy

    s = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES,
        redirect=3,
        status_forcelist={500, 502, 503, 504, 429},
        backoff_factor=1.0,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)

    # 代理
    proxies = get_proxy()
    if proxies:
        s.proxies.update(proxies)

    return s


def fetch_html(url: str) -> str:
    """下载页面 HTML 源码。

    asmr.one 的 URL 无需 HTML——该方法返回空字符串，
    由 parse_resources 直接调用 API。

    Args:
        url: 目标页面 URL。

    Returns:
        页面 HTML 字符串（UTF-8 解码）。

    Raises:
        requests.HTTPError: HTTP 状态码非 2xx 时抛出。
        requests.ConnectionError: 连接失败时抛出。
    """
    from core.asmr_one import is_asmr_one

    if is_asmr_one(url):
        return ""  # asmr.one 走 API，不需要 HTML

    s = make_session()
    try:
        headers = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        }
        resp = s.get(
            url,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, TIMEOUT),
            allow_redirects=True,
        )
        resp.raise_for_status()

        # 编码推断：优先 apparent_encoding，fallback UTF-8
        html = resp.text
        if resp.apparent_encoding and resp.apparent_encoding.lower() != "utf-8":
            try:
                html = resp.content.decode(resp.apparent_encoding)
            except (UnicodeDecodeError, LookupError):
                html = resp.content.decode("utf-8", errors="replace")
        return html
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def fetch_all_urls(urls: list[str], max_workers: int = MAX_FETCH_WORKERS) -> list[Resource]:
    """并发抓取多个 URL，汇总所有资源到一个统一列表（自动去重）。

    适用于用户一次粘贴多个页面地址的场景。每个 URL 独立抓取 + 解析，
    结果按资源 URL 去重后合并返回。

    Args:
        urls: 目标页面 URL 列表。
        max_workers: 最大并发线程数（默认 6，上限 8，避免被反爬）。

    Returns:
        去重后的 Resource 列表。

    Example:
        >>> resources = fetch_all_urls(["https://site1.com", "https://site2.com"])
        >>> len(resources)
        42
    """
    all_resources: list[Resource] = []
    seen_urls: set[str] = set()

    def _fetch_one(url: str) -> list[Resource]:
        try:
            html = fetch_html(url)
            return parse_resources(html, url, source_url=url)
        except Exception as e:
            _log.warning(f"[fetch_all] {url[:60]} 抓取失败: {e}")
            return []

    workers = min(max_workers, len(urls), 8)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, u): u for u in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                resources = future.result()
                _log.info(f"[fetch_all] {url[:60]} -> {len(resources)} 资源")
                for r in resources:
                    if r.url not in seen_urls:
                        seen_urls.add(r.url)
                        all_resources.append(r)
            except Exception as e:
                _log.warning(f"[fetch_all] {url[:60]} 并发异常: {e}")

    _log.info(f"[fetch_all] 总计 {len(all_resources)} 资源（{len(urls)} 个 URL）")
    return all_resources