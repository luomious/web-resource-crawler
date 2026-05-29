"""
Web Resource Crawler — PyQt5 图形界面（View 层 + 轻量 Controller）。

架构说明：
    core/controller.py  — 纯业务逻辑（URL 规范、批量抓取、结果分类）
    本文件（gui.py）     — View + Qt 线程桥接（FetchWorker / DownloadWorker / MainWindow）
    core/scraper.py      — Facade → parser / fetcher / asmr_one / translator 等
    core/downloader.py   — 下载引擎
    core/config.py       — 配置持久化

遵循 MVC/MVP 模式：MainWindow 专心做 View，controller.py 处理纯逻辑。
"""

import sys
import json
import re
from urllib.parse import urlparse
import threading
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Any, Dict

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QListWidget,
    QListWidgetItem, QFrame, QMessageBox, QFileDialog, QTextEdit,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QHeaderView,
    QCompleter,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl, QStringListModel
from PyQt5.QtGui import QFont, QPalette, QColor, QPixmap

# 核心模块导入
sys.path.insert(0, str(Path(__file__).parent))
from core.fetcher import fetch_html
from core.parser import parse_resources, Resource
from core.downloader import download_all
from core.config import (
    get_config_int,
    load_config,
    save_config,
    load_history,
    save_history,
)
from core.constants import (
    HLS_DOWNLOAD_WORKERS,
    HLS_DOWNLOAD_WORKER_LIMIT,
    MAX_DOWNLOAD_WORKERS,
    APP_VERSION,
)
from core.controller import normalize_urls, fetch_resources, get_label_for_urls

_log = logging.getLogger("gui")

# ──────────────────────────────────────────────────────────────────
#  Worker 线程（Qt 桥接层 — 连接 core 模块和 UI）
# ──────────────────────────────────────────────────────────────────


class FetchWorker(QThread):
    """抓取工作线程。

    在后台线程中依次抓取多个 URL，通过 finished 信号将结果传回 UI 线程。
    asmr.one 的解析由 scraper 模块内部自动路由，本 Worker 无需特殊处理。

    Signals:
        finished(str, list[Resource]): (显示标签, 去重资源列表)
        error(str): 错误信息
    """
    finished = pyqtSignal(str, list)
    error = pyqtSignal(str)

    def __init__(self, urls: List[str]) -> None:
        """初始化抓取线程。

        Args:
            urls: 规范化后的 URL 列表。
        """
        super().__init__()
        self._urls: List[str] = urls

    def run(self) -> None:
        """执行抓取（在后台线程中运行，禁止直接操作 UI）。"""
        try:
            all_resources = fetch_resources(self._urls)
            label = get_label_for_urls(self._urls)
            self.finished.emit(label, all_resources)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            _log.error(f'[FetchWorker] 未捕获异常: {tb}')
            self.error.emit(f'抓取失败: {e}')


class DownloadWorker(QThread):
    """下载工作线程。

    将 Resource 列表交给 downloader 批量下载，通过 progress 信号推送进度，
    finished 信号返回分类后的结果。

    Signals:
        progress(int, int, str, int): (total, done, 文件名, 百分比)
        finished(list, list, list): (ok_list, fail_list, stop_list)
    """
    progress = pyqtSignal(int, int, str, int)
    finished = pyqtSignal(list, list, list)

    def __init__(
        self,
        resources: List[Resource],
        save_dir: Path,
        stop_flag: threading.Event,
        max_workers: int,
        hls_max_workers: int,
    ) -> None:
        """初始化下载线程。

        Args:
            resources: 待下载的 Resource 对象列表。
            save_dir: 保存目录。
            stop_flag: 停止信号（来自 UI 的 threading.Event）。
            max_workers: 批量下载并发数。
            hls_max_workers: HLS 分片并发数。
        """
        super().__init__()
        self._resources: List[Resource] = resources
        self._save_dir: Path = save_dir
        self._stop_flag: threading.Event = stop_flag
        self._max_workers: int = max_workers
        self._hls_max_workers: int = hls_max_workers
        self._progress_count: int = 0

    def run(self) -> None:
        """执行下载（在后台线程中运行）。"""
        def progress_cb(total: int, done: int, name: str) -> None:
            """下载进度回调（线程安全）。"""
            pct: int = min(int(done / total * 100), 100) if total else 0
            self._progress_count += 1
            # 节流：避免过于频繁的 UI 更新
            if self._progress_count % 15 == 0 or "OK" in name or "Done" in name:
                self.progress.emit(total, done, name, pct)

        try:
            results = download_all(
                self._resources,
                self._save_dir,
                stop_flag=self._stop_flag,
                progress_cb=progress_cb,
                max_workers=self._max_workers,
                hls_max_workers=self._hls_max_workers,
            )
        except Exception as e:
            import traceback as _tb
            _log.error(f'[DownloadWorker] 未捕获异常: {_tb.format_exc()}')
            failed = [(r.url, str(e)) for r in self._resources]
            self.finished.emit([], failed, [])
            return

        # 分类结果（交由 controller 层处理）
        from core.controller import classify_download_results, STOPPED_MARKER
        ok_list, fail_list, stop_list = classify_download_results(results)
        self.finished.emit(ok_list, fail_list, stop_list)


# ──────────────────────────────────────────────────────────────────
#  主窗口（View）
# ──────────────────────────────────────────────────────────────────


class _ImageLoadWorker(QThread):
    """图片预览加载线程。"""
    loaded = pyqtSignal(bytes)  # 图片数据
    failed = pyqtSignal()

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            import requests as req
            r = req.get(self._url, timeout=8, stream=True)
            r.raise_for_status()
            self.loaded.emit(r.content)
        except Exception:
            self.failed.emit()


class MainWindow(QMainWindow):
    """Web Resource Crawler 主窗口。

    负责：
        - UI 组件构建与布局
        - 主题切换
        - 用户交互事件的响应（创建 Worker、更新 UI 状态）
    """

    # 暗色主题样式表（VS Code 风格）
    _DARK_STYLE: str = """
        QMainWindow, QWidget { background: #2b2b2b; color: #d4d4d4; }
        QFrame { background: #353535; border: 1px solid #505050; border-radius: 4px; }
        QPushButton { background: #3c3c3c; color: #d4d4d4; border: 1px solid #505050;
                      border-radius: 4px; padding: 4px 12px; }
        QPushButton:hover { background: #4a4a4a; }
        QPushButton:pressed { background: #555555; }
        QPushButton:checked { background: #569cd6; color: #ffffff; border: 1px solid #569cd6; }
        QPushButton:disabled { background: #2b2b2b; color: #666666; border: 1px solid #3c3c3c; }
        QLineEdit { background: #3c3c3c; color: #d4d4d4; border: 1px solid #505050;
                    border-radius: 4px; padding: 4px 8px; }
        QLineEdit:focus { border: 1px solid #569cd6; }
        QTreeWidget, QListWidget, QTextEdit { background: #1e1e1e; color: #d4d4d4;
                                              border: 1px solid #505050; border-radius: 4px; }
        QTreeWidget::item { padding: 2px 0px; }
        QTreeWidget::item:selected { background: #094771; color: #ffffff; }
        QTreeWidget::item:hover { background: #2a2d2e; }
        QTreeWidget::branch { background: #1e1e1e; }
        QHeaderView::section { background: #353535; color: #d4d4d4;
                               border: 1px solid #505050; padding: 4px 8px;
                               font-weight: bold; }
        QProgressBar { background: #1e1e1e; border: 1px solid #505050;
                       border-radius: 4px; text-align: center; color: #d4d4d4;
                       min-height: 18px; }
        QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                              stop:0 #569cd6, stop:1 #4ec9b0); border-radius: 3px; }
        QLabel { color: #d4d4d4; }
        QMessageBox { background: #2b2b2b; }
        QMessageBox QLabel { color: #d4d4d4; }
        QToolTip { background: #353535; color: #d4d4d4; border: 1px solid #569cd6;
                   padding: 4px; border-radius: 4px; }
        QScrollBar:vertical {
            background: #1e1e1e; width: 10px; margin: 0px; }
        QScrollBar::handle:vertical {
            background: #505050; min-height: 30px; border-radius: 5px; }
        QScrollBar::handle:vertical:hover { background: #666666; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        QScrollBar:horizontal {
            background: #1e1e1e; height: 10px; margin: 0px; }
        QScrollBar::handle:horizontal {
            background: #505050; min-width: 30px; border-radius: 5px; }
        QScrollBar::handle:horizontal:hover { background: #666666; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
    """

    def __init__(self) -> None:
        """初始化主窗口，加载配置、构建 UI、应用主题。"""
        super().__init__()
        self.setWindowTitle("网页资源爬虫")
        self.setGeometry(100, 100, 1200, 800)

        # 加载配置
        cfg: dict = load_config()

        # 状态变量
        self.resources: List[Resource] = []
        self._downloading: bool = False
        self._stop_flag: threading.Event = threading.Event()
        self._history: List[str] = load_history()
        self._save_dir: Path = Path(cfg.get("save_dir", "E:/"))
        self._max_workers: int = get_config_int(
            cfg, "max_workers", MAX_DOWNLOAD_WORKERS, 1, HLS_DOWNLOAD_WORKER_LIMIT,
        )
        self._hls_max_workers: int = get_config_int(
            cfg, "hls_workers", HLS_DOWNLOAD_WORKERS, 1, HLS_DOWNLOAD_WORKER_LIMIT,
        )

        # Worker 引用
        self._fetch_worker: Optional[FetchWorker] = None
        self._dl_worker: Optional[DownloadWorker] = None
        self._img_worker: Optional[_ImageLoadWorker] = None

        # 下载管理中的条目映射
        self._dl_items: dict[str, QListWidgetItem] = {}
        self._global_item: Optional[QListWidgetItem] = None

        # 资源树中叶子节点 → Resource 的映射（用于快速查找）
        self._leaf_to_resource: Dict[int, Resource] = {}

        # 当前筛选类型
        self._current_filter: Optional[str] = None

        # 构建 UI
        self._build_ui()
        self._apply_theme(cfg.get("theme", "light") or "light")

        # 启用拖放
        self.setAcceptDrops(True)

        # 键盘快捷键
        self._setup_shortcuts()

    # ── 主题 ──────────────────────────────────────────────────

    def _toggle_theme(self) -> None:
        """切换暗色/亮色主题并持久化配置。"""
        current: str = getattr(self, "_theme", "light")
        new: str = "dark" if current == "light" else "light"
        self._apply_theme(new)

        cfg: dict = load_config()
        cfg["theme"] = new
        save_config(cfg)

    def _apply_theme(self, theme: str) -> None:
        """应用指定主题。

        Args:
            theme: 'dark' 或 'light'。
        """
        self._theme = theme
        if theme == "dark":
            self.setStyleSheet(self._DARK_STYLE)
            p: QPalette = self.palette()
            p.setColor(QPalette.Window, QColor(43, 43, 43))
            p.setColor(QPalette.WindowText, QColor(212, 212, 212))
            p.setColor(QPalette.Base, QColor(60, 60, 60))
            p.setColor(QPalette.Text, QColor(212, 212, 212))
            p.setColor(QPalette.Button, QColor(60, 60, 60))
            p.setColor(QPalette.ButtonText, QColor(212, 212, 212))
            p.setColor(QPalette.Highlight, QColor(86, 156, 214))
            self.setPalette(p)
            self._theme_btn.setText("\u2600\ufe0f 亮色")  # ☀️ 亮色
        else:
            self.setStyleSheet("QPushButton:checked { background: #0078d4; color: #ffffff; border: 1px solid #0078d4; border-radius: 4px; }")
            self.setPalette(QApplication.style().standardPalette())
            self._theme_btn.setText("\U0001f319 暗色")  # 🌙 暗色

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        """构建完整的 UI 布局（标题栏、URL 输入区、三栏主内容、状态栏）。"""
        central: QWidget = QWidget()
        self.setCentralWidget(central)
        root_layout: QVBoxLayout = QVBoxLayout(central)
        root_layout.setSpacing(6)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # ── 标题栏（含主题切换）──
        title_layout: QHBoxLayout = QHBoxLayout()
        title_label: QLabel = QLabel("\U0001f310  网页资源爬虫")
        title_label.setFont(QFont("Microsoft YaHei", 14))
        version_label: QLabel = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet("color: #888; font-size: 11px;")
        title_layout.addWidget(title_label)
        title_layout.addWidget(version_label)
        title_layout.addStretch()

        self._theme_btn: QPushButton = QPushButton("\U0001f319 暗色")
        self._theme_btn.setFixedWidth(80)
        self._theme_btn.clicked.connect(self._toggle_theme)
        title_layout.addWidget(self._theme_btn)
        root_layout.addLayout(title_layout)

        # ── URL 输入区 ──
        url_frame: QFrame = QFrame()
        url_frame.setFrameStyle(QFrame.StyledPanel)
        url_layout: QVBoxLayout = QVBoxLayout(url_frame)
        url_layout.addWidget(QLabel("网址 URL（多个用逗号或换行分隔）:"))

        input_row: QHBoxLayout = QHBoxLayout()
        self._url_input: QLineEdit = QLineEdit()
        self._url_input.setPlaceholderText("https://example.com")
        self._url_input.returnPressed.connect(self._on_fetch)
        self._url_completer: QCompleter = QCompleter(self._history, self)
        self._url_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._url_completer.setMaxVisibleItems(10)
        self._url_input.setCompleter(self._url_completer)
        input_row.addWidget(self._url_input)

        self._history_btn: QPushButton = QPushButton("\U0001f4c3")
        self._history_btn.setToolTip("URL 历史")
        self._history_btn.setFixedWidth(36)
        self._history_btn.clicked.connect(self._on_show_history)
        input_row.addWidget(self._history_btn)

        self._fetch_btn: QPushButton = QPushButton("\U0001f50d  抓 取")
        self._fetch_btn.setMinimumWidth(100)
        self._fetch_btn.clicked.connect(self._on_fetch)
        input_row.addWidget(self._fetch_btn)
        url_layout.addLayout(input_row)

        dir_row: QHBoxLayout = QHBoxLayout()
        dir_row.addWidget(QLabel(f"保存目录: {self._save_dir}"))
        change_dir_btn: QPushButton = QPushButton("\U0001f4c1 更换")
        change_dir_btn.clicked.connect(self._on_change_dir)
        dir_row.addWidget(change_dir_btn)
        dir_row.addStretch()
        url_layout.addLayout(dir_row)

        # 代理设置行
        proxy_row: QHBoxLayout = QHBoxLayout()
        proxy_row.addWidget(QLabel("代理:"))
        self._proxy_input: QLineEdit = QLineEdit()
        self._proxy_input.setPlaceholderText("http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
        self._proxy_input.setMaximumWidth(300)
        # 加载已保存的代理
        saved_proxy: str = load_config().get("proxy", "") or ""
        self._proxy_input.setText(saved_proxy)
        self._proxy_input.textChanged.connect(self._on_proxy_text_changed)
        proxy_row.addWidget(self._proxy_input)
        proxy_row.addWidget(QLabel("\U0001f4a1 留空=直连"))
        proxy_row.addStretch()
        url_layout.addLayout(proxy_row)
        root_layout.addWidget(url_frame)

        # ── 三栏主内容区 ──
        content_layout: QHBoxLayout = QHBoxLayout()

        # 左侧：下载管理
        left_layout: QVBoxLayout = QVBoxLayout()
        left_layout.addWidget(QLabel("\U0001f4e5 下载管理"))
        self._dl_list: QListWidget = QListWidget()
        self._dl_list.itemDoubleClicked.connect(self._on_dl_item_double_clicked)
        left_layout.addWidget(self._dl_list)
        content_layout.addLayout(left_layout, 1)

        # 中间：资源树
        mid_layout: QVBoxLayout = QVBoxLayout()

        filter_row: QHBoxLayout = QHBoxLayout()
        filter_row.addWidget(QLabel("筛选:"))
        self._filter_layout: QHBoxLayout = filter_row  # 保存引用，后续动态添加按钮
        self._filter_buttons: list[QPushButton] = []  # 动态筛选按钮列表
        self._filter_all_btn: QPushButton = QPushButton("全部")
        self._filter_all_btn.setCheckable(True)
        self._filter_all_btn.setChecked(True)
        self._filter_all_btn.clicked.connect(lambda: self._on_filter(None))
        filter_row.addWidget(self._filter_all_btn)
        filter_row.addStretch()
        mid_layout.addLayout(filter_row)

        self._res_tree: QTreeWidget = QTreeWidget()
        self._res_tree.setHeaderLabels(["名称", "类型"])
        self._res_tree.header().setStretchLastSection(False)
        self._res_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._res_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._res_tree.setColumnWidth(1, 80)
        self._res_tree.itemClicked.connect(self._on_preview)
        self._res_tree.itemChanged.connect(self._on_item_changed)
        mid_layout.addWidget(self._res_tree)

        action_row: QHBoxLayout = QHBoxLayout()
        action_row.addWidget(QPushButton("\u2611 全选", clicked=self._on_select_all))
        action_row.addWidget(QPushButton("\u2610 取消", clicked=self._on_select_none))
        self._count_label: QLabel = QLabel("已选 0 项")
        action_row.addWidget(self._count_label)

        self._progress: QProgressBar = QProgressBar()
        self._progress.setRange(0, 100)
        action_row.addWidget(self._progress)

        self._dl_btn: QPushButton = QPushButton("\u2b07  下 载")
        self._dl_btn.setMinimumWidth(100)
        self._dl_btn.clicked.connect(self._on_download)
        action_row.addWidget(self._dl_btn)

        self._stop_btn: QPushButton = QPushButton("\u23f9 停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_download)
        action_row.addWidget(self._stop_btn)
        mid_layout.addLayout(action_row)
        content_layout.addLayout(mid_layout, 3)

        # 右侧：预览
        right_layout: QVBoxLayout = QVBoxLayout()
        right_layout.addWidget(QLabel("\U0001f4d6 资源预览"))
        self._preview_area: QTextEdit = QTextEdit()
        self._preview_area.setReadOnly(True)
        self._preview_area.setMaximumHeight(200)
        right_layout.addWidget(self._preview_area)
        # 图片缩略图
        self._preview_image: QLabel = QLabel()
        self._preview_image.setAlignment(Qt.AlignCenter)
        self._preview_image.setMinimumHeight(150)
        self._preview_image.hide()  # 默认隐藏，点击图片资源时显示
        right_layout.addWidget(self._preview_image)
        # 音视频播放器（延迟初始化，因 QtMultimedia 可能不可用）
        self._media_player = None
        self._video_widget = None
        try:
            from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
            from PyQt5.QtMultimediaWidgets import QVideoWidget
            self._media_player = QMediaPlayer()
            self._video_widget = QVideoWidget()
            self._video_widget.setMinimumHeight(200)
            self._video_widget.hide()
            self._media_player.setVideoOutput(self._video_widget)
            right_layout.addWidget(self._video_widget)
        except ImportError:
            _log.info("[gui] QtMultimediaWidgets 不可用，音视频预览禁用")
        content_layout.addLayout(right_layout, 1)

        root_layout.addLayout(content_layout, 1)

        # ── 状态栏 ──
        self._status_label: QLabel = QLabel("就绪")
        root_layout.addWidget(self._status_label)

    # ── 资源树构建 ───────────────────────────────────────────

    def _build_resource_tree(self, resources: List[Resource]) -> None:
        """将 Resource 列表按类型分组构建为树形结构。

        顶层按资源类型（r.rtype）分组，创建带 emoji 的类型文件夹节点
        （如 🖼️ 图片、🎵 音频）。类型文件夹下：
        - 无路径资源：再按来源域名创建子文件夹，文件挂在域名下
        - 有路径资源（如 asmr.one）：保持原有路径层级展开

        Args:
            resources: 抓取到的资源列表。
        """
        self._res_tree.blockSignals(True)
        self._res_tree.clear()
        self._leaf_to_resource.clear()

        folder_nodes: Dict[str, QTreeWidgetItem] = {}  # path_str → node

        for r in resources:
            # 筛选过滤
            if self._current_filter is not None and r.rtype != self._current_filter:
                continue

            # ── 1. 顶层类型文件夹 ──
            rtype = r.rtype or "其他"
            type_key = f"__type__{rtype}"
            type_emoji = self._TYPE_EMOJI.get(rtype, "📁")
            type_label = f"{type_emoji} {rtype}"

            if type_key in folder_nodes:
                type_node = folder_nodes[type_key]
            else:
                type_node = QTreeWidgetItem(self._res_tree, [type_label, ""])
                type_node.setData(0, Qt.UserRole, None)
                type_node.setCheckState(0, Qt.Unchecked)
                type_node.setExpanded(False)
                folder_nodes[type_key] = type_node

            # ── 2. 类型下的子结构 ──
            parts = r.name.split("/")
            if len(parts) == 1:
                # 无路径 — 按来源域名再分组
                source_key = ""
                if r.source:
                    parsed = urlparse(r.source)
                    domain = parsed.netloc or parsed.path
                    source_key = f"{type_key}/__source__{domain}"

                if source_key and source_key in folder_nodes:
                    parent = folder_nodes[source_key]
                elif source_key:
                    domain_item = QTreeWidgetItem(type_node, [f"📄 {domain}", ""])
                    domain_item.setData(0, Qt.UserRole, None)
                    domain_item.setCheckState(0, Qt.Unchecked)
                    domain_item.setExpanded(False)
                    folder_nodes[source_key] = domain_item
                    parent = domain_item
                else:
                    parent = type_node

                leaf = QTreeWidgetItem(parent, [r.name, r.rtype])
                leaf.setData(0, Qt.UserRole, r)
                leaf.setCheckState(0, Qt.Unchecked)
                self._leaf_to_resource[id(leaf)] = r
            else:
                # 有路径 — 保持原有层级，挂在类型节点下
                parent: QTreeWidgetItem = type_node
                path_so_far: str = type_key
                for part in parts[:-1]:
                    path_so_far = f"{path_so_far}/{part}"
                    if path_so_far in folder_nodes:
                        parent = folder_nodes[path_so_far]
                    else:
                        folder_item = QTreeWidgetItem(parent, [f"📁 {part}", ""])
                        folder_item.setData(0, Qt.UserRole, None)
                        folder_item.setCheckState(0, Qt.Unchecked)
                        folder_item.setExpanded(False)
                        folder_nodes[path_so_far] = folder_item
                        parent = folder_item

                # 叶子节点
                leaf = QTreeWidgetItem(parent, [parts[-1], r.rtype])
                leaf.setData(0, Qt.UserRole, r)
                leaf.setCheckState(0, Qt.Unchecked)
                self._leaf_to_resource[id(leaf)] = r

        self._res_tree.blockSignals(False)
        self._update_count()

    # ── 抓取流程 ─────────────────────────────────────────────

    def _on_fetch(self) -> None:
        """点击「抓取」按钮：规范化 URL → 更新历史 → 启动 FetchWorker。"""
        raw: str = self._url_input.text().strip()
        if not raw:
            return

        urls: List[str] = normalize_urls(raw)
        if not urls:
            return

        # 更新历史
        if urls[0] not in self._history:
            self._history.insert(0, urls[0])
            self._history = self._history[:50]
            save_history(self._history)
            self._url_completer.setModel(QStringListModel(self._history))

        # 清空上一轮结果
        self._res_tree.clear()
        self._leaf_to_resource.clear()
        self._preview_area.clear()
        self._status_label.setText(f"\u23f3 正在抓取 {len(urls)} 个网页...")

        # 启动抓取线程
        self._fetch_btn.setEnabled(False)
        self._dl_btn.setEnabled(False)
        self._fetch_worker = FetchWorker(urls)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    # ── 筛选按钮动态生成 ───────────────────────────────────

    # 资源类型 → emoji 映射
    _TYPE_EMOJI: Dict[str, str] = {
        "图片": "🖼️",
        "音频": "🎵",
        "视频": "🎬",
        "音频-HLS": "📻",
        "样式": "🎨",
        "脚本": "📜",
        "文档": "📄",
        "字幕": "💬",
        "其他": "❓",
    }

    def _update_filter_buttons(self, resources: List[Resource]) -> None:
        """根据抓取结果动态生成类型筛选按钮。

        清除旧按钮后，统计资源中出现的类型，生成带 emoji + 数量的筛选按钮。

        Args:
            resources: 当前资源列表。
        """
        # 清除旧按钮（保留“全部”按钮和 addStretch）
        for btn in self._filter_buttons:
            self._filter_layout.removeWidget(btn)
            btn.deleteLater()
        self._filter_buttons.clear()

        # 统计各类型数量
        type_counts: Dict[str, int] = {}
        for r in resources:
            type_counts[r.rtype] = type_counts.get(r.rtype, 0) + 1

        # 按数量降序排列
        sorted_types = sorted(type_counts.items(), key=lambda x: -x[1])

        # 在“全部”按钮和 addStretch 之间插入新按钮
        # layout 顺序: Label, 全部按钮, ..., addStretch
        insert_index = 2  # 插入到“全部”按钮之后
        for rtype, count in sorted_types:
            emoji = self._TYPE_EMOJI.get(rtype, "")
            btn = QPushButton(f"{emoji} {rtype} ({count})")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, t=rtype: self._on_filter(t))
            self._filter_layout.insertWidget(insert_index, btn)
            self._filter_buttons.append(btn)
            insert_index += 1

    def _on_fetch_error(self, msg: str) -> None:
        """FetchWorker 异常回调。"""
        self._fetch_btn.setEnabled(True)
        self._dl_btn.setEnabled(True)
        self._status_label.setText(f"\u274c {msg}")
        QMessageBox.warning(self, "抓取失败", msg)

    def _on_fetch_done(self, label: str, resources: List[Resource]) -> None:
        """FetchWorker 完成回调：构建资源树 + 更新筛选按钮。"""
        self._fetch_btn.setEnabled(True)
        self._dl_btn.setEnabled(True)
        self.resources = resources
        self._current_filter = None
        self._status_label.setText(f"\u2705 找到 {len(resources)} 个资源")

        self._update_filter_buttons(resources)
        self._build_resource_tree(resources)

    # ── 资源树交互 ───────────────────────────────────────────

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """树节点勾选状态变化时：级联父子节点。

        - 父节点勾选 → 所有子节点勾选
        - 父节点取消 → 所有子节点取消
        - 子节点变化 → 更新父节点状态（全选/部分/无）

        Args:
            item: 状态变化的树节点。
            column: 变化的列（0 = 名称列含 checkbox）。
        """
        if column != 0:
            return

        self._res_tree.blockSignals(True)

        check_state = item.checkState(0)

        # 级联到子节点
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, check_state)

        # 更新父节点状态
        self._update_parent_check(item)

        self._res_tree.blockSignals(False)
        self._update_count()

    def _update_parent_check(self, item: QTreeWidgetItem) -> None:
        """根据子节点勾选状态更新父节点的 checkState。

        规则：所有子节点勾选 → 父勾选；所有取消 → 父取消；否则部分勾选（显示为未选）。

        Args:
            item: 需要向上更新父节点的子节点。
        """
        parent = item.parent()
        if parent is None:
            return

        child_count = parent.childCount()
        checked = sum(
            1 for i in range(child_count)
            if parent.child(i).checkState(0) == Qt.Checked
        )

        self._res_tree.blockSignals(True)
        if checked == 0:
            parent.setCheckState(0, Qt.Unchecked)
        elif checked == child_count:
            parent.setCheckState(0, Qt.Checked)
        else:
            parent.setCheckState(0, Qt.PartiallyChecked)
        self._res_tree.blockSignals(False)

        # 递归向上
        self._update_parent_check(parent)

    def _on_filter(self, rtype: Optional[str]) -> None:
        """按资源类型筛选列表，更新按钮选中状态。

        Args:
            rtype: 类型字符串（如 '图片'）；None 表示显示全部。
        """
        self._current_filter = rtype

        # 更新按钮选中状态
        self._filter_all_btn.setChecked(rtype is None)
        for btn in self._filter_buttons:
            # 从按钮文本中提取类型名（去掉 emoji 和计数）
            btn_rtype = btn.text().split(" ")[-2] if " (" in btn.text() else btn.text()
            btn.setChecked(btn_rtype == rtype)

        self._build_resource_tree(self.resources)

    def _on_select_all(self) -> None:
        """全选资源树中的所有叶子节点。"""
        self._res_tree.blockSignals(True)
        it = QTreeWidgetItemIterator(self._res_tree)
        while it.value():
            item = it.value()
            if id(item) in self._leaf_to_resource:
                item.setCheckState(0, Qt.Checked)
            it += 1
        # 更新所有文件夹节点状态
        self._sync_all_folder_checks()
        self._res_tree.blockSignals(False)
        self._update_count()

    def _on_select_none(self) -> None:
        """取消全选。"""
        self._res_tree.blockSignals(True)
        it = QTreeWidgetItemIterator(self._res_tree)
        while it.value():
            item = it.value()
            item.setCheckState(0, Qt.Unchecked)
            it += 1
        self._res_tree.blockSignals(False)
        self._update_count()

    def _sync_all_folder_checks(self) -> None:
        """同步所有文件夹节点的勾选状态（从叶子向上传播）。"""
        # 收集所有叶子，然后逐层更新父节点
        leaves: List[QTreeWidgetItem] = []
        it = QTreeWidgetItemIterator(self._res_tree)
        while it.value():
            item = it.value()
            if id(item) in self._leaf_to_resource:
                leaves.append(item)
            it += 1

        # 从叶子向上递归更新
        updated_parents: set = set()
        for leaf in leaves:
            parent = leaf.parent()
            while parent is not None and id(parent) not in updated_parents:
                self._update_parent_check(leaf)
                updated_parents.add(id(parent))
                parent = parent.parent()

    def _update_count(self) -> None:
        """更新「已选 N 项」标签。"""
        checked = 0
        it = QTreeWidgetItemIterator(self._res_tree)
        while it.value():
            item = it.value()
            if id(item) in self._leaf_to_resource and item.checkState(0) == Qt.Checked:
                checked += 1
            it += 1
        self._count_label.setText(f"已选 {checked} 项")

    def _on_preview(self, item: QTreeWidgetItem, column: int) -> None:
        """点击资源树项：右侧面板显示详细信息 + 内嵌预览。

        图片 → QPixmap 缩略图
        音频 → QMediaPlayer 播放
        视频 → QMediaPlayer + QVideoWidget 播放
        HLS  → 显示 m3u8 信息（不可直接预览）
        其他 → 文本详情

        Args:
            item: 被点击的 QTreeWidgetItem。
            column: 点击的列号。
        """
        # 停止上一次播放
        if self._media_player:
            self._media_player.stop()
        self._preview_image.hide()
        if self._video_widget:
            self._video_widget.hide()

        r: Optional[Resource] = item.data(0, Qt.UserRole)
        if r is None:
            # 文件夹节点 — 显示文件夹信息
            name = item.text(0)
            child_count = item.childCount()
            self._preview_area.setHtml(f"""
            <b>📁 文件夹</b><br><br>
            <b>名称:</b> {name}<br><br>
            <b>包含:</b> {child_count} 项<br>
            """)
            return

        # 基本信息
        info_html = f"""
        <b>{self._TYPE_EMOJI.get(r.rtype, '')} {r.rtype}</b><br><br>
        <b>文件名:</b> {r.name}<br><br>
        <b>URL:</b><br><small>{r.url}</small><br><br>
        <b>来源:</b> {getattr(r, 'source', '')}<br>
        """

        # 按类型嵌入预览
        if r.rtype == "图片":
            # 尝试加载缩略图
            pixmap = QPixmap()
            # 先尝试从网络加载（非阻塞，QPixmap 不支持直接从 URL 加载）
            # 方案：后台下载小图，加载到 QPixmap
            self._preview_image.setPixmap(pixmap)
            self._preview_image.show()
            self._preview_image.setText("⏳ 加载中...")
            # 异步加载图片
            self._load_preview_image(r.url)
            info_html += "<hr><p><small>🖼️ 图片预览</small></p>"
        elif r.rtype == "音频":
            if self._media_player:
                from PyQt5.QtMultimedia import QMediaContent
                self._media_player.setMedia(QMediaContent(QUrl(r.url)))
                self._media_player.play()
                info_html += "<hr><p><small>🎵 正在播放音频预览</small></p>"
            else:
                info_html += "<hr><p style=\"color:#888;\">🎵 音频预览不可用（缺少 QtMultimedia）</p>"
        elif r.rtype == "视频":
            if self._media_player and self._video_widget:
                from PyQt5.QtMultimedia import QMediaContent
                self._video_widget.show()
                self._media_player.setMedia(QMediaContent(QUrl(r.url)))
                self._media_player.play()
                info_html += "<hr><p><small>🎬 正在播放视频预览</small></p>"
            else:
                info_html += "<hr><p style=\"color:#888;\">🎬 视频预览不可用（缺少 QtMultimediaWidgets）</p>"
        elif "HLS" in r.rtype:
            info_html += "<hr><p style=\"color:#888;\">📻 HLS 流媒体 — 不支持在线预览，下载后播放</p>"

        self._preview_area.setHtml(info_html)

    def _load_preview_image(self, url: str) -> None:
        """后台加载图片并显示到预览区。

        Args:
            url: 图片 URL。
        """
        self._img_worker = _ImageLoadWorker(url)
        self._img_worker.loaded.connect(self._on_preview_image_loaded)
        self._img_worker.failed.connect(lambda: self._preview_image.setText("❌ 图片加载失败"))
        self._img_worker.start()

    def _on_preview_image_loaded(self, data: bytes) -> None:
        """图片加载完成回调（UI 线程执行）。

        Args:
            data: 图片二进制数据。
        """
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self._preview_image.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._preview_image.setPixmap(scaled)
        else:
            self._preview_image.setText("❌ 图片加载失败")

    # ── 下载流程 ─────────────────────────────────────────────

    def _get_checked_resources(self) -> List[Resource]:
        """从资源树中收集所有勾选的叶子资源。

        Returns:
            勾选的 Resource 列表。
        """
        checked: List[Resource] = []
        it = QTreeWidgetItemIterator(self._res_tree)
        while it.value():
            item = it.value()
            if id(item) in self._leaf_to_resource and item.checkState(0) == Qt.Checked:
                r = item.data(0, Qt.UserRole)
                if r is not None:
                    checked.append(r)
            it += 1
        return checked

    def _on_download(self) -> None:
        """点击「下载」按钮：收集勾选资源 → 启动 DownloadWorker。"""
        checked = self._get_checked_resources()

        if not checked:
            QMessageBox.information(self, "提示", "请先勾选要下载的资源")
            return

        self._save_dir.mkdir(parents=True, exist_ok=True)
        self._downloading = True
        self._stop_flag.clear()
        self._status_label.setText("\U0001f4fb 开始下载...")
        self._dl_list.clear()

        # 禁用抓取/下载按钮，启用停止按钮
        self._fetch_btn.setEnabled(False)
        self._dl_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        # 构建下载条目列表（用 URL 作 key，避免文件名截取匹配不可靠）
        self._dl_items = {}
        self._dl_name_map = {}  # url → display name
        for r in checked:
            item: QListWidgetItem = QListWidgetItem(f"\u2b07 {r.name}")
            self._dl_list.addItem(item)
            self._dl_items[r.url] = item
            self._dl_name_map[r.url] = r.name

        # 总进度条目
        self._dl_list.addItem("\u2501" * 15)
        self._global_item = QListWidgetItem("总进度: 0%")
        self._dl_list.addItem(self._global_item)

        # 启动下载线程
        self._dl_worker = DownloadWorker(
            checked,
            self._save_dir,
            self._stop_flag,
            self._max_workers,
            self._hls_max_workers,
        )
        self._dl_worker.progress.connect(self._on_download_progress)
        self._dl_worker.finished.connect(self._on_download_done)
        self._dl_worker.start()

    def _on_download_progress(
        self, total: int, done: int, name: str, pct: int
    ) -> None:
        """下载进度回调：更新进度条和文件条目文本。

        使用 URL 精确匹配下载条目，替代之前的文件名截取匹配。

        Args:
            total: 资源总数。
            done: 已完成数。
            name: 当前下载中的文件名或进度信息。
            pct: 完成百分比（0-100）。
        """
        self._progress.setValue(pct)

        # 尝试通过 URL 精确匹配条目
        matched: bool = False
        for url, item in list(self._dl_items.items()):
            display = self._dl_name_map.get(url, url)
            # 进度回调的 name 包含文件名或 OK 信息，用 URL 片段匹配
            if url in name or display[:20] in name or name[:20] in display:
                prefix: str = "\u2705" if pct >= 100 else "\u2b07"
                item.setText(f"{prefix} {display[:30]} [{pct}%]")
                matched = True
                break

        # fallback：更新第一个仍显示下载中的条目
        if not matched and self._dl_items:
            for url, item in self._dl_items.items():
                if "\u2b07" in item.text():
                    display = self._dl_name_map.get(url, url)
                    item.setText(f"\u2b07 {display[:30]} [{pct}%]")
                    break

        if self._global_item is not None:
            total_pct: int = int(done / total * 100) if total else 0
            self._global_item.setText(
                f"总进度: [{done}/{total}] {total_pct}% — {name[:25]}"
            )
        self._status_label.setText(f"\U0001f4e5 [{done}/{total}] {name[:30]}")

    def _on_download_done(
        self,
        ok_list: List[Tuple[str, str, int]],
        fail_list: List[Tuple[str, str]],
        stop_list: List[Tuple[str, str]],
    ) -> None:
        """下载完成回调：显示最终结果 + 系统通知。

        Args:
            ok_list: [(url, path, filesize), ...] 成功条目。
            fail_list: [(url, error), ...] 失败条目。
            stop_list: [(url, marker), ...] 被停止的条目。
        """
        self._downloading = False
        self._progress.setValue(100)

        # 恢复按钮状态
        self._fetch_btn.setEnabled(True)
        self._dl_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

        self._dl_list.clear()
        for _, path, sz in ok_list:
            fname: str = Path(path).name
            if sz > 1024 * 1024:
                sz_str: str = f"{sz / 1024 / 1024:.1f}MB"
            else:
                sz_str = f"{sz / 1024:.0f}KB"
            self._dl_list.addItem(f"\u2705 {fname} ({sz_str})")

        for _, err in fail_list:
            self._dl_list.addItem(f"\u274c {err[:60]}")

        self._status_label.setText(
            f"\u2705 完成: 成功 {len(ok_list)}, 失败 {len(fail_list)}"
        )

        # 系统托盘通知（窗口最小化时特别有用）
        self._show_tray_notification(len(ok_list), len(fail_list))

        QMessageBox.information(
            self, "下载结果",
            f"成功: {len(ok_list)} 项\n失败: {len(fail_list)} 项",
        )

    def _show_tray_notification(self, ok_count: int, fail_count: int) -> None:
        """显示系统托盘通知。

        Args:
            ok_count: 成功下载数。
            fail_count: 失败下载数。
        """
        try:
            from PyQt5.QtWidgets import QSystemTrayIcon
            if QSystemTrayIcon.isSystemTrayAvailable():
                tray = QSystemTrayIcon(self)
                # 使用应用图标或默认图标
                from PyQt5.QtGui import QIcon
                tray.setIcon(self.windowIcon() or QApplication.style().standardIcon(QApplication.style().SP_ComputerIcon))
                tray.show()
                title = "下载完成"
                msg = f"成功: {ok_count} 项"
                if fail_count > 0:
                    msg += f", 失败: {fail_count} 项"
                tray.showMessage(title, msg, QSystemTrayIcon.Information, 3000)
                # 延迟隐藏托盘图标
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(4000, tray.hide)
        except Exception:
            pass  # 托盘不可用时静默忽略

    def _on_stop_download(self) -> None:
        """点击「停止」按钮：设置停止标志通知 Worker 中止。"""
        self._stop_flag.set()
        self._status_label.setText("\u23f9 正在停止...")

    def _on_change_dir(self) -> None:
        """点击「更换」按钮：选择新的保存目录。"""
        directory: str = QFileDialog.getExistingDirectory(
            self, "选择保存目录", str(self._save_dir),
        )
        if directory:
            self._save_dir = Path(directory)
            cfg: dict = load_config()
            cfg["save_dir"] = directory
            save_config(cfg)
            self._status_label.setText(f"保存目录: {directory}")

    def _on_proxy_text_changed(self, text: str) -> None:
        """代理输入变更时启动防抖计时器（500ms 后保存）。"""
        if not hasattr(self, '_proxy_timer'):
            from PyQt5.QtCore import QTimer
            self._proxy_timer = QTimer()
            self._proxy_timer.setSingleShot(True)
            self._proxy_timer.timeout.connect(self._on_proxy_changed)
        self._proxy_timer.start(500)

    def _on_proxy_changed(self) -> None:
        """代理输入防抖回调：保存到配置。"""
        text = self._proxy_input.text()
        cfg = load_config()
        cfg["proxy"] = text.strip()
        save_config(cfg)
        if text.strip():
            self._status_label.setText(f"\U0001f310 代理已设置: {text.strip()}")
        else:
            self._status_label.setText("\U0001f310 直连（无代理）")

    # ── 拖放 URL ──────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        """拖入事件：接受包含 URL 或文本的拖放。"""
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        """放下事件：提取 URL 填入输入框。"""
        mime = event.mimeData()
        urls: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                s = url.toString()
                if s.startswith(("http://", "https://")):
                    urls.append(s)
        if not urls and mime.hasText():
            for line in mime.text().strip().splitlines():
                line = line.strip()
                if line.startswith(("http://", "https://")):
                    urls.append(line)
        if urls:
            self._url_input.setText(", ".join(urls))
            self._status_label.setText(f"📥 已拖入 {len(urls)} 个 URL")

    # ── 双击下载项打开文件位置 ─────────────────────────────────

    def _on_dl_item_double_clicked(self, item: QListWidgetItem) -> None:
        """双击下载管理列表项：打开文件所在目录。

        Args:
            item: 被双击的列表项。
        """
        text = item.text()
        # 成功项格式: ✅ 文件名 (大小)
        if not text.startswith("\u2705"):
            return
        # 提取文件名
        fname = text.lstrip("\u2705 ").rsplit(" (", 1)[0].strip()
        if not fname:
            return
        # 在保存目录中查找
        target = self._save_dir / fname
        if not target.exists():
            # 递归搜索子目录
            for p in self._save_dir.rglob(fname):
                target = p
                break
        if target.exists():
            import subprocess
            # Windows: 选中文件并打开所在目录
            subprocess.Popen(f'explorer /select,"{target}"')

    # ── URL 历史弹出菜单 ─────────────────────────────────────

    def _on_show_history(self) -> None:
        """点击历史按钮：弹出菜单，列出历史 URL，点击选用，底部可清除。"""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        if not self._history:
            act = menu.addAction("（无历史记录）")
            act.setEnabled(False)
        else:
            for url in self._history[:20]:
                display = url if len(url) <= 60 else url[:57] + "..."
                action = menu.addAction(display)
                action.setData(url)
                action.triggered.connect(self._on_pick_history)
            menu.addSeparator()
            clear_act = menu.addAction("🗑 清除历史")
            clear_act.triggered.connect(self._on_clear_history)
        menu.exec_(self._history_btn.mapToGlobal(self._history_btn.rect().bottomLeft()))

    def _on_pick_history(self) -> None:
        """选中历史 URL → 填入输入框。"""
        action = self.sender()
        if action and action.data():
            self._url_input.setText(action.data())
            self._url_input.setFocus()

    def _on_clear_history(self) -> None:
        """清除全部 URL 历史。"""
        reply = QMessageBox.question(
            self, "清除历史",
            "确定要清除所有 URL 历史记录吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._history.clear()
            save_history(self._history)
            self._url_completer.setModel(QStringListModel(self._history))
            self._status_label.setText("🗑 URL 历史已清除")

    # ── 键盘快捷键 ─────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        """注册全局键盘快捷键。"""
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        # Ctrl+Enter: 抓取
        QShortcut(QKeySequence("Ctrl+Return"), self, self._on_fetch)
        # Ctrl+D: 下载
        QShortcut(QKeySequence("Ctrl+D"), self, self._on_download)
        # Escape: 停止下载
        QShortcut(QKeySequence("Escape"), self, self._on_stop_download)

    # ── 关闭窗口确认 ──────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """关闭窗口时：若正在下载，弹出确认对话框。"""
        if self._downloading:
            reply = QMessageBox.question(
                self, "确认关闭",
                "正在下载中，关闭窗口将中断下载。\n确定要关闭吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            # 用户确认关闭，停止下载
            self._stop_flag.set()
        elif self._fetch_worker is not None and self._fetch_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认关闭",
                "正在抓取中，关闭窗口将中断操作。\n确定要关闭吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()


# ──────────────────────────────────────────────────────────────────
#  入口
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 全局异常钩子：将未捕获异常完整 traceback 写入日志文件
    _orig_excepthook = sys.excepthook

    # 日志路径：exe 同目录（PyInstaller --windowed 下 Path.home() 可能异常）
    if getattr(sys, 'frozen', False):
        _log_dir = Path(sys.executable).parent
    else:
        _log_dir = Path.cwd()
    _crash_log = _log_dir / "web_crawler_crash.log"

    def _global_excepthook(exc_type, exc_value, exc_tb):
        import traceback as _tb
        tb_text = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        # 写入日志文件（多路径尝试）
        for log_path in [_crash_log, Path.home() / "web_crawler_crash.log", Path.cwd() / "web_crawler_crash.log"]:
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    import datetime as _dt
                    f.write(f"\n{'='*60}\n{_dt.datetime.now():%Y-%m-%d %H:%M:%S}\n{tb_text}")
                break  # 写成功就停
            except Exception:
                continue
        # 尝试弹窗显示完整错误
        try:
            if QApplication.instance() is None:
                app = QApplication(sys.argv)
            QMessageBox.critical(None, "错误", f"未捕获异常:\n\n{tb_text[:2000]}")
        except Exception:
            pass
        # 最后才调原始钩子（PyInstaller --windowed 可能直接退出）
        _orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _global_excepthook

    # QThread 未捕获异常钩子
    def _qthread_excepthook(exc_type, exc_value, exc_tb):
        import traceback as _tb
        tb_text = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        for log_path in [_crash_log, Path.home() / "web_crawler_crash.log", Path.cwd() / "web_crawler_crash.log"]:
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    import datetime as _dt
                    f.write(f"\n{'='*60}\n{_dt.datetime.now():%Y-%m-%d %H:%M:%S} [QThread]\n{tb_text}")
                break
            except Exception:
                continue

    # PyQt5 QThread 的 uncaught exception 默认走 sys.excepthook
    # 但 --windowed 模式下 PyInstaller 覆盖了 sys.excepthook，所以需要恢复

    app: QApplication = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    window: MainWindow = MainWindow()
    window.show()
    sys.exit(app.exec_())
