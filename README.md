# 🌐 网页资源爬虫 v1.0

**桌面单文件 EXE 资源抓取工具** — 支持普通网页资源、asmr.one 作品批量下载，PyQt5 稳定多线程 GUI，开箱即用。

---

## ✨ 功能特性

### 🔍 智能资源发现
- **10 层解析策略**：img 标签（含 14 种懒加载属性）→ video/audio → source 标签 → a 直链 → CSS/JS → JSON 播放器配置 → 全文正则扫描 → CSS 背景图 → 文档链接 → 章节时间轴
- **多 URL 并发抓取**：支持换行、逗号分隔多个 URL，自动去重汇总
- **JS 混淆解码**：内置 Dean Edwards Packer 反混淆，从混淆 JS 中提取 m3u8 地址
- **编码自动推断**：apparent_encoding + fallback UTF-8，覆盖各类中文站点
- **HTTP 容错**：自动重试 3 次，指数退避，429/5xx 状态码自动处理

### 📻 asmr.one 作品抓取
- 输入 `https://www.asmr.one/work/RJ01568719` 即可抓取全部音频和字幕
- 直接调用 asmr.one API，解析作品文件树，递归提取所有音轨
- 自动分类：音频 / 字幕，保持文件夹层级命名

### 📥 HLS 流媒体下载
- 自动解析 `.m3u8` 播放列表
- 16 线程并发下载 TS 分片
- 失败率 > 30% 自动丢弃并报错
- 分片合并为单个 TS 文件

### ⏸ 完善的下载控制
- **停止**：主动中止下载，清理临时文件
- **批量并行**：多资源同时下载，HLS 和普通文件混合调度
- **进度实时**：进度条 + 下载列表实时更新

### 🎨 精美界面
- **PyQt5 原生界面**：稳定多线程，抓取/下载互不阻塞
- **资源类型筛选**：全部 / 图片 / 音频 / 视频 / HLS 流 / CSS / JS / 文档
- **全选/取消**：一键勾选或清空所有资源
- **配置持久化**：保存目录、历史记录写入 `%APPDATA%/WebScraper/config.json`

---

## 🚀 快速开始

### 方式一：直接运行 EXE（推荐）

下载 `网页资源爬虫.exe` 到桌面，双击运行。首次运行会自动创建配置文件。

### 方式二：源码运行

```bash
pip install -r requirements.txt
python gui.py
```

> 推荐 Python 3.12+，已测试 Python 3.13。

### 打包为 EXE

```bash
python -m PyInstaller --onefile --windowed --name "网页资源爬虫" --add-data "core;core" --hidden-import PyQt5 --hidden-import requests --hidden-import bs4 --hidden-import urllib3 --hidden-import lxml --clean --noconfirm gui.py
```

> 打包后 EXE 会在 `dist/` 目录。

---

## 📂 项目结构

```
web-resource-crawler/
├── gui.py              # PyQt5 主界面（含 asmr.one API 内嵌解析）
├── core/
│   ├── __init__.py    # 包初始化
│   ├── scraper.py     # 网页抓取 + 资源解析（10 层提取策略 + asmr.one API）
│   └── downloader.py  # 并发下载 + HLS 分片合并 + 停止控制
├── requirements.txt    # Python 依赖
├── README.md           # 本文件
├── 整合打包.bat        # 一键打包脚本
└── .gitignore
```

---

## 🛠 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| GUI | PyQt5 |
| 网页抓取 | `requests` + `BeautifulSoup4` + `lxml` |
| HLS 解析 | 纯 Python 手写，无 ffmpeg 依赖 |
| 并发 | `concurrent.futures.ThreadPoolExecutor` + `QThread` |
| 打包 | PyInstaller |

---

## 📖 使用示例

### 1. 抓取 asmr.one 作品
输入 `https://www.asmr.one/work/RJ01568719` → 点击 **抓取** → 等待列表加载 → 勾选需要下载的音轨 → 点击 **下载**。

### 2. 抓取普通网页资源
输入任意网页 URL → 抓取 → 筛选资源类型 → 勾选 → 下载。

### 3. 批量抓取多页面
在 URL 输入框中输入多个网址（用换行或逗号分隔），点击「抓取」即可并发抓取所有页面的资源，自动汇总去重。

---

## ⚠️ 注意事项

1. **HLS 合并输出格式为 TS**：目前 HLS 下载后合并为 `.ts` 文件，若需要 MP4/M4A 格式，建议使用 `ffmpeg -i input.ts output.mp4` 转换
2. **反爬站点**：部分站点有反爬机制，建议降低并发数
3. **asmr.one 抓取**：直接调用公开 API，无需登录

---

## 🐛 常见问题

**Q: 抓取失败，显示 `ConnectionError`？**
> 检查网络连接，部分站点需要代理。请确认目标站点在浏览器中可正常访问。

**Q: asmr.one 抓取不到资源？**
> 确认 URL 格式为 `https://www.asmr.one/work/RJxxxxxxx`，作品编号以 RJ 开头。

**Q: 下载速度慢？**
> 尝试增加并发数或更换网络环境。

---

## 📄 License

MIT License — 欢迎 Fork 和 Star！

---

## 🙏 致谢

- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — HTML/XML 解析
- [lxml](https://lxml.de/) — 高性能 XML/HTML 解析器
- [requests](https://requests.readthedocs.io/) — 优雅的 HTTP 库
- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/) — Python GUI 框架
- [PyInstaller](https://www.pyinstaller.org/) — Python 程序打包工具
