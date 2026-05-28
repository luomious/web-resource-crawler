"""core.unpacker JS 混淆解码单元测试"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.unpacker import extract_m3u8_from_html, unpack_js


class TestUnpackJs:
    """JS 混淆解码测试"""

    # 标准 Dean Edwards Packer 格式
    SAMPLE_P1: str = 'eval(function(p,a,c,k,e,d){'
    SAMPLE_CLOSE: str = '}'

    def test_empty_string(self):
        """空字符串或非 Packer 内容返回 None"""
        assert unpack_js("") is None
        assert unpack_js("no eval here") is None

    def test_non_packed_js(self):
        """非 Packer 格式直接返回 None"""
        js = 'var x = 1; console.log(x);'
        result = unpack_js(js)
        assert result is None

    def test_no_m3u8_content(self):
        """不完整 Packer 格式返回 None"""
        js = f"""{self.SAMPLE_P1}return "hello world";}})()"""
        result = unpack_js(js)
        assert result is None

    def test_partial_packer(self):
        """不完整的 packer 返回 None"""
        js = 'eval(function(p,a,c,k,e,d){'  # 未闭合
        result = unpack_js(js)
        assert result is None

    def test_m3u8_in_plain_js(self):
        """普通 JS 中包含 m3u8 URL"""
        js = 'var url = "https://example.com/video.m3u8";'
        result = extract_m3u8_from_html(js)
        assert result == ["https://example.com/video.m3u8"]
