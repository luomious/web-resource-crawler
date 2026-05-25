# 🌐 Web Resource Crawler

**多功能网页资源抓取工具** — 支持图片、音频、视频、HLS 流媒体批量下载，Tkinter 精美暗色主题 GUI，开箱即用。

[简体中文](README.md) · [English](README_en.md)

---

## ✨ 功能特性

### 🔍 智能资源发现
- **10 层解析策略**：img 标签（含 14 种懒加载属性）→ video/audio → source 标签 → a 直链 → CSS/JS → JSON 播放器配置（6 种正则）→ 全文正则扫描 → CSS 背景图 → 文档链接 → 章节时间轴
- **JS 混淆解码**：内置 Dean Edwards Packer 反混淆（`eval(function(p,a,c,k,e,d){...})`），直接从混淆 JS 中提取 m3u8 地址
- **编码自动推断**：apparent_encoding + fallback UTF-8，覆盖各类中文站点
- **HTTP 容错**：自动重试 3 次，指数退避，429/5xx/429 状态码自动处理

### 📻 HLS 流媒体下载
- 自动解析 `.m3u8` 播放列表
- 16 线程并发下载 TS 分片
- 失败率 > 30% 自动丢弃并报错
- 分片合并为单个 TS 文件
- 检测到 HLS 资源时自动勾选

### ⏸ 完善的下载控制
- **暂停 / 继续**：下载过程中随时暂停，保留已下载分片
- **取消**：主动中止，清理临时文件
- **批量并行**：多资源同时下载，HLS 和普通文件混合调度
- **进度实时**：Canvas 滚动列表实时更新速度、进度百分比

### 🎨 精美界面
- **GitHub 风格暗色主题**（也可切换亮色）：#0d1117 深邃背景
- **浏览器地址栏风格** URL 输入框：下拉历史建议、Control+A 全选、↑↓导航
- **资源类型分类徽章**：🖼 图片 / 🎵 音频 / 📻 HLS 流 / 🎬 视频 / 🎨 CSS / ⚙ JS / 📄 文档
- **实时筛选**：按资源类型筛选，全选/取消快捷操作
- **侧边栏下载日志**：进行中 / 已完成标签页切换，右键删除记录
- **右键历史管理**：输入框右键删除单条历史记录
- **DPI 感知**：自动适配 HiDPI 屏幕（tk scaling 1.3）
- **配置持久化**：保存目录、并发数、超时、主题等写入 `%APPDATA%/WebScraper/config.json`，重启不丢

---

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

> 推荐使用 Python 3.12+，已测试 Python 3.13。

### 启动

```bash
python gui.py
```

### 打包为 EXE（单文件）

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name "网页资源爬虫" --add-data "core;core" gui.py
```

> 打包后 EXE 会在 `dist/` 目录。首次运行会自动在 `%APPDATA%/WebScraper/` 创建配置文件（重装不丢配置）。

---

## 📂 项目结构

```
web-resource-crawler/
├── gui.py              # Tkinter 图形界面（全部 UI 逻辑，单文件 1400+ 行）
├── core/
│   ├── scraper.py     # 网页抓取 + 资源解析 + 翻译（10 层提取策略）
│   └── downloader.py  # 并发下载 + HLS 分片合并 + 暂停/取消控制
├── requirements.txt    # Python 依赖
├── README.md           # 本文件
└── .gitignore
```

---

## 🛠 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| GUI | Tkinter（内置，无需安装） |
| 网页抓取 | `requests` + `BeautifulSoup4` + `lxml` |
| HLS 解析 | 纯 Python 手写，无 ffmpeg 依赖 |
| 并发 | `concurrent.futures.ThreadPoolExecutor` |
| 翻译 | `deep-translator`（Google 翻译） |
| 打包 | PyInstaller |
| 版本管理 | Git |

---

## 🔧 配置说明

启动后点击右上角 **⚙** 进入设置页面：

| 选项 | 说明 | 默认值 |
|------|------|--------|
| 默认保存目录 | 下载文件的存放路径 | 百度网盘 |
| 最大并发下载数 | 同时下载的资源数量 | 16 |
| 请求超时（秒） | 单次 HTTP 请求超时 | 30 |
| 检测到 HLS 自动勾选 | 抓取到 HLS 流时是否默认勾选 | ✅ 开启 |
| 界面主题 | 暗色 🌙 / 亮色 ☀ | 暗色 |

---

## 📖 使用示例

### 1. 抓取图片
在地址栏输入图片详情页 URL，点击 **🔍 抓取**，找到所有图片资源后勾选，点击 **⬇ 下载**。

### 2. 下载 HLS 流媒体
输入含 HLS 流的页面 URL → 抓取 → 自动检测到 m3u8 流并勾选 → 下载 → 自动合并为完整文件。

### 3. 批量下载多页面
用逗号或换行分隔多个 URL，一次抓取多个页面的资源。

---

## ⚠️ 注意事项

1. **HLS 合并输出格式为 TS**：目前 HLS 下载后合并为 `.ts` 文件，若需要 MP4/M4A 格式，建议使用 `ffmpeg -i input.ts output.mp4` 转换
2. **反爬站点**：部分站点有反爬机制，建议降低并发数（设置 → 并发下载 → 1~4）
4. **编码问题**：极少数站点编码特殊，抓取失败时可尝试手动指定编码或提 Issue

---

## 🐛 常见问题

**Q: 抓取失败，显示 `ConnectionError`？**
> 检查网络连接，部分站点需要代理。请确认目标站点在浏览器中可正常访问。

**Q: HLS 下载一直失败？**
> 部分站点 HLS 流需要特殊的 Referer 或 Cookie 头，当前版本暂不支持，可提 Issue 反馈。

**Q: 下载速度慢？**
> 尝试增加并发数（设置 → 最大并发下载数 → 16 或更高）。

**Q: 打包后 EXE 运行时界面显示异常？**
> 可能是 HiDPI 问题，请提交 Issue 并说明操作系统版本和屏幕分辨率。

---

## 📄 License

MIT License — 欢迎 Fork 和 Star！

---

## 🙏 致谢

- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — HTML/XML 解析
- [lxml](https://lxml.de/) — 高性能 XML/HTML 解析器
- [requests](https://requests.readthedocs.io/) — 优雅的 HTTP 库
- [deep-translator](https://github.com/nidhaloff/deep-translator) — 多语言翻译
- [PyInstaller](https://www.pyinstaller.org/) — Python 程序打包工具
