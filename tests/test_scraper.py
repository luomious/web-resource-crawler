"""core.scraper / core.parser 单元测试"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 新代码直接导入子模块，不依赖 scraper.py 的重导出
from core.parser import Resource, classify, extract_name, parse_resources
from core.asmr_one import is_asmr_one
from core.unpacker import unpack_js
from core.fetcher import fetch_html


class TestResource:
    """Resource 数据类测试"""

    def test_resource_creation(self):
        r = Resource(url="https://example.com/a.mp3", rtype="音频", name="a.mp3")
        assert r.url == "https://example.com/a.mp3"
        assert r.rtype == "音频"
        assert r.name == "a.mp3"
        assert r.checked is True
        assert r.chapters is None

    def test_resource_defaults(self):
        r = Resource(url="x", rtype="其他", name="x")
        assert r.size == ""
        assert r.source == ""


class TestClassify:
    """classify 函数测试"""

    def test_image_extensions(self):
        for ext in ["jpg", "png", "gif", "webp", "svg", "bmp", "avif"]:
            assert classify(f"https://x.com/file.{ext}") == "图片"

    def test_audio_extensions(self):
        for ext in ["mp3", "m4a", "wav", "flac", "ogg", "opus"]:
            assert classify(f"https://x.com/file.{ext}") == "音频"

    def test_video_extensions(self):
        for ext in ["mp4", "webm", "mkv", "avi", "mov", "flv"]:
            assert classify(f"https://x.com/file.{ext}") == "视频"

    def test_hls_detection(self):
        assert classify("https://x.com/stream.m3u8") == "音频-HLS"

    def test_document_extensions(self):
        for ext in ["pdf", "docx", "xlsx", "pptx", "zip", "rar"]:
            assert classify(f"https://x.com/file.{ext}") == "文档"

    def test_css_js(self):
        assert classify("https://x.com/style.css") == "样式"
        assert classify("https://x.com/app.js") == "脚本"

    def test_unknown_returns_candidate(self):
        assert classify("https://x.com/file.xyz", "音频") == "音频"
        assert classify("https://x.com/file.xyz") == "其他"


class TestExtractName:
    """extract_name 函数测试"""

    def test_simple_path(self):
        name = extract_name("https://x.com/path/to/file.mp3")
        assert name == "file.mp3"

    def test_query_params(self):
        name = extract_name("https://x.com/dl?src=music.mp3&token=abc")
        assert name == "music.mp3"

    def test_no_extension(self):
        name = extract_name("https://x.com/download")
        # 无扩展名时返回路径最后一段
        assert name == "download"


class TestIsAsmrOne:
    """asmr.one 检测测试"""

    def test_positive(self):
        assert is_asmr_one("https://asmr.one/work/RJ01000000")
        assert is_asmr_one("http://www.asmr.one/work/RJ12345678")

    def test_negative(self):
        assert not is_asmr_one("https://example.com/work/RJ01000000")
        assert not is_asmr_one("https://asmr.one/other")


class TestUnpackJS:
    """Dean Edwards Packer 反混淆测试"""

    def test_simple_packed(self):
        packed = "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){while(c--)d[c]=k[c]||c;k=[function(e){return d[e]}];e=function(){return'\\\\w+'};c=1};while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c]);return p}('0 1=\"hello\"',2,2,'var|test'.split('|'),0,{}))"
        result = unpack_js(packed)
        assert result is not None
        assert "hello" in result

    def test_invalid_input(self):
        assert unpack_js("plain javascript code") is None
        assert unpack_js("") is None


class TestParseResources:
    """parse_resources 基础测试"""

    def test_empty_html(self):
        res = parse_resources("", "https://example.com")
        assert isinstance(res, list)

    def test_basic_img(self):
        html = '<html><body><img src="photo.jpg"></body></html>'
        res = parse_resources(html, "https://example.com/page/")
        assert any("photo.jpg" in r.name for r in res)

    def test_basic_audio(self):
        html = '<html><body><audio src="track.mp3"></audio></body></html>'
        res = parse_resources(html, "https://example.com/")
        assert any("track.mp3" in r.name for r in res)

    def test_link_stylesheet(self):
        html = '<html><head><link rel="stylesheet" href="style.css"></head></html>'
        res = parse_resources(html, "https://example.com/")
        assert any("style.css" in r.name for r in res)

    def test_data_uri_ignored(self):
        html = '<html><body><img src="data:image/png;base64,xxx"></body></html>'
        res = parse_resources(html, "https://example.com/")
        assert len(res) == 0
