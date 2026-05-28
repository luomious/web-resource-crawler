"""gui 下载配置传递测试"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import gui


class TestDownloadWorkerConfig:
    """DownloadWorker 应把 GUI 配置传给下载器"""

    def test_worker_accepts_download_worker_settings(self):
        sig = inspect.signature(gui.DownloadWorker.__init__)
        assert "max_workers" in sig.parameters
        assert "hls_max_workers" in sig.parameters

    def test_worker_passes_worker_settings_to_download_all(self):
        source = inspect.getsource(gui.DownloadWorker.run)
        assert "max_workers=self._max_workers" in source
        assert "hls_max_workers=self._hls_max_workers" in source
