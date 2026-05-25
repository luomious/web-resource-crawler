"""
并发下载器 — 普通文件 + HLS 流媒体，支持暂停/取消
"""
import re
import shutil
import logging
import threading
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

_log = logging.getLogger("downloader")

TIMEOUT = 30
CONNECT_TIMEOUT = 8
MAX_WORKERS = 16
CHUNK_SIZE = 524288  # 512KB

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
_STOPPED_MARKER = "__STOPPED__"


def _headers(url: str = "") -> dict:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": url or "",
    }


# ══════════════════════════════════════════════════════════
#  普通文件下载
# ══════════════════════════════════════════════════════════

def download_file(url: str, save_dir: Path,
                  stop_flag: threading.Event = None) -> tuple[str, str]:
    """下载普通文件 → (本地路径, 错误或空)"""
    name = url.split("/")[-1].split("?")[0] or "download"
    safe_name = re.sub(r'[\\/:*?"<>|]', '', name)
    output = save_dir / safe_name

    try:
        r = requests.get(url, headers=_headers(url),
                         timeout=(CONNECT_TIMEOUT, TIMEOUT), stream=True)
        r.raise_for_status()
        with open(output, "wb") as f:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if stop_flag and stop_flag.is_set():
                    r.close()
                    output.unlink(missing_ok=True)
                    return "", _STOPPED_MARKER
                if chunk:
                    f.write(chunk)
        return str(output), ""
    except Exception as e:
        return "", str(e)


# ══════════════════════════════════════════════════════════
#  HLS 流媒体下载 + 合并
# ══════════════════════════════════════════════════════════

def _parse_m3u8(m3u8_url: str) -> list[str]:
    """解析 m3u8 获取 TS 分片列表"""
    try:
        r = requests.get(m3u8_url, headers=_headers(), timeout=(CONNECT_TIMEOUT, TIMEOUT))
        r.raise_for_status()
        lines = [l.strip() for l in r.text.splitlines() if l.strip() and not l.startswith("#")]
    except Exception as e:
        _log.warning(f"[m3u8] 解析失败: {e}")
        return []
    return [urljoin(m3u8_url, l) for l in lines]


def download_hls(m3u8_url: str, output_path: Path,
                 stop_flag: threading.Event = None, progress_cb=None) -> tuple[str, str]:
    """下载 HLS 流 → 合并为单个 TS 文件 → (路径, 错误)"""
    try:
        segments = _parse_m3u8(m3u8_url)
        if not segments:
            return "", "m3u8 无分片"

        total = len(segments)
        _log.info(f"[HLS] {m3u8_url} -> {total} 分片")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = output_path.parent / f"._hls_{output_path.stem}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        failed = 0
        stopped = False
        workers = min(MAX_WORKERS, 16)

        def _fetch(seg_info):
            idx, url = seg_info
            if stop_flag and stop_flag.is_set():
                return idx, False
            seg_path = tmp_dir / f"{idx:06d}.ts"
            if seg_path.exists() and seg_path.stat().st_size > 0:
                return idx, True
            try:
                r = requests.get(url, headers=_headers(url),
                                 timeout=(CONNECT_TIMEOUT, TIMEOUT), stream=True)
                r.raise_for_status()
                with open(seg_path, "wb") as f:
                    for c in r.iter_content(chunk_size=CHUNK_SIZE):
                        if stop_flag and stop_flag.is_set():
                            r.close()
                            return idx, False
                        if c:
                            f.write(c)
                return idx, True
            except Exception as exc:
                _log.warning(f"[HLS] 分片 {idx} 失败: {exc}")
                return idx, False

        seg_args = list(enumerate(segments))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(_fetch, sa) for sa in seg_args):
                idx, ok = future.result()
                if not ok and stop_flag and stop_flag.is_set():
                    stopped = True
                    for f in seg_args:
                        if hasattr(f, 'cancel'):
                            pass
                elif not ok:
                    failed += 1
                if progress_cb:
                    done = idx + 1
                    progress_cb(total, done, f"分片 {done}/{total}")

        if stopped:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return "", _STOPPED_MARKER

        if failed / total > 0.3:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return "", f"失败分片过多 ({failed}/{total})"

        # 合并
        if progress_cb:
            progress_cb(total, total, "合并中...")

        with open(output_path, "wb") as out:
            for i in range(total):
                if stop_flag and stop_flag.is_set():
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    output_path.unlink(missing_ok=True)
                    return "", _STOPPED_MARKER
                seg = tmp_dir / f"{i:06d}.ts"
                if seg.exists():
                    with open(seg, "rb") as sf:
                        shutil.copyfileobj(sf, out)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        size_mb = output_path.stat().st_size / 1024 / 1024
        _log.info(f"[HLS] 完成: {output_path} ({size_mb:.1f}MB)")
        return str(output_path), ""

    except Exception as e:
        return "", str(e)


# ══════════════════════════════════════════════════════════
#  批量下载（多资源并行）
# ══════════════════════════════════════════════════════════

def download_all(resources: list, save_dir: Path,
                 stop_flag: threading.Event = None, progress_cb=None,
                 max_workers: int = 6) -> list[tuple[str, str]]:
    """
    多资源并行下载：HLS 和普通文件同时进行。
    """
    total = len(resources)
    counter = {"done": 0, "lock": threading.Lock()}
    results_dict = {}

    hls_items = []
    normal_items = []
    for i, r in enumerate(resources):
        if "HLS" in r.rtype or ".m3u8" in r.url:
            hls_items.append((i, r))
        else:
            normal_items.append((i, r))

    def _inc_done():
        with counter["lock"]:
            counter["done"] += 1
            return counter["done"]

    def _do_hls(idx, r):
        if stop_flag and stop_flag.is_set():
            results_dict[idx] = (r.url, _STOPPED_MARKER)
            _inc_done()
            return
        safe_name = re.sub(r'[\\/:*?"<>|]', '', r.name)
        if safe_name.endswith(".m3u8"):
            safe_name = safe_name[:-5] + ".ts"
        output = save_dir / safe_name

        if progress_cb:
            progress_cb(total, counter["done"], f"📻 {safe_name[:30]}")

        path, err = download_hls(r.url, output, stop_flag=stop_flag)
        if err == _STOPPED_MARKER:
            results_dict[idx] = (r.url, _STOPPED_MARKER)
        elif not err:
            results_dict[idx] = (r.url, path)
            sz_mb = Path(path).stat().st_size / 1024 / 1024
            if progress_cb:
                progress_cb(total, _inc_done(), f"✅ {safe_name} ({sz_mb:.1f}MB)")
        else:
            results_dict[idx] = (r.url, err)
            _inc_done()

    def _do_normal(idx, r):
        if stop_flag and stop_flag.is_set():
            results_dict[idx] = (r.url, _STOPPED_MARKER)
            _inc_done()
            return
        path, err = download_file(r.url, save_dir, stop_flag=stop_flag)
        results_dict[idx] = (r.url, path if not err else err)
        done = _inc_done()
        if progress_cb:
            progress_cb(total, done, r.name[:45])

    all_futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for idx, r in hls_items:
            all_futures.append(pool.submit(_do_hls, idx, r))
        for idx, r in normal_items:
            all_futures.append(pool.submit(_do_normal, idx, r))
        for f in as_completed(all_futures):
            try:
                f.result()
            except Exception:
                pass
            if stop_flag and stop_flag.is_set():
                break

    return [results_dict.get(i, (resources[i].url, "未完成")) for i in range(total)]
