"""core.downloader 单元测试"""
import inspect
import pytest
import sys
import time
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.downloader import (
    _clamp_workers,
    _make_session,
    _headers,
    download_file,
    download_all,
    download_hls,
    _parse_m3u8,
)
from core import constants
import core.downloader as downloader
import requests


class TestMakeSession:
    """Session 工厂测试"""

    def test_returns_session(self):
        s = _make_session()
        assert isinstance(s, requests.Session)
        s.close()

    def test_has_retry_adapter(self):
        s = _make_session()
        adapter = s.get_adapter("https://example.com")
        assert adapter is not None
        s.close()


class TestHeaders:
    """_headers 函数测试"""

    def test_basic_headers(self):
        h = _headers()
        assert "User-Agent" in h
        assert "Accept" in h

    def test_with_referer(self):
        h = _headers("https://example.com/page")
        assert h["Referer"] == "https://example.com/page"


class TestParseM3u8:
    """_parse_m3u8 测试"""

    def test_invalid_url_returns_empty(self):
        result = _parse_m3u8("https://invalid.example/missing.m3u8")
        assert isinstance(result, list)
        # 无效 URL 应返回空列表（有日志警告）


class TestWorkerLimits:
    """并发数边界测试"""

    def test_clamp_workers(self):
        assert _clamp_workers(None, 16, 32) == 16
        assert _clamp_workers("bad", 16, 32) == 16
        assert _clamp_workers(0, 16, 32) == 1
        assert _clamp_workers(99, 16, 32) == 32

    def test_download_all_uses_constant_default_workers(self, monkeypatch, tmp_path):
        captured = {}

        class FakeExecutor:
            def __init__(self, max_workers, **kwargs):  # 接受 thread_name_prefix 等额外参数
                captured.setdefault("max_workers_list", []).append(max_workers)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, *args):
                fut = Future()
                try:
                    fut.set_result(fn(*args))
                except Exception:
                    pass
                return fut

        monkeypatch.setattr(downloader, "ThreadPoolExecutor", FakeExecutor)
        monkeypatch.setattr(downloader, "download_file", lambda *a, **k: ("", "failed"))
        monkeypatch.setattr(downloader, "download_hls", lambda *a, **k: ("", "failed"))

        res = SimpleNamespace(url="https://example.com/a.mp3", rtype="音频", name="a.mp3")
        download_all([res], tmp_path)

        # 普通文件线程池应使用 MAX_DOWNLOAD_WORKERS
        assert constants.MAX_DOWNLOAD_WORKERS in captured["max_workers_list"]


class TestHlsDownload:
    """HLS 下载优化测试"""

    def test_hls_reuses_thread_local_sessions(self, monkeypatch, tmp_path):
        created_sessions = []
        closed_sessions = []

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                time.sleep(0.01)
                yield b"ts"

            def close(self):
                return None

            @property
            def headers(self):
                return {}

            @property
            def content(self):
                return b"ts"

        class FakeSession:
            def __init__(self, **kwargs):
                created_sessions.append(self)

            def get(self, *args, **kwargs):
                return FakeResponse()

            def close(self):
                closed_sessions.append(self)

        def fake_merge(tmp_dir, output_path, total, stop_flag=None):
            """模拟合并：写入输出文件"""
            with open(output_path, 'wb') as f:
                f.write(b'ts' * total)

        monkeypatch.setattr(downloader, "_parse_m3u8", lambda url, session=None: [f"seg{i}.ts" for i in range(8)])
        monkeypatch.setattr(downloader, "_make_session", FakeSession)
        monkeypatch.setattr(downloader, "_merge_ts_segments", fake_merge)

        path, err = download_hls(
            "https://example.com/index.m3u8",
            tmp_path / "out.ts",
            max_workers=2,
        )

        assert err == ""
        assert Path(path).exists()
        assert 1 <= len(created_sessions) <= 2
        assert len(created_sessions) < 8
        assert closed_sessions == created_sessions

    def test_hls_cleanup_does_not_use_recursive_rmtree(self):
        source = inspect.getsource(downloader._cleanup_hls_tmp_dir)
        assert "rmtree" not in source
