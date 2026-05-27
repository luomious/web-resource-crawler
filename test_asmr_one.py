import requests, re, json, sys
from bs4 import BeautifulSoup
from urllib.parse import urljoin

sys.path.insert(0, r"E:\VSCode\VSCode-Workspace\Web Resource Crawler")
from core.scraper import parse_resources

url = 'https://www.asmr.one/work/RJ01568719'
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
html = r.text
print(f'HTML长度: {len(html)}')

soup = BeautifulSoup(html, 'lxml')

print('\n=== 页面标题 ===')
print(soup.title.text if soup.title else '无标题')

print('\n=== audio/video/source 标签 ===')
for tag in soup.find_all(['audio', 'video', 'source']):
    src = tag.get('src', '')
    print(f'  {tag.name}: {src}')

print('\n=== 脚本数据 ===')
for s in soup.find_all('script'):
    if s.string and any(k in (s.string or '') for k in ['m3u8', 'mediaUrl', 'RJ015687']):
        print(f'  {s.string[:500]}')

print('\n=== 媒体链接 ===')
for a in soup.find_all('a', href=True):
    href = a.get('href')
    if any(ext in href.lower() for ext in ['.m3u8', '.mp3', '.mp4', '.wav', '.flac']):
        print(f'  {href}')

print('\n=== 通用解析 ===')
res = parse_resources(html, url, source_url=url)
print(f'解析到 {len(res)} 个资源')
for r in res:
    print(f'  [{r.rtype}] {r.name}')
