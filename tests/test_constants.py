"""core.constants 单元测试"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import constants


class TestConstantsValues:
    """验证常量值类型和基本约束"""

    def test_user_agents_non_empty(self):
        assert isinstance(constants.USER_AGENTS, list)
        assert len(constants.USER_AGENTS) >= 1
        for ua in constants.USER_AGENTS:
            assert isinstance(ua, str)
            assert len(ua) > 10

    def test_timeouts_positive(self):
        assert constants.TIMEOUT > 0
        assert constants.CONNECT_TIMEOUT > 0
        assert constants.DOWNLOAD_TIMEOUT > 0
        assert constants.DOWNLOAD_CONNECT_TIMEOUT > 0

    def test_max_retries_positive(self):
        assert constants.MAX_RETRIES >= 0

    def test_ext_sets(self):
        for name in [
            "IMG_EXTS", "AUDIO_EXTS", "VIDEO_EXTS",
            "DOC_EXTS", "CSS_EXTS", "JS_EXTS",
        ]:
            val = getattr(constants, name)
            assert isinstance(val, set)
            assert all(ext.startswith(".") for ext in val)

    def test_chunk_sizes_positive(self):
        assert constants.CHUNK_SIZE > 0
        assert constants.DOWNLOAD_CHUNK_SIZE > 0
        assert constants.DOWNLOAD_CHUNK_SIZE == 1024 * 1024

    def test_hls_worker_bounds(self):
        assert constants.HLS_DOWNLOAD_WORKERS == 24
        assert constants.HLS_DOWNLOAD_WORKER_LIMIT == 48
        assert constants.MAX_DOWNLOAD_WORKERS <= constants.HLS_DOWNLOAD_WORKER_LIMIT

    def test_stopped_marker(self):
        assert constants.STOPPED_MARKER == "__STOPPED__"


class TestDefaultUserAgent:
    """DEFAULT_USER_AGENT 验证"""

    def test_exists(self):
        assert hasattr(constants, "DEFAULT_USER_AGENT")
        assert "Mozilla" in constants.DEFAULT_USER_AGENT
