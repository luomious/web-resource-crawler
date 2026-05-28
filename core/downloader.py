"""
并发下载器 — 普通文件 + HLS 流媒体，支持暂停/取消。

优化点（相比旧版）：
1. Session 全局复用 — download_all() 创建共享 Session，避免每次下载重新握手
2. 分离线程池 — HLS 任务独立线程池，不阻塞普通文件下载
3. 断点续传 — 支持 Range 头，大文件中断后从断点继续
4. HLS 小分片直接读 content — 不用 stream+iter_content，减少系统调用
5. 快速合并 — 用 os.sendfile 替代 shutil.copyfileobj
6. 超时优化 — 大文件用更长的读超时
7. 保留目录结构 — asmr.one 资源 name 含路径时，在 save_dir 下创建子目录

公共 API:
    download_file(url, save_dir, stop_flag, session, output_path) -> (local_path, error)
    download_hls(m3u8_url, output_path, stop_flag, progress_cb, max_workers) -> (path, error)
    download_all(resources, save_dir, stop_flag, progress_cb, max_workers) -> [(url, result), ...]
"""

import os
import re
import logging
import threading
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.constants import (
    DOWNLOAD_TIMEOUT as TIMEOUT,
    DOWNLOAD_CONNECT_TIMEOUT as CONNECT_TIMEOUT,
    MAX_DOWNLOAD_WORKERS as MAX_WORKERS,
    HLS_DOWNLOAD_WORKERS,
    HLS_DOWNLOAD_WORKER_LIMIT,
    DOWNLOAD_CHUNK_SIZE as CHUNK_SIZE,
    DEFAULT_USER_AGENT as _USER_AGENT,
    STOPPED_MARKER,
)

_log = logging.getLogger('downloader')

_RETRY_TOTAL: int = 3


# ---- 内部工具函数 -----------------------------------------------


def _make_session(pool_connections: int = 32, pool_maxsize: int = 64) -> requests.Session:
    """创建带 Retry 策略的 Session（连接池复用 + 代理）。"""
    from core.config import get_proxy

    s = requests.Session()
    retry = Retry(
        total=_RETRY_TOTAL,
        connect=_RETRY_TOTAL,
        read=_RETRY_TOTAL,
        redirect=3,
        status_forcelist={500, 502, 503, 504, 429},
        backoff_factor=0.5,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    s.mount('https://', adapter)
    s.mount('http://', adapter)

    # 代理
    proxies = get_proxy()
    if proxies:
        s.proxies.update(proxies)

    return s


def _clamp_workers(value: Optional[int], default: int, upper: int) -> int:
    """将并发数限制在可控范围内。"""
    try:
        workers = int(value) if value is not None else default
    except (TypeError, ValueError):
        workers = default
    return max(1, min(workers, upper))


def _headers(url: str = '') -> dict[str, str]:
    """构建统一的 HTTP 请求头。"""
    return {
        'User-Agent': _USER_AGENT,
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': url or '',
    }


def _safe_path(name: str) -> Path:
    """将资源 name 转为安全的相对路径，保留目录层级。

    - '文件夹/子文件夹/文件.mp4' → Path('文件夹/子文件夹/文件.mp4')
    - '文件.mp4' → Path('文件.mp4')
    - 只删除 Windows 不允许的字符（: * ? " < > |），保留 / 作为目录分隔符
    - 去除首尾空格和点号（Windows 不允许尾随点号）
    """
    # 先把 / 保留为占位符，清理其他非法字符，再恢复
    SEP_PLACEHOLDER = '\x00SEP\x00'
    parts = name.split('/')
    safe_parts = []
    for part in parts:
        # 清理非法字符（保留 / 以外的路径分隔符用上面的 split 处理了）
        cleaned = re.sub(r'[:*?"<>|]', '', part.strip().rstrip('.'))
        if cleaned:
            safe_parts.append(cleaned)
    return Path('/'.join(safe_parts)) if safe_parts else Path('download')


def _cleanup_hls_tmp_dir(tmp_dir: Path, total: int) -> None:
    """清理本次 HLS 下载生成的临时分片。"""
    for i in range(total):
        (tmp_dir / f'{i:06d}.ts').unlink(missing_ok=True)
    try:
        tmp_dir.rmdir()
    except OSError:
        _log.warning(f'[HLS] 临时目录非空，保留: {tmp_dir}')


def _merge_ts_segments(tmp_dir: Path, output_path: Path, total: int, stop_flag: Optional[threading.Event] = None) -> None:
    """快速合并 TS 分片。

    优先使用 os.sendfile（零拷贝），fallback 到普通读写。
    """
    if stop_flag and stop_flag.is_set():
        return

    try:
        with open(output_path, 'wb') as out:
            out_fd = out.fileno()
            for i in range(total):
                if stop_flag and stop_flag.is_set():
                    return
                seg = tmp_dir / f'{i:06d}.ts'
                if not seg.exists():
                    continue
                with open(seg, 'rb') as sf:
                    in_fd = sf.fileno()
                    remaining = os.fstat(in_fd).st_size
                    offset = 0
                    while remaining > 0:
                        sent = os.sendfile(out_fd, in_fd, offset, remaining)
                        if sent == 0:
                            break
                        offset += sent
                        remaining -= sent
    except (OSError, AttributeError):
        import shutil
        with open(output_path, 'wb') as out:
            for i in range(total):
                if stop_flag and stop_flag.is_set():
                    return
                seg = tmp_dir / f'{i:06d}.ts'
                if seg.exists():
                    with open(seg, 'rb') as sf:
                        shutil.copyfileobj(sf, out)


def _ffmpeg_available() -> bool:
    """检测系统是否安装了 ffmpeg。"""
    import shutil as _shutil
    return _shutil.which('ffmpeg') is not None


def _remux_with_ffmpeg(
    ts_path: Path,
    output_path: Path,
    stop_flag: Optional[threading.Event] = None,
) -> bool:
    """使用 ffmpeg 将 TS 转封装为 MP4/M4A。

    不重新编码（-c copy），仅更换容器格式，速度极快。

    Args:
        ts_path: 源 TS 文件路径。
        output_path: 目标 MP4/M4A 文件路径。
        stop_flag: 停止信号。

    Returns:
        True 转封装成功，False 失败或 ffmpeg 不可用。
    """
    if not _ffmpeg_available():
        return False

    import subprocess
    try:
        cmd = [
            'ffmpeg', '-y',
            '-i', str(ts_path),
            '-c', 'copy',
            '-movflags', '+faststart',
            str(output_path),
        ]
        result = subprocess.run(
            cmd,
            timeout=120,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            # 转封装成功，删除原始 TS
            ts_path.unlink(missing_ok=True)
            return True
        else:
            _log.warning(f'[ffmpeg] 转封装失败: {result.stderr.decode("utf-8", errors="replace")[:200]}')
            # 清理失败输出
            output_path.unlink(missing_ok=True)
            return False
    except subprocess.TimeoutExpired:
        _log.warning('[ffmpeg] 转封装超时')
        output_path.unlink(missing_ok=True)
        return False
    except Exception as e:
        _log.warning(f'[ffmpeg] 转封装异常: {e}')
        output_path.unlink(missing_ok=True)
        return False


# ---- 普通文件下载 ------------------------------------------------


def download_file(
    url: str,
    save_dir: Path,
    stop_flag: Optional[threading.Event] = None,
    session: Optional[requests.Session] = None,
    output_path: Optional[Path] = None,
) -> tuple[str, str]:
    """下载普通文件，支持断点续传和共享 Session。

    Args:
        url: 文件下载地址。
        save_dir: 保存目录。
        stop_flag: 停止信号。
        session: 共享的 requests.Session（如果不传则创建新的）。
        output_path: 指定完整输出路径（含文件名和子目录）。
                     若为 None，则从 URL 提取文件名保存在 save_dir 下。

    Returns:
        (本地路径, '') 成功；('', STOPPED_MARKER) 被停止；('', 错误消息) 失败。
    """
    if output_path is not None:
        output = output_path
    else:
        name: str = url.split('/')[-1].split('?')[0] or 'download'
        safe_name: str = re.sub(r'[\\/:*?\"<>|]', '', name)
        output: Path = save_dir / safe_name

    # 确保父目录存在
    output.parent.mkdir(parents=True, exist_ok=True)

    own_session = session is None
    if own_session:
        session = _make_session()

    try:
        # 断点续传：检查已有文件大小
        existing_size: int = 0
        headers = _headers(url)
        if output.exists():
            existing_size = output.stat().st_size
            if existing_size > 0:
                headers['Range'] = f'bytes={existing_size}-'

        r = session.get(
            url,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, TIMEOUT),
            stream=True,
        )

        # 服务器不支持 Range 或返回 200（完整文件）→ 重新下载
        if r.status_code == 200:
            existing_size = 0
            mode = 'wb'
        elif r.status_code == 206:
            mode = 'ab'
            _log.info(f'[download] 断点续传 {output.name} 从 {existing_size} 字节继续')
        else:
            r.raise_for_status()
            mode = 'wb'

        with open(output, mode) as f:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if stop_flag and stop_flag.is_set():
                    r.close()
                    return '', STOPPED_MARKER
                if chunk:
                    f.write(chunk)
        return str(output), ''

    except Exception as e:
        _log.warning(f'[download] {url[:60]} 下载失败: {e}')
        if output.exists() and output.stat().st_size < 1024:
            output.unlink(missing_ok=True)
        return '', str(e)
    finally:
        if own_session:
            session.close()


# ---- HLS 流媒体 ------------------------------------------------


def _parse_m3u8(m3u8_url: str, session: Optional[requests.Session] = None) -> list[str]:
    """解析 m3u8 播放列表，获取所有 TS 分片 URL。"""
    own_session = session is None
    if own_session:
        session = _make_session()
    try:
        r = session.get(
            m3u8_url,
            headers=_headers(),
            timeout=(CONNECT_TIMEOUT, TIMEOUT),
        )
        r.raise_for_status()
        lines = [
            l.strip() for l in r.text.splitlines()
            if l.strip() and not l.startswith('#')
        ]
    except Exception as e:
        _log.warning(f'[m3u8] 解析失败: {e}')
        return []
    finally:
        if own_session:
            session.close()
    return [urljoin(m3u8_url, l) for l in lines]


def download_hls(
    m3u8_url: str,
    output_path: Path,
    stop_flag: Optional[threading.Event] = None,
    progress_cb: Optional[Callable] = None,
    max_workers: Optional[int] = None,
    session: Optional[requests.Session] = None,
    is_audio: bool = False,
) -> tuple[str, str]:
    """下载 HLS 流并合并为单个 TS 文件。"""
    try:
        segments = _parse_m3u8(m3u8_url, session=session)
        if not segments:
            return '', 'm3u8 无分片'

        total: int = len(segments)
        _log.info(f'[HLS] {m3u8_url} -> {total} 分片')

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir: Path = output_path.parent / f'._hls_{output_path.stem}'
        tmp_dir.mkdir(parents=True, exist_ok=True)

        failed: int = 0
        stopped: bool = False
        workers: int = _clamp_workers(
            max_workers,
            HLS_DOWNLOAD_WORKERS,
            HLS_DOWNLOAD_WORKER_LIMIT,
        )

        done_counter: dict[str, int | threading.Lock] = {
            'done': 0,
            'lock': threading.Lock(),
        }

        thread_local = threading.local()
        sessions: list[requests.Session] = []
        sessions_lock = threading.Lock()

        def _thread_session() -> requests.Session:
            s = getattr(thread_local, 'session', None)
            if s is None:
                s = _make_session(pool_connections=8, pool_maxsize=workers)
                thread_local.session = s
                with sessions_lock:
                    sessions.append(s)
            return s

        def _fetch(seg_info: tuple[int, str]) -> tuple[int, bool]:
            idx, url = seg_info
            if stop_flag and stop_flag.is_set():
                return idx, False
            seg_path: Path = tmp_dir / f'{idx:06d}.ts'

            if seg_path.exists() and seg_path.stat().st_size > 0:
                return idx, True

            sess = _thread_session()
            try:
                r = sess.get(
                    url,
                    headers=_headers(url),
                    timeout=(CONNECT_TIMEOUT, 15),
                )
                r.raise_for_status()

                content_length = int(r.headers.get('Content-Length', 0))
                if content_length > 0 and content_length <= 2 * CHUNK_SIZE:
                    with open(seg_path, 'wb') as f:
                        f.write(r.content)
                else:
                    with open(seg_path, 'wb') as f:
                        for c in r.iter_content(chunk_size=CHUNK_SIZE):
                            if stop_flag and stop_flag.is_set():
                                r.close()
                                return idx, False
                            if c:
                                f.write(c)
                return idx, True

            except Exception as exc:
                _log.warning(f'[HLS] 分片 {idx} 失败: {exc}')
                return idx, False

        seg_args: list[tuple[int, str]] = list(enumerate(segments))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_fetch, sa): sa for sa in seg_args}
                for future in as_completed(futures):
                    idx, ok = future.result()
                    if not ok and stop_flag and stop_flag.is_set():
                        stopped = True
                    elif not ok:
                        failed += 1
                    if progress_cb:
                        with done_counter['lock']:
                            done_counter['done'] += 1
                            done = done_counter['done']
                        progress_cb(total, done, f'分片 {done}/{total}')
        finally:
            with sessions_lock:
                sessions_to_close = list(sessions)
                sessions.clear()
            for s in sessions_to_close:
                s.close()

        if stopped:
            _cleanup_hls_tmp_dir(tmp_dir, total)
            return '', STOPPED_MARKER

        if failed / total > 0.3:
            _cleanup_hls_tmp_dir(tmp_dir, total)
            return '', f'失败分片过多 ({failed}/{total})'

        if progress_cb:
            progress_cb(total, total, '合并中...')

        _merge_ts_segments(tmp_dir, output_path, total, stop_flag)

        if stop_flag and stop_flag.is_set():
            _cleanup_hls_tmp_dir(tmp_dir, total)
            output_path.unlink(missing_ok=True)
            return '', STOPPED_MARKER

        _cleanup_hls_tmp_dir(tmp_dir, total)

        # 尝试 ffmpeg 转封装（TS → MP4/M4A）
        final_path = output_path
        if _ffmpeg_available():
            ext = '.m4a' if is_audio else '.mp4'
            remuxed = output_path.with_suffix(ext)
            if progress_cb:
                progress_cb(total, total, '转封装中...')
            if _remux_with_ffmpeg(output_path, remuxed, stop_flag):
                final_path = remuxed
                size_mb = final_path.stat().st_size / 1024 / 1024
                _log.info(f'[HLS] 转封装完成: {final_path} ({size_mb:.1f}MB)')
            else:
                size_mb = output_path.stat().st_size / 1024 / 1024
                _log.info(f'[HLS] 转封装失败，保留 TS: {output_path} ({size_mb:.1f}MB)')
        else:
            size_mb = output_path.stat().st_size / 1024 / 1024
            _log.info(f'[HLS] 完成: {output_path} ({size_mb:.1f}MB)')

        return str(final_path), ''

    except Exception as e:
        _log.error(f'[HLS] 下载异常: {e}')
        return '', str(e)


# ---- 批量下载 --------------------------------------------------


def download_all(
    resources: list,
    save_dir: Path,
    stop_flag: Optional[threading.Event] = None,
    progress_cb: Optional[Callable] = None,
    max_workers: Optional[int] = None,
    hls_max_workers: Optional[int] = None,
) -> list[tuple[str, str]]:
    """多资源并行下载，HLS 和普通文件分离调度。

    优化：
    - 创建共享 Session，普通文件下载复用连接池
    - HLS 任务独立线程池，不阻塞普通文件
    - 已存在的文件自动跳过（不重复下载）
    - 保留 asmr.one 资源的目录结构（name 中的 / 转为子目录）
    """
    total: int = len(resources)
    workers: int = _clamp_workers(max_workers, MAX_WORKERS, 32)
    counter: dict = {'done': 0, 'lock': threading.Lock()}
    results_dict: dict[int, tuple[str, str]] = {}

    hls_items: list[tuple[int, object]] = []
    normal_items: list[tuple[int, object]] = []

    for i, r in enumerate(resources):
        if 'HLS' in getattr(r, 'rtype', '') or '.m3u8' in getattr(r, 'url', ''):
            hls_items.append((i, r))
        else:
            normal_items.append((i, r))

    shared_session = _make_session(pool_connections=workers, pool_maxsize=workers * 2)

    def _inc_done() -> int:
        with counter['lock']:
            counter['done'] += 1
            return counter['done']

    def _do_hls(idx: int, r) -> None:
        if stop_flag and stop_flag.is_set():
            results_dict[idx] = (r.url, STOPPED_MARKER)
            _inc_done()
            return

        # 保留目录结构：name 中的 / → 子目录
        rel_path: Path = _safe_path(r.name)
        # HLS 输出改 .ts 扩展名
        if rel_path.suffix == '.m3u8':
            rel_path = rel_path.with_suffix('.ts')
        output: Path = save_dir / rel_path

        if progress_cb:
            progress_cb(total, counter['done'], f'HLS: {rel_path}')

        path, err = download_hls(
            r.url,
            output,
            stop_flag=stop_flag,
            max_workers=hls_max_workers,
            session=shared_session,
            is_audio=(r.rtype == "\u97f3\u9891"),
        )
        if err == STOPPED_MARKER:
            results_dict[idx] = (r.url, STOPPED_MARKER)
        elif not err:
            results_dict[idx] = (r.url, path)
            sz_mb: float = Path(path).stat().st_size / 1024 / 1024
            if progress_cb:
                progress_cb(total, _inc_done(), f'OK: {rel_path} ({sz_mb:.1f}MB)')
        else:
            results_dict[idx] = (r.url, err)
            _inc_done()

    def _do_normal(idx: int, r) -> None:
        if stop_flag and stop_flag.is_set():
            results_dict[idx] = (r.url, STOPPED_MARKER)
            _inc_done()
            return

        # 保留目录结构：name 中的 / → 子目录
        rel_path: Path = _safe_path(getattr(r, 'name', 'download'))
        output: Path = save_dir / rel_path

        # 跳过已存在的文件（避免重复下载）
        if output.exists() and output.stat().st_size > 0:
            results_dict[idx] = (r.url, str(output))
            done: int = _inc_done()
            if progress_cb:
                progress_cb(total, done, f'跳过: {str(rel_path)[:30]}')
            return

        # 传入指定输出路径，保留目录结构
        path, err = download_file(
            r.url, save_dir, stop_flag=stop_flag,
            session=shared_session, output_path=output,
        )
        results_dict[idx] = (r.url, path if not err else err)
        done: int = _inc_done()
        if progress_cb:
            progress_cb(total, done, str(rel_path)[:45])

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='dl') as normal_pool, \
             ThreadPoolExecutor(max_workers=min(len(hls_items), 4), thread_name_prefix='hls') as hls_pool:

            normal_futures = []
            hls_futures = []

            for idx, r in hls_items:
                hls_futures.append(hls_pool.submit(_do_hls, idx, r))
            for idx, r in normal_items:
                normal_futures.append(normal_pool.submit(_do_normal, idx, r))

            for f in as_completed(normal_futures + hls_futures):
                try:
                    f.result()
                except Exception as e:
                    _log.warning(f'[download_all] 任务异常: {e}')
                if stop_flag and stop_flag.is_set():
                    break

    finally:
        shared_session.close()

    return [
        results_dict.get(i, (resources[i].url, '未完成'))
        for i in range(total)
    ]
