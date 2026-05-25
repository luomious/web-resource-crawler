# 🌐 网页资源爬虫

多功能网页资源抓取工具，支持图片、音频、视频、HLS 流媒体等多媒体资源下载。

## ✨ 功能特性

- 🔍 **多平台抓取** — 支持 ASMR、微博、B站、知乎等多网站资源提取
- 📻 **HLS 流下载** — 自动解析 .m3u8，并发下载 TS 分片后合并
- 📝 **时间轴字幕** — 提取 ASMR 章节并嵌入 MP3 为 ID3 同步歌词 + SRT 字幕
- 🌐 **多语翻译** — 日/韩文时间轴自动翻译为中文
- 📦 **批量下载** — 多 URL 同时抓取，多资源并行下载
- 💾 **历史记录** — 抓取历史自动保存，支持搜索和右键删除
- 🎨 **暗色/亮色主题** — GitHub 风格精美界面，实时切换

## 🚀 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python gui.py
```

## 📦 打包

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name "网页资源爬虫" --add-data "core;core" gui.py
```

## 🏗 项目结构

```
├── gui.py              # Tkinter 图形界面
├── core/
│   ├── scraper.py      # 网页抓取 + 解析 + 翻译
│   └── downloader.py   # 并发下载 + HLS 合并 + 字幕嵌入
├── requirements.txt
└── .gitignore
```

## 🛠 技术栈

- **Python 3.13** + Tkinter GUI
- **requests + BeautifulSoup** — 网页抓取解析
- **mutagen** — MP3 章节/字幕嵌入
- **deep-translator** — 多语言翻译
- **ThreadPoolExecutor** — 并发下载
- **PyInstaller** — 单文件打包

## 📄 License

MIT
