"""core.asmr_one 单元测试"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.asmr_one import is_asmr_one, parse_asmr_one


class TestIsAsmrOne:
    """asmr.one URL 识别测试"""

    def test_positive_https(self):
        assert is_asmr_one("https://asmr.one/work/RJ01000000")

    def test_positive_http_www(self):
        assert is_asmr_one("http://www.asmr.one/work/RJ12345678")

    def test_negative_other_domain(self):
        assert not is_asmr_one("https://example.com/work/RJ01000000")

    def test_negative_wrong_path(self):
        assert not is_asmr_one("https://asmr.one/other")

    def test_negative_empty(self):
        assert not is_asmr_one("")


class TestParseAsmrOne:
    """asmr.one API 解析测试（mock requests.get）"""

    @patch("core.asmr_one.requests.get")
    def test_parse_audio_files(self, mock_get):
        """正常 API 返回音频资源"""
        # mock workInfo 响应
        info_resp = MagicMock()
        info_resp.json.return_value = {"id": 42}
        info_resp.raise_for_status = MagicMock()

        # mock tracks 响应
        tracks_resp = MagicMock()
        tracks_resp.json.return_value = [
            {
                "type": "audio",
                "title": "intro.mp3",
                "mediaDownloadUrl": "https://cdn.asmr.one/audio/intro.mp3",
            },
            {
                "type": "folder",
                "title": "Chapter 1",
                "children": [
                    {
                        "type": "audio",
                        "title": "scene1.m4a",
                        "mediaDownloadUrl": "https://cdn.asmr.one/audio/scene1.m4a",
                    },
                ],
            },
            {
                "type": "text",
                "title": "subtitle.srt",
                "mediaDownloadUrl": "https://cdn.asmr.one/subs/subtitle.srt",
            },
        ]
        tracks_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [info_resp, tracks_resp]

        resources = parse_asmr_one("https://asmr.one/work/RJ01000000")
        assert len(resources) == 3
        urls = [r.url for r in resources]
        assert "https://cdn.asmr.one/audio/intro.mp3" in urls
        assert "https://cdn.asmr.one/audio/scene1.m4a" in urls
        assert "https://cdn.asmr.one/subs/subtitle.srt" in urls

        # folder 子资源的 name 应含路径
        scene1 = [r for r in resources if "scene1" in r.name][0]
        assert "Chapter 1" in scene1.name

    @patch("core.asmr_one.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        """API 请求失败返回空列表"""
        import requests
        mock_get.side_effect = requests.RequestException("Network error")

        resources = parse_asmr_one("https://asmr.one/work/RJ99999999")
        assert resources == []

    @patch("core.asmr_one.requests.get")
    def test_no_work_id_returns_empty(self, mock_get):
        """workInfo 返回无 id 字段"""
        info_resp = MagicMock()
        info_resp.json.return_value = {"title": "test"}  # 没有 id
        info_resp.raise_for_status = MagicMock()
        mock_get.return_value = info_resp

        resources = parse_asmr_one("https://asmr.one/work/RJ00000000")
        assert resources == []

    @patch("core.asmr_one.requests.get")
    def test_invalid_url_returns_empty(self, mock_get):
        """非 asmr.one URL 返回空列表"""
        resources = parse_asmr_one("https://example.com/page")
        assert resources == []
        mock_get.assert_not_called()

    @patch("core.asmr_one.requests.get")
    def test_video_type(self, mock_get):
        """video 类型资源也正确提取"""
        info_resp = MagicMock()
        info_resp.json.return_value = {"id": 1}
        info_resp.raise_for_status = MagicMock()

        tracks_resp = MagicMock()
        tracks_resp.json.return_value = [
            {
                "type": "video",
                "title": "intro.mp4",
                "mediaDownloadUrl": "https://cdn.asmr.one/video/intro.mp4",
            },
        ]
        tracks_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [info_resp, tracks_resp]

        resources = parse_asmr_one("https://asmr.one/work/RJ01000001")
        assert len(resources) == 1
        assert resources[0].rtype == "视频"
