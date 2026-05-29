"""
asmr.one 站点 API 集成模块。

通过 asmr.one 公共 API 获取作品文件树，
递归提取音频、视频和字幕资源，无需解析 HTML。
"""

import logging
import re
from typing import Final

import requests

from core.constants import (
    USER_AGENTS,
    TIMEOUT,
    CONNECT_TIMEOUT,
    ASMR_API_WORK_INFO,
    ASMR_API_TRACKS,
)
from core.fetcher import make_session

_log = logging.getLogger("asmr_one")

ASMR_PATTERN: Final = re.compile(r'asmr\.one/work/(RJ\d+)', re.I)


def is_asmr_one(url: str) -> bool:
    """判断 URL 是否为 asmr.one 作品页。

    Args:
        url: 待检测的完整 URL。

    Returns:
        若 URL 匹配 asmr.one/work/RJxxxxxx 格式则返回 True。

    Example:
        >>> is_asmr_one("https://asmr.one/work/RJ01000000")
        True
        >>> is_asmr_one("https://example.com")
        False
    """
    return bool(ASMR_PATTERN.search(url))


def parse_asmr_one(url: str) -> list:
    """通过 asmr.one API 获取作品所有音视频和字幕资源。

    流程：
    1. 从 URL 提取 RJ 编号
    2. 调用 /api/workInfo/{RJ} 获取数字 work_id
    3. 调用 /api/tracks/{work_id} 获取完整文件树
    4. 递归遍历文件树，收集 audio / text 类型节点

    Args:
        url: asmr.one 作品页 URL（如 https://asmr.one/work/RJ01000000）。

    Returns:
        Resource 对象列表，包含所有提取到的音频和字幕资源。
        若 API 调用失败或作品不存在则返回空列表。
    """
    from core.parser import Resource

    match = ASMR_PATTERN.search(url)
    if not match:
        _log.warning(f"[asmr.one] URL 不匹配: {url}")
        return []

    rj = match.group(1)
    resources: list[Resource] = []
    sess = make_session()

    try:
        # 1. 获取作品元数据 → 拿到数字 ID
        info_r = sess.get(
            ASMR_API_WORK_INFO.format(rj),
            headers={"User-Agent": USER_AGENTS[0]},
            timeout=(CONNECT_TIMEOUT, TIMEOUT),
        )
        info_r.raise_for_status()
        work_id = info_r.json().get("id")
        if not work_id:
            _log.warning(f"[asmr.one] 未找到作品ID: {rj}")
            return []

        # 2. 获取文件树
        tracks_r = sess.get(
            ASMR_API_TRACKS.format(work_id),
            headers={"User-Agent": USER_AGENTS[0]},
            timeout=(CONNECT_TIMEOUT, TIMEOUT),
        )
        tracks_r.raise_for_status()
        tree = tracks_r.json()

        # 3. 递归遍历文件树
        def walk(nodes, prefix: str = "") -> None:
            """递归遍历 JSON 树节点，收集音频和字幕资源。"""
            if isinstance(nodes, list):
                for n in nodes:
                    walk(n, prefix)
            elif isinstance(nodes, dict):
                t = nodes.get("type", "")
                title = nodes.get("title", "unknown")
                path = (prefix + "/" + title) if prefix else title

                if t in {"audio", "video"}:
                    dl_url = nodes.get("mediaDownloadUrl", "")
                    stream_url = nodes.get("mediaStreamUrl", "")
                    media_url = dl_url or stream_url
                    if not media_url:
                        _log.warning(f"[asmr.one] 无下载链接: {title}")
                        return
                    from core.parser import classify
                    resources.append(Resource(
                        url=media_url, rtype=classify(media_url, "音频"),
                        name=path, source=url,
                    ))
                elif t == "text":
                    sub_url = nodes.get("mediaDownloadUrl", "")
                    if sub_url and title:
                        resources.append(Resource(
                            url=sub_url, rtype="字幕",
                            name=path, source=url,
                        ))
                elif t == "folder":
                    folder_name = nodes.get("title", "")
                    current_path = (
                        (prefix + "/" + folder_name) if prefix else folder_name
                    )
                    for child in nodes.get("children", []):
                        walk(child, current_path)

        walk(tree)
        _log.info(f"[asmr.one] {rj} → {len(resources)} 个资源")

    except requests.RequestException as e:
        _log.error(f"[asmr.one] 网络请求失败 {rj}: {e}")
    except (KeyError, ValueError, TypeError) as e:
        _log.error(f"[asmr.one] 数据解析失败 {rj}: {e}")
    except Exception as e:
        _log.error(f"[asmr.one] 未知错误 {rj}: {e}")
    finally:
        try:
            sess.close()
        except Exception:
            pass

    return resources
