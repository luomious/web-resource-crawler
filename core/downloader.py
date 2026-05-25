"""
并发下载器 — 普通文件 + HLS 流媒体，支持暂停/取消 + 时间轴嵌入
"""
import re
import shutil
import subprocess
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
CHUNK_SIZE = 524288  # 512KB 加速读写

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
_STOPPED_MARKER = "__STOPPED__"


def _headers(url: str = "") -> dict:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": url.rsplit("/", 1)[0] if url else "",
    }


def download_file(url: str, save_dir: Path, stop_flag: threading.Event = None, progress_cb=None) -> tuple[str, str]:
    """下载单个普通文件 -> (本地路径, 错误信息)"""
    try:
        resp = requests.get(url, headers=_headers(url), timeout=(CONNECT_TIMEOUT, TIMEOUT), stream=True)
        resp.raise_for_status()
        name = _extract_filename(url, resp)
        path = save_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        total = int(resp.headers.get("Content-Length", 0))
        written = 0
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if stop_flag and stop_flag.is_set():
                    resp.close()
                    return "", _STOPPED_MARKER
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
                    if progress_cb:
                        progress_cb(total if total else 1, written, name[:40])
        return str(path), ""
    except Exception as e:
        return "", str(e)


def _extract_filename(url: str, resp: requests.Response) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename[^;=\n]*=(?:["\']?)([^\n;"\']*)', cd)
    if m and m.group(1).strip():
        return m.group(1).strip()
    name = url.split("?")[0].split("/")[-1]
    if name and "." in name:
        return name
    ct = resp.headers.get("Content-Type", "").split(";")[0].lower()
    ext_map = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
        "image/webp": ".webp", "image/svg+xml": ".svg",
        "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/wav": ".wav",
        "video/mp4": ".mp4", "video/webm": ".webm",
        "text/css": ".css", "application/javascript": ".js",
    }
    return "file" + ext_map.get(ct, "")


# ══════════════════════════════════════════════════════════
#  HLS (m3u8) 下载
# ══════════════════════════════════════════════════════════

def _parse_m3u8(m3u8_url: str) -> list[str]:
    resp = requests.get(m3u8_url, headers=_headers(m3u8_url), timeout=(CONNECT_TIMEOUT, TIMEOUT))
    resp.raise_for_status()
    lines = [l.strip() for l in resp.text.split("\n") if l.strip() and not l.startswith("#")]
    master = any("#EXT-X-STREAM-INF" in l for l in resp.text.split("\n"))
    if master:
        best_bw, best_url = 0, ""
        for i, line in enumerate(resp.text.split("\n")):
            if line.startswith("#EXT-X-STREAM-INF"):
                bw = int(re.search(r"BANDWIDTH=(\d+)", line).group(1)) if "BANDWIDTH=" in line else 0
                if i + 1 < len(resp.text.split("\n")):
                    nl = resp.text.split("\n")[i + 1].strip()
                    if nl and not nl.startswith("#") and bw > best_bw:
                        best_bw, best_url = bw, nl
        if best_url:
            return _parse_m3u8(urljoin(m3u8_url, best_url))
        return []
    return [urljoin(m3u8_url, l) for l in lines]


def download_hls(m3u8_url: str, output_path: Path,
                 stop_flag: threading.Event = None, progress_cb=None,
                 chapters: list = None) -> tuple[str, str]:
    """下载 HLS 流 → 合并为单个文件 → (路径, 错误)"""
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
        workers = min(MAX_WORKERS, 16)  # 必须在使用前定义

        # 共享 Session 复用连接池
        shared_session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers * 2)
        shared_session.mount("https://", adapter)

        def _fetch(seg_info):
            idx, url = seg_info
            if stop_flag and stop_flag.is_set():
                return idx, False
            seg_path = tmp_dir / f"{idx:06d}.ts"
            if seg_path.exists() and seg_path.stat().st_size > 0:
                return idx, True
            try:
                r = shared_session.get(url, headers=_headers(url),
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
            futures = {pool.submit(_fetch, arg): arg for arg in seg_args}
            for i, future in enumerate(as_completed(futures)):
                idx, ok = future.result()
                if stop_flag and stop_flag.is_set():
                    stopped = True
                    # 取消剩余任务
                    for f in futures:
                        f.cancel()
                    break
                if not ok:
                    failed += 1
                if progress_cb:
                    progress_cb(total, i + 1, f"分片 {i+1}/{total}")

        if stopped:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return "", _STOPPED_MARKER

        if failed > total * 0.15:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return "", f"HLS 下载失败 {failed}/{total} 个分片"

        # 合并所有分片
        merged_ts = output_path.with_suffix(".merged.ts")
        with open(merged_ts, "wb") as out:
            for i in range(total):
                if stop_flag and stop_flag.is_set():
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    merged_ts.unlink(missing_ok=True)
                    return "", _STOPPED_MARKER
                seg = tmp_dir / f"{i:06d}.ts"
                if seg.exists():
                    with open(seg, "rb") as sf:
                        while True:
                            chunk = sf.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            out.write(chunk)

        shutil.rmtree(tmp_dir, ignore_errors=True)

        # 转换为 MP3（FFmpeg）或保留 TS
        final_output = output_path
        ffmpeg = _find_ffmpeg()
        if ffmpeg:
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-i", str(merged_ts), "-acodec", "libmp3lame",
                     "-ab", "128k", str(final_output)],
                    capture_output=True, timeout=300, check=True
                )
                merged_ts.unlink()
                _log.info(f"[HLS] 已转换为 MP3: {final_output}")
            except Exception as e:
                _log.warning(f"[HLS] FFmpeg 转换失败: {e}, 保留 TS 文件")
                final_output = merged_ts
        else:
            final_output = merged_ts
            _log.info(f"[HLS] FFmpeg 未安装，保留 TS 文件: {final_output}")

        size_mb = final_output.stat().st_size / 1024 / 1024
        size_mb = final_output.stat().st_size / 1024 / 1024
        _log.info(f"[HLS] 完成: {final_output} ({size_mb:.1f}MB)")

        # 嵌入时间轴章节
        if chapters:
            ch_result = _embed_chapters(final_output, chapters)
            if ch_result:
                _log.info(f"[HLS] 时间轴已嵌入: {ch_result}")

        return str(final_output), ""
    except Exception as e:
        return "", f"HLS 错误: {e}"


# ══════════════════════════════════════════════════════════
#  时间轴嵌入（FFmpeg）
# ══════════════════════════════════════════════════════════

def _find_ffmpeg() -> str | None:
    """查找 FFmpeg 路径"""
    for name in ["ffmpeg", "ffmpeg.exe"]:
        path = shutil.which(name)
        if path:
            return path
    # 常见安装路径
    for p in [Path("C:/ffmpeg/bin/ffmpeg.exe"), Path.home() / "ffmpeg/bin/ffmpeg.exe"]:
        if p.exists():
            return str(p)
    return None


def _embed_chapters(audio_path: Path, chapters: list) -> str | None:
    """将时间轴嵌入音频文件（优先 mutagen，备选 FFmpeg，始终写 .txt）"""
    # 始终写 chapters.txt
    chapters_txt = audio_path.with_suffix(".chapters.txt")
    lines = []
    for ch in chapters:
        start, end = ch[0], ch[1]
        title = ch[3] if len(ch) > 3 and ch[3] else ch[2]
        zh = ch[3] if len(ch) > 3 else ""
        line = f"[{_fmt_time(start)} → {_fmt_time(end) if end else 'END'}] {ch[2]}"
        if zh:
            line += f"\n      [{_fmt_time(start)}] {zh}"
        lines.append(line)
    chapters_txt.write_text("\n".join(lines), encoding="utf-8")

    # 尝试 mutagen：ID3 章节 + 同步歌词字幕（SYLT）
    result = _embed_mutagen_full(audio_path, chapters)
    if result:
        return f"{result} + {chapters_txt.name}"

    # 备选 FFmpeg
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        result = _embed_ffmpeg(audio_path, chapters, ffmpeg)
        if result:
            return f"{result} + {chapters_txt.name}"

    return f"时间轴已保存: {chapters_txt.name}"


def _embed_mutagen_full(audio_path: Path, chapters: list) -> str | None:
    """用 mutagen 写入 ID3v2 章节 + 同步歌词（SYLT）+ 生成 .srt"""
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, CHAP, TIT2, CTOC, SYLT, Encoding, ID3NoHeaderError

        audio = MP3(str(audio_path))
        try:
            audio.add_tags()
        except Exception:
            pass
        tags = audio.tags
        if not tags:
            tags = ID3()
            audio.tags = tags

        # 删除旧章节/歌词
        for key in list(tags.keys()):
            if key.startswith(("CHAP", "CTOC", "SYLT")):
                del tags[key]

        # 1. 写入章节
        toc_ids = []
        for i, ch in enumerate(chapters):
            title = ch[3] if len(ch) > 3 and ch[3] else ch[2]
            cid = f"chp{i}"
            toc_ids.append(cid)
            tags.add(CHAP(element_id=cid, start_time=ch[0]*1000, end_time=ch[1]*1000,
                          sub_frames=[TIT2(text=[title])]))
        tags.add(CTOC(element_id="toc", flags=0, child_element_ids=toc_ids,
                      sub_frames=[TIT2(text=["目录"])]))

        # 2. 写入同步歌词（SYLT — 播放器显示字幕）
        sylt_texts, sylt_ts = [], []
        for ch in chapters:
            title = ch[3] if len(ch) > 3 and ch[3] else ch[2]
            sylt_texts.append(title)
            sylt_ts.append(ch[0] * 1000)
        tags.add(SYLT(encoding=Encoding.UTF8, language="zho", time_stamp_format=2,
                       content_type=1, desc="字幕",
                       text=list(zip(sylt_texts, sylt_ts))))

        audio.save()

        # 3. 生成 .srt 字幕文件
        srt_path = audio_path.with_suffix(".srt")
        srt_lines = []
        for i, ch in enumerate(chapters):
            title = ch[3] if len(ch) > 3 and ch[3] else ch[2]
            srt_lines.append(str(i + 1))
            srt_lines.append(f"{_fmt_time_ms(ch[0]*1000)} --> {_fmt_time_ms(ch[1]*1000)}")
            srt_lines.append(title)
            srt_lines.append("")
        srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

        return f"{len(chapters)} 个章节+字幕已嵌入音频"
    except Exception as e:
        _log.warning(f"[chapters] mutagen 失败: {e}")
        return None


def _embed_ffmpeg(audio_path: Path, chapters: list, ffmpeg: str) -> str | None:
    """用 FFmpeg 嵌入章节元数据"""
    meta_path = audio_path.with_suffix(".meta.txt")
    meta_lines = [";FFMETADATA1"]
    for ch in chapters:
        title = ch[3] if len(ch) > 3 and ch[3] else ch[2]
        meta_lines.append("[CHAPTER]")
        meta_lines.append("TIMEBASE=1/1000")
        meta_lines.append(f"START={ch[0] * 1000}")
        meta_lines.append(f"END={ch[1] * 1000}")
        meta_lines.append(f"title={title}")
    meta_path.write_text("\n".join(meta_lines), encoding="utf-8")
    tmp_out = audio_path.with_name(audio_path.stem + "_ch" + audio_path.suffix)
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(audio_path), "-i", str(meta_path),
             "-map_metadata", "1", "-c", "copy", str(tmp_out)],
            capture_output=True, timeout=120, check=True
        )
        shutil.move(str(tmp_out), str(audio_path))
        meta_path.unlink()
        return f"{len(chapters)} 个章节已嵌入"
    except Exception as e:
        meta_path.unlink()
        _log.warning(f"[chapters] FFmpeg 失败: {e}")
        return None


def _fmt_time(sec: int) -> str:
    h, m = divmod(sec, 3600)
    m, s = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_time_ms(ms: int) -> str:
    """SRT 格式: HH:MM:SS,mmm"""
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    s, ms_part = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms_part:03d}"


# ══════════════════════════════════════════════════════════
#  批量下载
# ══════════════════════════════════════════════════════════

def download_all(resources: list, save_dir: Path,
                 stop_flag: threading.Event = None, progress_cb=None,
                 max_workers: int = 6) -> list[tuple[str, str]]:
    """
    多资源并行下载：HLS 和普通文件同时进行，互不阻塞。
    progress_cb(total, done, name) — done 是全局完成计数
    """
    total = len(resources)
    counter = {"done": 0, "lock": threading.Lock()}
    results_dict = {}  # idx → (url, path_or_error)

    # 分离类型
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

    # ── HLS 下载（每个单独线程，并行）───────────────
    def _do_hls(idx, r):
        if stop_flag and stop_flag.is_set():
            results_dict[idx] = (r.url, _STOPPED_MARKER)
            _inc_done()
            return
        safe_name = re.sub(r'[\\/:*?"<>|]', '', r.name)
        if safe_name.endswith(".m3u8"):
            safe_name = safe_name[:-5] + ".mp3"
        output = save_dir / safe_name

        if progress_cb:
            progress_cb(total, counter["done"], f"📻 {safe_name[:30]}")

        def _seg_cb(seg_total, seg_done, seg_name):
            pass  # 分段进度不干扰全局（暂不报告，避免 UI 事件队列过载）

        path, err = download_hls(r.url, output, stop_flag=stop_flag,
                                 progress_cb=_seg_cb,
                                 chapters=getattr(r, 'chapters', None))
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

    # ── 普通文件下载 ───────────────────────────────
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

    # ── 并行执行 ────────────────────────────────────
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
                for f2 in all_futures:
                    f2.cancel()
                break

    # ── 按原始顺序返回 ──────────────────────────────
    return [results_dict.get(i, (resources[i].url, "未完成")) for i in range(total)]
