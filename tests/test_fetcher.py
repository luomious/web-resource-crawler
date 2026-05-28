"""core.fetcher 单元测试"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.fetcher import make_session, fetch_html, fetch_all_urls


class TestMakeSession:
    """Session 工厂测试"""

    def test_returns_session(self):
        import requests
        s = make_session()
        assert isinstance(s, requests.Session)
        s.close()

    def test_has_retry_adapter(self):
        s = make_session()
        adapter = s.get_adapter("https://example.com")
        assert adapter is not None
        s.close()

    def test_has_both_scheme_adapters(self):
        s = make_session()
        assert s.get_adapter("https://example.com") is not None
        assert s.get_adapter("http://example.com") is not None
        s.close()


class TestFetchHtml:
    """fetch_html 测试"""

    @patch("core.fetcher.make_session")
    def test_returns_html_string(self, mock_make_session):
        """正常请求返回 HTML 字符串"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Hello</body></html>"
        mock_resp.content = b"<html><body>Hello</body></html>"
        mock_resp.apparent_encoding = "utf-8"
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_make_session.return_value = mock_session

        result = fetch_html("https://example.com")
        assert "Hello" in result
        mock_session.close.assert_called_once()

    @patch("core.fetcher.make_session")
    def test_asmr_one_returns_empty(self, mock_make_session):
        """asmr.one URL 不请求 HTML，直接返回空字符串"""
        result = fetch_html("https://asmr.one/work/RJ01000000")
        assert result == ""
        mock_make_session.assert_not_called()

    @patch("core.fetcher.make_session")
    def test_gbk_encoding_auto_decode(self, mock_make_session):
        """GBK 编码页面自动解码"""
        html_gbk = "<html><body>中文内容</body></html>".encode("gbk")

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "wrong"  # requests 默认解码
        mock_resp.content = html_gbk
        mock_resp.apparent_encoding = "gbk"
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_make_session.return_value = mock_session

        result = fetch_html("https://example.com/gbk-page")
        assert "中文内容" in result


class TestFetchAllUrls:
    """多 URL 并发抓取测试"""

    @patch("core.fetcher.fetch_html")
    @patch("core.fetcher.parse_resources")
    def test_single_url(self, mock_parse, mock_fetch):
        """单个 URL 抓取"""
        mock_fetch.return_value = "<html></html>"
        mock_parse.return_value = [
            type("Resource", (), {"url": "https://x.com/a.mp3", "rtype": "音频", "name": "a.mp3"})(),
        ]

        results = fetch_all_urls(["https://example.com"])
        assert len(results) == 1

    @patch("core.fetcher.fetch_html")
    @patch("core.fetcher.parse_resources")
    def test_deduplication(self, mock_parse, mock_fetch):
        """多 URL 结果去重"""
        mock_fetch.return_value = "<html></html>"
        r = type("Resource", (), {"url": "https://x.com/a.mp3", "rtype": "音频", "name": "a.mp3"})()
        # 两个 URL 返回相同资源
        mock_parse.side_effect = [[r], [r]]

        results = fetch_all_urls(["https://site1.com", "https://site2.com"])
        assert len(results) == 1  # 去重后只保留一个

    @patch("core.fetcher.fetch_html")
    def test_fetch_failure_graceful(self, mock_fetch):
        """单个 URL 失败不影响其他"""
        mock_fetch.side_effect = Exception("Network error")
        results = fetch_all_urls(["https://bad.com"])
        assert results == []
