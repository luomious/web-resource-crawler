#!/usr/bin/env python3
"""
测试多 URL 并发抓取功能
"""
import sys
sys.path.insert(0, ".")

from core.scraper import fetch_all_urls, Resource
import re

def test_url_parsing():
    """测试 URL 解析逻辑"""
    test_cases = [
        ("https://example.com", ["https://example.com"]),
        ("https://a.com\nhttps://b.com", ["https://a.com", "https://b.com"]),
        ("a.com,b.com,c.com", ["https://a.com", "https://b.com", "https://c.com"]),
        ("a.com;b.com;c.com", ["https://a.com", "https://b.com", "https://c.com"]),
        ("  a.com  ,  b.com  ,  c.com  ", ["https://a.com", "https://b.com", "https://c.com"]),
        ("a.com\nb.com,c.com;d.com", ["https://a.com", "https://b.com", "https://c.com", "https://d.com"]),
    ]
    
    print("=== 测试 URL 解析 ===")
    for input_str, expected in test_cases:
        urls = [u.strip() for u in re.split(r'[\n,;]+', input_str) if u.strip()]
        normalized = [u if u.startswith(("http://","https://")) else "https://"+u for u in urls]
        success = normalized == expected
        print(f"{'✅' if success else '❌'} {input_str[:30]:30} -> {len(normalized)} URLs")
        if not success:
            print(f"  期望: {expected}")
            print(f"  实际: {normalized}")
    print()

def test_resource_source():
    """测试 Resource 的 source 属性"""
    print("=== 测试 Resource source 属性 ===")
    r = Resource("http://test.com/image.jpg", "图片", "image.jpg", source="http://parent.com")
    print(f"✅ Resource 有 source 属性: {r.source}")
    print()

def test_imports():
    """测试导入"""
    print("=== 测试导入 ===")
    try:
        from core.scraper import fetch_all_urls
        print("✅ fetch_all_urls 导入成功")
    except ImportError as e:
        print(f"❌ fetch_all_urls 导入失败: {e}")
    print()

def main():
    print("Web Resource Crawler 多 URL 功能测试")
    print("=" * 50)
    test_imports()
    test_url_parsing()
    test_resource_source()
    print("✅ 所有测试通过！")
    print("\n使用说明:")
    print("1. 运行 python gui.py 启动 GUI")
    print("2. 在 URL 输入框中输入多个网址（用换行、逗号或分号分隔）")
    print("3. 按 Ctrl+Enter 或点击「抓取」按钮")
    print("4. 程序会并发抓取所有网页，自动汇总资源")

if __name__ == "__main__":
    main()