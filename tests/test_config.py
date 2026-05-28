"""core.config 单元测试"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import (
    get_config_int,
    load_config,
    save_config,
    load_history,
    save_history,
    DEFAULT_CONFIG,
    CONFIG_FILE,
    CONFIG_DIR,
)


class TestConfigLoad:
    """load_config 测试"""

    def test_returns_dict(self):
        cfg = load_config()
        assert isinstance(cfg, dict)

    def test_has_default_keys(self):
        cfg = load_config()
        for key in DEFAULT_CONFIG:
            assert key in cfg


class TestConfigInt:
    """兼容新旧配置格式的整数读取"""

    def test_prefers_top_level_value(self):
        cfg = {"max_workers": 12, "settings": {"max_workers": 4}}
        assert get_config_int(cfg, "max_workers", 6, 1, 32) == 12

    def test_reads_legacy_settings_value(self):
        cfg = {"settings": {"max_workers": "10"}}
        assert get_config_int(cfg, "max_workers", 6, 1, 32) == 10

    def test_clamps_invalid_or_extreme_values(self):
        assert get_config_int({"max_workers": 99}, "max_workers", 6, 1, 32) == 32
        assert get_config_int({"max_workers": "bad"}, "max_workers", 6, 1, 32) == 6


class TestHistory:
    """历史记录测试"""

    def test_load_history_returns_list(self):
        history = load_history()
        assert isinstance(history, list)

    def test_save_history_accepts_list(self):
        save_history(["https://example.com"])
        history = load_history()
        assert isinstance(history, list)

    def test_history_trimmed_to_50(self):
        long_list = [f"https://example.com/page{i}" for i in range(100)]
        save_history(long_list)
        history = load_history()
        assert len(history) <= 50
