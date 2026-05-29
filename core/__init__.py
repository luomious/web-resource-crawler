# -*- coding: utf-8 -*-
"""
Core package — Web Resource Crawler 业务逻辑层。

子模块:
    constants   — 全局常量（User-Agent / 扩展名 / 超时等）
    unpacker    — JS 混淆解码（Dean Edwards Packer）
    fetcher     — HTTP 抓取 + 多 URL 并发
    parser      — HTML 资源解析 + Resource 数据类
    asmr_one    — asmr.one API 集成
    translator  — 翻译工具
    downloader  — 并发下载器 + HLS 流媒体
    config      — 统一配置管理（JSON 持久化）
    controller  — MVC 控制器（协调业务逻辑）

导入约定：新代码直接从子模块导入，例如：
    from core.parser import Resource, parse_resources
    from core.fetcher import fetch_html
"""

# 仅保留 constants 子模块的包级访问（测试用 from core import constants）
from core import constants  # noqa: F401

__all__ = ["constants"]
