"""core.controller 单元测试"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.controller import normalize_urls, get_label_for_urls


class TestNormalizeUrls:
    """URL 规范化测试"""

    def test_empty_input(self):
        assert normalize_urls("") == []
        assert normalize_urls("   ") == []

    def test_single_url_without_protocol(self):
        result = normalize_urls("example.com")
        assert result == ["https://example.com"]

    def test_single_url_with_https(self):
        result = normalize_urls("https://example.com/path")
        assert result == ["https://example.com/path"]

    def test_single_url_with_http(self):
        result = normalize_urls("http://example.com")
        assert result == ["http://example.com"]

    def test_comma_separated(self):
        result = normalize_urls("a.com, b.com")
        assert result == ["https://a.com", "https://b.com"]

    def test_newline_separated(self):
        result = normalize_urls("a.com\nb.com")
        assert result == ["https://a.com", "https://b.com"]

    def test_deduplication(self):
        result = normalize_urls("a.com, a.com, b.com")
        assert result == ["https://a.com", "https://b.com"]

    def test_mixed_delimiters(self):
        result = normalize_urls("a.com; b.com\nc.com, https://d.com")
        assert len(result) == 4
        assert "https://a.com" in result
        assert "https://d.com" in result


class TestGetLabelForUrls:
    def test_single_url(self):
        assert get_label_for_urls(["https://example.com"]) == "https://example.com"

    def test_multiple_urls(self):
        assert get_label_for_urls(["a", "b", "c"]) == "3 个网页"