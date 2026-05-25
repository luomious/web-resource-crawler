"""
网页资源爬虫 — 精美 Tkinter GUI v4
启动: python gui.py
"""
import json
import pathlib
import re
import threading
from urllib.parse import urlparse

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ── 导入核心模块 ──────────────────────────────────────────
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from core.scraper import fetch_html, parse_resources, Resource
from core.downloader import download_all

# ══════════════════════════════════════════════════════════
#  配置文件持久化（%APPDATA% — EXE 重启不丢）
# ══════════════════════════════════════════════════════════
import os as _os
if getattr(sys, 'frozen', False):
    # PyInstaller EXE → 存到 AppData/Roaming
    _appdata = pathlib.Path(_os.environ.get("APPDATA", pathlib.Path.home() / "AppData" / "Roaming"))
    _config_dir = _appdata / "WebScraper"
else:
    # 开发环境 → 项目目录
    _config_dir = pathlib.Path(__file__).parent
_config_dir.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = _config_dir / "config.json"

def _load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}

def _save_config(cfg: dict):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _load_history() -> list[str]:
    urls = _load_config().get("history", [])
    if isinstance(urls, list):
        return [u for u in urls if isinstance(u, str) and u.strip()]
    return []

def _save_history(urls: list[str]):
    cfg = _load_config()
    cfg["history"] = urls[:50]
    _save_config(cfg)

def _load_save_dir() -> str | None:
    return _load_config().get("save_dir")

def _save_save_dir(path: str):
    cfg = _load_config()
    cfg["save_dir"] = path
    _save_config(cfg)

# ══════════════════════════════════════════════════════════
#  配色方案
# ══════════════════════════════════════════════════════════
BG0   = "#0d1117"   # 最深背景
BG1   = "#161b22"   # 卡片背景
BG2   = "#21262d"   # 行悬停
BORDER= "#30363d"   # 边框
FG    = "#e6edf3"   # 主文字
FG2   = "#8b949e"   # 次要文字
FG3   = "#484f58"   # 黯淡文字
GREEN = "#3fb950"   # 成功/下载
BLUE  = "#58a6ff"   # 链接/HLS
RED   = "#f85149"   # 错误
ORANGE= "#d29922"   # 警告
PURPLE= "#a371f7"   # 音频

TYPE_ICONS = {
    "图片": "🖼", "音频": "🎵", "音频-HLS": "📻", "视频": "🎬",
    "样式": "🎨", "脚本": "⚙", "文档": "📄", "其他": "📎",
}
TYPE_COLORS = {
    "图片": "#79c0ff", "音频": "#d2a8ff", "音频-HLS": "#56d364",
    "视频": "#ffa657", "样式": "#56d364", "脚本": "#e3b341",
    "文档": "#ff7b72", "其他": "#8b949e",
}

FONT = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)
PAD = 6
PAD2 = 4


# ══════════════════════════════════════════════════════════
# 应用主类
# ══════════════════════════════════════════════════════════
class ScraperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("网页资源爬虫")
        root.geometry("1100x720")
        root.minsize(800, 500)
        root.configure(bg=BG0)

        # 状态
        self.resources: list[Resource] = []
        self.checked_count = 0
        self.fetching = False
        self.downloading = False
        self.paused = False
        self.stop_flag = threading.Event()
        self.pause_event = threading.Event()
        saved_dir = _load_save_dir()
        if saved_dir and pathlib.Path(saved_dir).exists():
            self.save_dir = pathlib.Path(saved_dir)
        else:
            self.save_dir = pathlib.Path("E:/百度网盘")
        self._fetch_thread = None
        self._dl_thread = None
        self.history = _load_history()
        self.download_log = []  # [(url, filename, status, size_str), ...]
        self.download_tab = "进行中"  # 下载侧边栏当前标签页
        self._pending_fetch_result = None  # 共享抓取结果
        self._dl_progress_info = [0, 0, "", 0]  # [total, done, name, pct] 线程写入，定时器读取

        # 加载设置
        self.settings = _load_config().get("settings", {})
        self.settings.setdefault("max_workers", 16)
        self.settings.setdefault("timeout", 30)
        self.settings.setdefault("auto_check_hls", True)
        self.settings.setdefault("theme", "dark")
        self._apply_settings()

        self._build_ui()
        self._start_polling()  # 启动统一轮询，线程安全刷新 UI

    def _start_polling(self):
        """200ms 定时器，从线程共享变量读取最新状态并刷新 UI"""
        try:
            # 检查抓取结果
            if self._pending_fetch_result:
                label, resources = self._pending_fetch_result
                self._pending_fetch_result = None
                self._on_fetch_result(label, resources)

            # 检查下载进度
            info = self._dl_progress_info
            if info[0] > 0:
                total, done, name, pct = info
                self.progress["value"] = pct
                self.lbl_progress.config(text=f"{pct}%")
                color = GREEN if "✅" in name else BLUE
                self.lbl_status.config(
                    text=f"📥 [{done}/{total}] {name[:35]}", fg=color)
        except Exception:
            pass  # 轮询器永不崩溃
        self.root.after(200, self._start_polling)

    # ── UI 构建 ──────────────────────────────────────────
    def _build_ui(self):
        # 顶部标题栏
        top_bar = tk.Frame(self.root, bg=BG1, height=48)
        top_bar.pack(fill="x")
        top_bar.pack_propagate(False)
        tk.Label(top_bar, text="🌐  网页资源爬虫", fg=FG, bg=BG1,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=16, pady=10)
        tk.Button(top_bar, text="⚙", command=self._open_settings,
                  bg=BG1, fg=FG2, font=("Segoe UI", 11), relief="flat", cursor="hand2",
                  activebackground=BG2, activeforeground=FG, padx=4).pack(side="left", pady=10)
        self.lbl_status = tk.Label(top_bar, text="", fg=FG2, bg=BG1, font=FONT_SM)
        self.lbl_status.pack(side="right", padx=16, pady=10)

        # 主区域
        main = tk.Frame(self.root, bg=BG0)
        main.pack(fill="both", expand=True, padx=8, pady=4)

        # ── 顶部：URL 输入 + 历史记录 ──────────────────────
        url_frame = tk.Frame(main, bg=BG1, highlightbackground=BORDER,
                             highlightthickness=1)
        url_frame.pack(fill="x", pady=(0, 6))

        inner = tk.Frame(url_frame, bg=BG1)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="网址 URL（多网址用逗号或换行分隔）", fg=FG2, bg=BG1, font=FONT_SM).pack(anchor="w")
        row = tk.Frame(inner, bg=BG1)
        row.pack(fill="x", pady=(4, 0))

        # URL 输入框（浏览器地址栏风格 — 改用 tk.Entry 避免 ttk 焦点变黑问题）
        self.var_url = tk.StringVar()
        self.cmb_url = tk.Entry(
            row, textvariable=self.var_url, font=FONT,
            bg=BG0, fg=FG, insertbackground=FG,
            relief="flat", highlightbackground=BORDER,
            highlightthickness=1, highlightcolor=BLUE,
        )

        self.cmb_url.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 4))
        # 输入框变更监听：清空时清除资源列表
        self.var_url.trace_add("write", lambda *a: self._on_url_change())
        # 浏览器地址栏行为
        self.cmb_url.bind("<Return>", lambda e: self._fetch())
        self.cmb_url.bind("<FocusIn>", lambda e: self.root.after(50, lambda: self.cmb_url.select_range(0, "end")))
        self.cmb_url.bind("<Button-1>", lambda e: self.root.after(10, self._url_click))
        self.cmb_url.bind("<Control-a>", lambda e: self.cmb_url.select_range(0, "end"))
        self.cmb_url.bind("<Escape>", lambda e: (self.cmb_url.select_clear(), self._hide_suggestions()))
        self.cmb_url.bind("<Down>", lambda e: self._nav_suggestions(1))
        self.cmb_url.bind("<Up>", lambda e: self._nav_suggestions(-1))

        # 下拉建议 Listbox（浮层）
        self.suggest_box = tk.Listbox(self.root, bg=BG1, fg=FG, font=FONT,
                                       selectbackground=BG2, selectforeground=FG,
                                       relief="solid", bd=1, highlightthickness=0, height=6)
        self.suggest_box.bind("<ButtonRelease-1>", lambda e: self._pick_suggestion())
        self.suggest_box.bind("<Button-3>", lambda e: self._right_click_history())
        self.suggest_box.bind("<Return>", lambda e: (self._pick_suggestion(), self._fetch()))

        # 删除历史按钮
        self.btn_del_hist = tk.Button(row, text="🗑", command=self._delete_history,
                                      bg=BG2, fg=FG2, font=("Segoe UI", 10),
                                      relief="flat", cursor="hand2", padx=8, pady=4,
                                      activebackground="#3d2222", activeforeground=RED)
        self.btn_del_hist.pack(side="right", padx=2)

        self.btn_fetch = tk.Button(row, text="🔍  抓 取", command=self._fetch,
                                   bg="#238636", fg="white", font=("Segoe UI", 10, "bold"),
                                   relief="flat", cursor="hand2", padx=24, pady=6,
                                   activebackground="#2ea043", activeforeground="white")
        self.btn_fetch.pack(side="right", padx=2)

        self.btn_stop = tk.Button(row, text="⏹", command=self._stop_fetch,
                                  bg=BG2, fg=RED, font=("Segoe UI", 10, "bold"),
                                  relief="flat", cursor="hand2", padx=10, pady=6,
                                  state="disabled",
                                  activebackground="#3d2222", activeforeground=RED)
        self.btn_stop.pack(side="right", padx=2)

        # 保存目录
        path_row = tk.Frame(inner, bg=BG1)
        path_row.pack(fill="x", pady=(6, 0))
        tk.Label(path_row, text="保存目录", fg=FG2, bg=BG1, font=FONT_SM).pack(side="left")
        self.lbl_path = tk.Label(path_row, text="", fg=FG3, bg=BG1, font=FONT_SM)
        self.lbl_path.pack(side="left", padx=8)
        tk.Button(path_row, text="📁 更换", command=self._change_dir,
                  bg=BG2, fg=FG2, font=FONT_SM, relief="flat", cursor="hand2",
                  padx=8, pady=2).pack(side="right")
        self._update_path_label()

        # ── 下载侧边栏 + 主内容区 ──────────────────────────
        body = tk.Frame(main, bg=BG0)
        body.pack(fill="both", expand=True)

        # 侧边栏（下载记录）
        self._build_sidebar(body)

        # 主内容区（资源列表 + 预览）
        content = tk.Frame(body, bg=BG0)
        content.pack(side="left", fill="both", expand=True, padx=(4, 0))

        # 左侧：资源列表
        left = tk.Frame(content, bg=BG1, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))

        # 筛选按钮行
        self.filter_frame = tk.Frame(left, bg=BG1)
        self.filter_frame.pack(fill="x", padx=8, pady=(8, 4))
        self.filter_buttons = {}

        # 滚动列表
        self.canvas = tk.Canvas(left, bg=BG1, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas, bg=BG1)
        self.scroll_frame.bind("<Configure>",
                               lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # 空状态
        self.empty_frame = tk.Frame(self.scroll_frame, bg=BG1)
        self.empty_frame.pack(fill="both", expand=True, pady=80)
        tk.Label(self.empty_frame, text="🔍", font=("Segoe UI", 36), fg=FG3, bg=BG1).pack()
        tk.Label(self.empty_frame, text="输入网址点击「抓取」开始", fg=FG2, bg=BG1,
                 font=("Segoe UI", 10)).pack(pady=4)
        tk.Label(self.empty_frame, text="支持图片 · 音视频 · HLS流 · CSS · JS · 文档",
                 fg=FG3, bg=BG1, font=FONT_SM).pack()

        # 分隔
        ttk.Separator(content, orient="vertical").pack(side="left", fill="y", padx=4)

        # 右侧：预览区域
        right = tk.Frame(content, bg=BG1, highlightbackground=BORDER, highlightthickness=1, width=320)
        right.pack(side="right", fill="both", padx=(4, 0))
        right.pack_propagate(False)

        tk.Label(right, text="📖  资源预览", fg=FG2, bg=BG1, font=("Segoe UI", 9, "bold")).pack(
            pady=(12, 0))
        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=12, pady=4)

        self.preview_frame = tk.Frame(right, bg=BG1)
        self.preview_frame.pack(fill="both", expand=True, padx=12, pady=8)
        tk.Label(self.preview_frame, text="👀", font=("Segoe UI", 28), fg=FG3, bg=BG1).pack(pady=40)
        tk.Label(self.preview_frame, text="点击资源查看预览", fg=FG3, bg=BG1, font=FONT_SM).pack()

        # ── 底部：下载栏 ──────────────────────────────────
        bottom = tk.Frame(main, bg=BG1, highlightbackground=BORDER, highlightthickness=1)
        bottom.pack(fill="x", pady=(6, 0))

        btn_row = tk.Frame(bottom, bg=BG1)
        btn_row.pack(fill="x", padx=12, pady=8)

        # 选择切换
        tk.Button(btn_row, text="☑ 全选", command=self._select_all,
                  bg=BG2, fg=FG2, font=FONT_SM, relief="flat", cursor="hand2",
                  padx=10, pady=4).pack(side="left", padx=(0, 4))
        tk.Button(btn_row, text="☐ 取消", command=self._select_none,
                  bg=BG2, fg=FG2, font=FONT_SM, relief="flat", cursor="hand2",
                  padx=10, pady=4).pack(side="left", padx=(0, 16))

        self.lbl_count = tk.Label(btn_row, text="已选 0 项", fg=FG2, bg=BG1, font=FONT_SM)
        self.lbl_count.pack(side="left", padx=(0, 8))

        # 进度条 + 进度文本
        self.progress = ttk.Progressbar(btn_row, mode="determinate", length=160)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.lbl_progress = tk.Label(btn_row, text="", fg=FG3, bg=BG1, font=("Consolas", 8))
        self.lbl_progress.pack(side="left", padx=(0, 8))

        self.btn_pause = tk.Button(btn_row, text="⏸", command=self._toggle_pause,
                                   bg=BG2, fg=ORANGE, font=("Segoe UI", 10, "bold"),
                                   relief="flat", cursor="hand2", padx=8, pady=4,
                                   state="disabled")
        self.btn_pause.pack(side="right", padx=2)

        self.btn_stop_dl = tk.Button(btn_row, text="⏹", command=self._stop_download,
                                     bg=BG2, fg=RED, font=("Segoe UI", 10, "bold"),
                                     relief="flat", cursor="hand2", padx=10, pady=4,
                                     state="disabled")
        self.btn_stop_dl.pack(side="right", padx=2)

        self.btn_download = tk.Button(btn_row, text="⬇  下 载", command=self._download,
                                      bg="#1f6feb", fg="white", font=("Segoe UI", 10, "bold"),
                                      relief="flat", cursor="hand2", padx=20, pady=6,
                                      state="disabled",
                                      activebackground="#388bfd", activeforeground="white")
        self.btn_download.pack(side="right", padx=2)

    # ── 路径更新 ──────────────────────────────────────────
    def _build_sidebar(self, parent):
        """左侧下载管理器（百度网盘风格）"""
        sidebar = tk.Frame(parent, bg=BG1, width=210, highlightbackground=BORDER, highlightthickness=1)
        sidebar.pack(side="left", fill="y", padx=(0, 4))
        sidebar.pack_propagate(False)

        # 标题
        tk.Label(sidebar, text="📥 下载管理", fg=FG, bg=BG1, font=("Segoe UI", 9, "bold")).pack(pady=(10, 8))

        # 标签切换：下载中(N) / 已完成(N)
        tab_row = tk.Frame(sidebar, bg=BG1)
        tab_row.pack(fill="x", padx=6, pady=(0, 8))
        active_count = sum(1 for d in self.download_log if "中" in d[2])
        done_count = sum(1 for d in self.download_log if "中" not in d[2])
        self.btn_tab_active = tk.Label(tab_row, text=f"下载中({active_count})", bg="#1f6feb", fg="white",
                                        font=FONT_SM, padx=4, pady=4, cursor="hand2")
        self.btn_tab_active.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.btn_tab_active.bind("<Button-1>", lambda e: self._switch_dl_tab("进行中"))
        self.btn_tab_done = tk.Label(tab_row, text=f"已完成({done_count})", bg=BG2, fg=FG2,
                                      font=FONT_SM, padx=4, pady=4, cursor="hand2")
        self.btn_tab_done.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.btn_tab_done.bind("<Button-1>", lambda e: self._switch_dl_tab("已完成"))

        # 控制按钮行
        ctrl_row = tk.Frame(sidebar, bg=BG1)
        ctrl_row.pack(fill="x", padx=6, pady=(0, 6))
        tk.Label(ctrl_row, text="全部暂停", fg=BLUE, bg=BG1, font=FONT_SM,
                 cursor="hand2").pack(side="left", padx=(0, 6))
        tk.Label(ctrl_row, text="全部开始", fg=GREEN, bg=BG1, font=FONT_SM,
                 cursor="hand2").pack(side="left", padx=(0, 6))
        tk.Label(ctrl_row, text="全部删除", fg=RED, bg=BG1, font=FONT_SM,
                 cursor="hand2").pack(side="left")
        # bind commands
        ctrl_row.winfo_children()[0].bind("<Button-1>", lambda e: self._toggle_pause())
        ctrl_row.winfo_children()[2].bind("<Button-1>", lambda e: self._clear_dl_log())

        # 滚动日志区
        dl_canvas = tk.Canvas(sidebar, bg=BG1, highlightthickness=0)
        dl_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=dl_canvas.yview)
        self.dl_log_frame = tk.Frame(dl_canvas, bg=BG1)
        self.dl_log_frame.bind("<Configure>", lambda e: dl_canvas.configure(
            scrollregion=dl_canvas.bbox("all")))
        dl_canvas.create_window((0, 0), window=self.dl_log_frame, anchor="nw", width=195)
        dl_canvas.configure(yscrollcommand=dl_scroll.set)
        dl_canvas.pack(side="left", fill="both", expand=True)
        dl_scroll.pack(side="right", fill="y")

        self.sidebar_canvas = dl_canvas
        self._refresh_sidebar()

    def _switch_dl_tab(self, tab):
        self.download_tab = tab
        active_count = sum(1 for d in self.download_log if "中" in d[2])
        done_count = sum(1 for d in self.download_log if "中" not in d[2])
        if tab == "进行中":
            self.btn_tab_active.config(bg="#1f6feb", fg="white", text=f"下载中({active_count})")
            self.btn_tab_done.config(bg=BG2, fg=FG2, text=f"已完成({done_count})")
        else:
            self.btn_tab_done.config(bg="#238636", fg="white", text=f"已完成({done_count})")
            self.btn_tab_active.config(bg=BG2, fg=FG2, text=f"下载中({active_count})")
        self._refresh_sidebar()

    def _clear_dl_log(self):
        self.download_log.clear()
        self._refresh_sidebar()

    def _refresh_sidebar(self):
        for w in self.dl_log_frame.winfo_children():
            w.destroy()
        active_count = sum(1 for d in self.download_log if "中" in d[2])
        done_count = sum(1 for d in self.download_log if "中" not in d[2])
        # 更新 tab 计数
        self.btn_tab_active.config(text=f"下载中({active_count})")
        self.btn_tab_done.config(text=f"已完成({done_count})")

        items = [d for d in self.download_log if (
            (self.download_tab == "进行中" and "中" in d[2]) or
            (self.download_tab == "已完成" and "中" not in d[2])
        )]
        if not items:
            tk.Label(self.dl_log_frame, text="暂无记录", fg=FG3, bg=BG1, font=FONT_SM).pack(pady=20)
            return
        for url, fname, status, size in items[-100:]:
            color = GREEN if "✅" in status else (ORANGE if "📥" in status else RED)
            text = f"{status} {fname[:20]}"
            tk.Label(self.dl_log_frame, text=text, fg=color, bg=BG1,
                     font=("Consolas", 7), anchor="w", justify="left",
                     wraplength=175, pady=1).pack(fill="x", padx=6)
            if size:
                tk.Label(self.dl_log_frame, text=f"   {size}", fg=FG3, bg=BG1,
                         font=("Consolas", 7)).pack(anchor="w", padx=6)
        self.lbl_path.config(text=str(self.save_dir))

    def _update_path_label(self):
        self.lbl_path.config(text=str(self.save_dir))

    def _change_dir(self):
        d = filedialog.askdirectory(title="选择保存目录", initialdir=self.save_dir)
        if d:
            self.save_dir = pathlib.Path(d)
            _save_save_dir(str(self.save_dir))
            self._update_path_label()

    def _apply_settings(self):
        import core.downloader as dl
        dl.MAX_WORKERS = self.settings["max_workers"]
        self._apply_theme()

    def _apply_theme(self):
        """实时切换主题色"""
        global BG0, BG1, BG2, BORDER, FG, FG2, FG3, GREEN, BLUE, RED, ORANGE, PURPLE
        if self.settings.get("theme") == "light":
            BG0 = "#ffffff"; BG1 = "#f6f8fa"; BG2 = "#e1e4e8"
            BORDER = "#d0d7de"; FG = "#24292f"; FG2 = "#656d76"
            FG3 = "#8b949e"; GREEN = "#1a7f37"; BLUE = "#0550ae"
            RED = "#cf222e"; ORANGE = "#bc4c00"; PURPLE = "#8250df"
        else:
            BG0 = "#0d1117"; BG1 = "#161b22"; BG2 = "#21262d"
            BORDER = "#30363d"; FG = "#e6edf3"; FG2 = "#8b949e"
            FG3 = "#484f58"; GREEN = "#3fb950"; BLUE = "#58a6ff"
            RED = "#f85149"; ORANGE = "#d29922"; PURPLE = "#a371f7"

        def _recolor(widget):
            """递归更新所有子控件颜色"""
            try:
                cls = widget.winfo_class()
                if cls in ("Frame", "Toplevel", "Labelframe"):
                    widget.configure(bg=BG1)
                elif cls == "Canvas":
                    widget.configure(bg=BG1)
                elif cls == "Label":
                    cur = widget.cget("fg")
                    if cur not in ("white", "#ffffff", "#fff"):
                        widget.configure(bg=BG1, fg=FG if cur not in (str(FG2), str(FG3), str(RED), str(BLUE), str(GREEN), str(ORANGE), str(PURPLE)) else cur)
                    else:
                        widget.configure(bg=BG1)
                elif cls == "Button":
                    widget.configure(bg=BG2, fg=FG2, activebackground=BG2)
                elif cls == "Checkbutton":
                    widget.configure(bg=BG1, activebackground=BG1)
                elif cls == "Entry":
                    widget.configure(bg=BG0, fg=FG)
                elif cls == "Scale":
                    widget.configure(bg=BG1)
                elif cls == "Radiobutton":
                    widget.configure(bg=BG1, activebackground=BG1)
            except Exception:
                pass
            for child in widget.winfo_children():
                _recolor(child)

        self.root.configure(bg=BG0)
        _recolor(self.root)

    # ── 设置窗口 ──────────────────────────────────────────
    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("⚙ 设置")
        win.geometry("420x470")
        win.configure(bg=BG1)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        # 居中
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 470) // 2
        win.geometry(f"+{x}+{y}")

        tk.Label(win, text="⚙  设置", fg=FG, bg=BG1, font=("Segoe UI", 13, "bold")).pack(pady=(16, 12))

        # 内容区
        frm = tk.Frame(win, bg=BG1)
        frm.pack(fill="both", expand=True, padx=20, pady=4)

        # 保存目录
        tk.Label(frm, text="默认保存目录", fg=FG2, bg=BG1, font=FONT_SM).pack(anchor="w")
        dir_row = tk.Frame(frm, bg=BG1)
        dir_row.pack(fill="x", pady=(2, 12))
        var_dir = tk.StringVar(value=str(self.save_dir))
        e_dir = tk.Entry(dir_row, textvariable=var_dir, bg=BG0, fg=FG, font=FONT, relief="flat",
                         highlightbackground=BORDER, highlightthickness=1)
        e_dir.pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(dir_row, text="📁", command=lambda: self._pick_dir(win, var_dir),
                  bg=BG2, fg=FG2, font=FONT, relief="flat", cursor="hand2", padx=6).pack(side="left", padx=4)

        # 并发数
        tk.Label(frm, text="最大并发下载数", fg=FG2, bg=BG1, font=FONT_SM).pack(anchor="w")
        var_workers = tk.IntVar(value=self.settings["max_workers"])
        tk.Scale(frm, from_=1, to=12, orient="horizontal", variable=var_workers,
                 bg=BG1, fg=FG, troughcolor=BG0, highlightthickness=0).pack(fill="x", pady=(2, 12))

        # 超时
        tk.Label(frm, text="请求超时（秒）", fg=FG2, bg=BG1, font=FONT_SM).pack(anchor="w")
        var_timeout = tk.IntVar(value=self.settings["timeout"])
        tk.Scale(frm, from_=5, to=60, orient="horizontal", variable=var_timeout,
                 bg=BG1, fg=FG, troughcolor=BG0, highlightthickness=0).pack(fill="x", pady=(2, 12))

        # 自动勾选 HLS
        var_hls = tk.BooleanVar(value=self.settings["auto_check_hls"])
        cb = tk.Checkbutton(frm, text="检测到 HLS 资源时自动勾选", variable=var_hls,
                            bg=BG1, fg=FG2, selectcolor=BG0, activebackground=BG1,
                            font=FONT_SM)
        cb.pack(anchor="w", pady=(4, 4))

        # 主题

        # 主题
        tk.Label(frm, text="界面主题", fg=FG2, bg=BG1, font=FONT_SM).pack(anchor="w")
        var_theme = tk.StringVar(value=self.settings["theme"])
        theme_frm = tk.Frame(frm, bg=BG1)
        theme_frm.pack(fill="x", pady=(2, 16))
        for t, label in [("dark", "🌙 暗色"), ("light", "☀ 亮色")]:
            tk.Radiobutton(theme_frm, text=label, variable=var_theme, value=t,
                           bg=BG1, fg=FG2, selectcolor=BG0, activebackground=BG1,
                           font=FONT_SM).pack(side="left", padx=(0, 16))

        # 保存按钮
        def _save():
            self.settings["max_workers"] = var_workers.get()
            self.settings["timeout"] = var_timeout.get()
            self.settings["auto_check_hls"] = var_hls.get()
            self.settings["theme"] = var_theme.get()
            cfg = _load_config()
            cfg["settings"] = self.settings
            _save_config(cfg)

            d = var_dir.get().strip()
            if d and pathlib.Path(d).exists():
                self.save_dir = pathlib.Path(d)
                _save_save_dir(d)
                self._update_path_label()

            win.destroy()
            self.lbl_status.config(text="✅ 设置已保存", fg=GREEN)

        tk.Button(frm, text="💾 保存设置", command=_save,
                  bg="#238636", fg="white", font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", padx=20, pady=6,
                  activebackground="#2ea043").pack(pady=(8, 0))

    def _pick_dir(self, parent, var):
        d = filedialog.askdirectory(title="选择目录", initialdir=var.get())
        if d:
            var.set(d)

    # ── 历史记录 ──────────────────────────────────────────
    def _add_history(self, url: str):
        if url in self.history:
            self.history.remove(url)
        self.history.insert(0, url)
        self.history = self.history[:50]
        _save_history(self.history)

    def _delete_history(self):
        url = self.var_url.get().strip()
        if not url:
            return
        if url in self.history:
            self.history.remove(url)
            _save_history(self.history)
            self.var_url.set("")
            self.lbl_status.config(text="🗑 已删除历史记录", fg=FG2)
        else:
            # 清空当前输入
            self.var_url.set("")

    def _right_click_history(self):
        """右键删除历史建议"""
        idx = self.suggest_box.nearest(self.suggest_box.winfo_pointery() - self.suggest_box.winfo_rooty())
        if idx < 0 or idx >= self.suggest_box.size():
            return
        self.suggest_box.selection_clear(0, "end")
        self.suggest_box.selection_set(idx)
        url = self.suggest_box.get(idx)
        if url in self.history:
            self.history.remove(url)
            _save_history(self.history)
            self._show_suggestions()
            self.lbl_status.config(text="🗑 已删除", fg=FG2)

    def _url_click(self):
        """点击时全选"""
        self.cmb_url.select_range(0, "end")
        self.cmb_url.icursor("end")

    def _show_suggestions(self):
        """显示浏览器风格下拉建议"""
        items = self.history[:10]
        typed = self.var_url.get().lower()
        if typed and len(typed) > 1:
            matches = [u for u in self.history if typed in u.lower()][:8]
            if matches:
                items = matches
        if items:
            self.suggest_box.delete(0, "end")
            for item in items:
                self.suggest_box.insert("end", item[:80])
            # 定位在输入框下方
            x = self.cmb_url.winfo_rootx() - self.root.winfo_rootx()
            y = self.cmb_url.winfo_rooty() - self.root.winfo_rooty() + self.cmb_url.winfo_height()
            w = self.cmb_url.winfo_width()
            self.suggest_box.config(width=int(w * 0.08))
            self.suggest_box.place(x=x, y=y, width=w)
            self.suggest_box.lift()
        else:
            self._hide_suggestions()

    def _hide_suggestions(self):
        self.suggest_box.place_forget()

    def _pick_suggestion(self):
        sel = self.suggest_box.curselection()
        if sel:
            self.var_url.set(self.suggest_box.get(sel[0]))
            self._hide_suggestions()
            self.cmb_url.select_range(0, "end")
            self.cmb_url.icursor("end")

    def _nav_suggestions(self, direction):
        if not self.suggest_box.winfo_ismapped():
            self._show_suggestions()
            return
        size = self.suggest_box.size()
        if size == 0:
            return
        sel = self.suggest_box.curselection()
        if sel:
            idx = max(0, min(size-1, sel[0] + direction))
        else:
            idx = 0 if direction > 0 else size - 1
        self.suggest_box.selection_clear(0, "end")
        self.suggest_box.selection_set(idx)
        self.suggest_box.activate(idx)

    def _on_url_type(self):
        pass

    def _on_url_change(self):
        """输入框清空时清除资源列表"""
        if not self.var_url.get().strip():
            self.resources = []
            self._clear_list()
            self._show_preview_empty()
            self.lbl_status.config(text="", fg=FG2)

    # ── 抓取（支持多 URL，独立线程永不阻塞）─────────────
    def _fetch(self):
        raw = self.var_url.get().strip()
        if not raw:
            return

        urls = [u.strip() for u in re.split(r'[,\n]+', raw) if u.strip()]
        if not urls:
            return
        normalized = [u if u.startswith(("http://","https://")) else "https://"+u for u in urls]

        if self.fetching:
            return
        self._add_history(normalized[0])

        self.fetching = True
        self.resources = []
        self._clear_list()
        self._show_preview_empty()
        self.lbl_status.config(text=f"⏳ 正在抓取 1/{len(normalized)}...", fg=ORANGE)
        self.progress["mode"] = "indeterminate"
        self.progress.start(10)

        def do():
            all_resources = []
            for i, url in enumerate(normalized):
                try:
                    html = fetch_html(url)
                    res = parse_resources(html, url, source_url=url)
                    all_resources.extend(res)
                except Exception:
                    pass
            label = normalized[0] if len(normalized)==1 else f"{len(normalized)}个网页"
        # ── 线程内立即回调，事件队列已空不堵塞 ──
            self.fetching = False
            self.root.after_idle(lambda: self._on_fetch_result(label, all_resources))

        self._fetch_thread = threading.Thread(target=do, daemon=True)
        self._fetch_thread.start()

    def _stop_fetch(self):
        self.fetching = False
        self._set_buttons(fetching=False)
        self.lbl_status.config(text="⏹ 已停止", fg=FG2)
        self.progress.stop()
        self.progress["mode"] = "determinate"

    def _set_buttons(self, fetching=False, downloading=False):
        self.btn_fetch.config(state="normal", text="🔍  抓 取")  # 始终可点，fetching 标志防抖
        self.btn_stop.config(state="normal" if fetching else "disabled")
        self.cmb_url.config(state="disabled" if fetching else "normal")
        self.btn_download.config(state="disabled" if fetching else (
            "normal" if self.checked_count > 0 and not downloading else "disabled"))
        if downloading:
            self.btn_pause.config(state="normal", text="⏸", fg=ORANGE)
            self.btn_stop_dl.config(state="normal")
        else:
            self.btn_pause.config(state="disabled")
            self.btn_stop_dl.config(state="disabled")

    def _on_fetch_result(self, url, resources):
        self.resources = resources
        self._set_buttons(fetching=False, downloading=self.downloading)
        self.progress.stop()
        self.progress["mode"] = "determinate"
        self.lbl_status.config(text=f"✅ 找到 {len(resources)} 个资源", fg=GREEN)
        self._render_list()
        self._check_suggest_hls()

    def _check_suggest_hls(self):
        """如果有 HLS 且设置允许自动勾选"""
        if not self.settings.get("auto_check_hls", True):
            return
        hls = [r for r in self.resources if "HLS" in r.rtype]
        if hls:
            for r in hls:
                r.checked = True
            self._update_count()
            self.root.after(500, lambda: self.lbl_status.config(
                text=f"📻 检测到 HLS 音频流，已自动勾选", fg=GREEN))

    def _on_fetch_err(self, err):
        self.fetching = False
        self._set_buttons(fetching=False)
        self.progress.stop()
        self.progress["mode"] = "determinate"
        self.lbl_status.config(text=f"❌ 抓取失败: {err[:50]}", fg=RED)
        messagebox.showerror("抓取失败", f"错误信息:\n{err}")

    # ── 资源列表渲染 ──────────────────────────────────────
    def _clear_list(self):
        for w in self.scroll_frame.winfo_children():
            if w != self.empty_frame:
                w.destroy()
        self.empty_frame.pack(fill="both", expand=True, pady=80)
        for btn in self.filter_buttons.values():
            btn.destroy()
        self.filter_buttons = {}
        self.row_widgets = []

    def _render_list(self):
        self._clear_list()
        self.empty_frame.pack_forget()
        self.row_widgets = []

        # 统计
        type_count = {}
        for r in self.resources:
            type_count[r.rtype] = type_count.get(r.rtype, 0) + 1

        # 筛选按钮
        all_btn = tk.Label(self.filter_frame, text=f"全部 ({len(self.resources)})",
                           bg="#1f6feb", fg="white", font=FONT_SM, padx=10, pady=3, cursor="hand2")
        all_btn.pack(side="left", padx=(0, 4))
        all_btn.bind("<Button-1>", lambda e: self._filter_type(None))
        self.filter_buttons["__all__"] = all_btn

        for t, cnt in sorted(type_count.items(), key=lambda x: -x[1]):
            color = TYPE_COLORS.get(t, FG2)
            btn = tk.Label(self.filter_frame, text=f"{t} ({cnt})",
                           bg=BG2, fg=color, font=FONT_SM, padx=8, pady=3, cursor="hand2")
            btn.pack(side="left", padx=(0, 4))
            btn.bind("<Button-1>", lambda e, tt=t: self._filter_type(tt))
            self.filter_buttons[t] = btn

        self._active_filter = None
        self._render_rows()

    def _filter_type(self, rtype):
        self._active_filter = rtype
        # 更新按钮样式
        for key, btn in self.filter_buttons.items():
            if key == ("__all__" if rtype is None else rtype):
                btn.config(bg="#1f6feb", fg="white")
            else:
                color = TYPE_COLORS.get(key, FG2) if key != "__all__" else FG2
                btn.config(bg=BG2, fg=color)
        self._render_rows()

    def _render_rows(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self.row_widgets = []

        filtered = self.resources
        if self._active_filter:
            filtered = [r for r in self.resources if r.rtype == self._active_filter]

        for i, r in enumerate(filtered):
            self._add_row(r, i, len(filtered) - 1)

        self.canvas.yview_moveto(0)
        self._update_count()

    def _add_row(self, r: Resource, idx, last_idx):
        is_last = (idx == last_idx)
        bg = BG2 if idx % 2 == 0 else BG1

        row_f = tk.Frame(self.scroll_frame, bg=bg)
        row_f.pack(fill="x", padx=4, pady=(0, 0 if is_last else 1))

        # Checkbox
        var = tk.BooleanVar(value=r.checked)
        cb = tk.Checkbutton(row_f, variable=var, bg=bg, fg=FG,
                            selectcolor=BG0, activebackground=bg,
                            command=lambda rr=r, vv=var: self._toggle(rr, vv))
        cb.pack(side="left", padx=(4, 2))

        # 类型 badge
        icon = TYPE_ICONS.get(r.rtype, "📎")
        color = TYPE_COLORS.get(r.rtype, FG2)
        tk.Label(row_f, text=f" {icon} {r.rtype} ", fg=color, bg=bg, font=FONT_SM).pack(side="left", padx=2)

        # 文件名
        name = r.name[:30] + ("..." if len(r.name) > 30 else "")
        tk.Label(row_f, text=name, fg=FG, bg=bg, font=FONT,
                 anchor="w").pack(side="left", fill="x", expand=True, padx=(8, 2))

        # 来源域名（多URL抓取时显示）
        if hasattr(r, 'source') and r.source:
            domain = urlparse(r.source).netloc[:18]
            tk.Label(row_f, text=domain, fg=FG3, bg=bg, font=("Consolas", 7),
                     padx=4).pack(side="right")

        # 预览按钮（仅可预览类型）
        if r.rtype in ("图片", "音频") or "HLS" in r.rtype:
            btn = tk.Label(row_f, text="👁", fg=BLUE, bg=bg, font=FONT,
                           cursor="hand2", padx=6)
            btn.bind("<Button-1>", lambda e, rr=r: self._preview(rr))
            btn.pack(side="right", padx=2)

        self.row_widgets.append((row_f, var, r))

    def _toggle(self, r, var):
        r.checked = var.get()
        self._update_count()

    def _select_all(self):
        if self._active_filter:
            filtered = [r for r in self.resources if r.rtype == self._active_filter]
            for r in filtered:
                r.checked = True
        else:
            for r in self.resources:
                r.checked = True
        self._render_rows()
        self._update_count()

    def _select_none(self):
        if self._active_filter:
            filtered = [r for r in self.resources if r.rtype == self._active_filter]
            for r in filtered:
                r.checked = False
        else:
            for r in self.resources:
                r.checked = False
        self._render_rows()
        self._update_count()

    def _update_count(self):
        n = sum(1 for r in self.resources if r.checked)
        self.checked_count = n
        self.lbl_count.config(text=f"已选 {n} 项")
        self.btn_download.config(state="normal" if n > 0 and not self.fetching else "disabled")

    # ── 预览 ─────────────────────────────────────────────
    def _preview(self, r: Resource):
        for w in self.preview_frame.winfo_children():
            w.destroy()
        tk.Label(self.preview_frame, text=r.name[:60], fg=FG, bg=BG1,
                 font=("Segoe UI", 9, "bold"), wraplength=280).pack(anchor="w", pady=(0, 4))
        tk.Label(self.preview_frame, text=r.url[:100], fg=FG3, bg=BG1,
                 font=FONT_SM, wraplength=280, justify="left").pack(anchor="w", pady=(0, 8))

        if "HLS" in r.rtype:
            tk.Label(self.preview_frame, text="📻  HLS 流媒体", fg=GREEN, bg=BG1,
                     font=("Segoe UI", 12, "bold")).pack(pady=8)
            tk.Label(self.preview_frame,
                     text="该资源为 HLS 流格式\n下载后将自动合并为完整音频文件\n\n请勾选后点击「下载」按钮",
                     fg=FG2, bg=BG1, font=FONT_SM, justify="center").pack(pady=4)
        elif r.rtype == "图片":
            tk.Label(self.preview_frame, text="🖼  图片预览", fg=BLUE, bg=BG1,
                     font=("Segoe UI", 10)).pack(pady=4)
            tk.Label(self.preview_frame, text=f"URL: {r.url[:80]}", fg=FG3, bg=BG1,
                     font=FONT_SM, wraplength=280).pack(pady=4)
            tk.Label(self.preview_frame,
                     text="💡 图片预览功能\n请勾选后下载到本地查看",
                     fg=FG2, bg=BG1, font=FONT_SM, justify="center").pack(pady=20)
        elif r.rtype == "音频":
            tk.Label(self.preview_frame, text="🎵  音频文件", fg=PURPLE, bg=BG1,
                     font=("Segoe UI", 10)).pack(pady=4)
            tk.Label(self.preview_frame, text=f"URL: {r.url[:80]}", fg=FG3, bg=BG1,
                     font=FONT_SM, wraplength=280).pack(pady=4)
        else:
            tk.Label(self.preview_frame, text=f"{TYPE_ICONS.get(r.rtype, '📄')}  {r.rtype}",
                     fg=FG, bg=BG1, font=("Segoe UI", 10)).pack(pady=20)

    def _show_preview_empty(self):
        for w in self.preview_frame.winfo_children():
            w.destroy()
        tk.Label(self.preview_frame, text="👀", font=("Segoe UI", 28), fg=FG3, bg=BG1).pack(pady=40)
        tk.Label(self.preview_frame, text="点击资源查看预览", fg=FG3, bg=BG1, font=FONT_SM).pack()

    # ── 下载（支持暂停/取消）────────────────────────────
    def _download(self):
        if self.downloading and self.paused:
            # 继续
            self._resume()
            return

        checked = [r for r in self.resources if r.checked]
        if not checked:
            messagebox.showinfo("提示", "请先勾选要下载的资源")
            return

        has_hls = any("HLS" in r.rtype for r in checked)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.downloading = True
        self.paused = False
        self.stop_flag.clear()
        self.pause_event.clear()

        # 记录到侧边栏
        for r in checked:
            self.download_log.append((r.url, r.name, "📥 下载中", ""))
        self._refresh_sidebar()

        self._set_dl_buttons(downloading=True)
        self.btn_download.config(text="⏳", state="disabled")
        self.progress["value"] = 0
        total = len(checked)

        if has_hls:
            self.lbl_status.config(text="📻 检测到 HLS，将自动合并为完整文件", fg=BLUE)

        self._dl_progress_info = [0, 0, "", 0]  # 重置进度
        def cb(t, done, name):
            pct = min(int(done / t * 100), 100) if t else 0
            self._dl_progress_info = [t, done, name, pct]  # 线程写入，轮询读取
            if "分片" in name and self.pause_event.is_set():
                self.pause_event.wait()

        def do():
            results = download_all(checked, self.save_dir,
                                   stop_flag=self.stop_flag, progress_cb=cb)
            ok_list, fail_list, stopped_list = [], [], []
            for u, p in results:
                if p == "__STOPPED__":
                    stopped_list.append((u, p))
                elif p and pathlib.Path(p).exists():
                    ok_list.append((u, p, pathlib.Path(p).stat().st_size))
                else:
                    fail_list.append((u, p or "下载失败"))
            self.root.after(0, lambda: self._on_dl_done(ok_list, fail_list, stopped_list))

        self._dl_thread = threading.Thread(target=do, daemon=True)
        self._dl_thread.start()

    def _toggle_pause(self):
        if not self.downloading:
            return
        if self.paused:
            self._resume()
        else:
            self._pause()

    def _pause(self):
        self.paused = True
        self.pause_event.set()
        self.btn_pause.config(text="▶", fg=GREEN)
        self.lbl_status.config(text="⏸ 已暂停  — 点击 ▶ 继续", fg=ORANGE)
        self.btn_download.config(text="▶ 继续", state="normal")

    def _resume(self):
        self.paused = False
        self.pause_event.clear()
        self.btn_pause.config(text="⏸", fg=ORANGE)
        self.btn_download.config(text="⏳", state="disabled")
        self.lbl_status.config(text="📥 继续下载...", fg=BLUE)

    def _stop_download(self):
        if not self.downloading:
            return
        self.stop_flag.set()
        self.paused = False
        self.pause_event.clear()  # 如果正在暂停，也唤醒以便退出
        self.lbl_status.config(text="⏹ 正在停止...", fg=RED)

    def _set_dl_buttons(self, downloading=False):
        self.btn_pause.config(state="normal" if downloading else "disabled",
                              text="⏸", fg=ORANGE)
        self.btn_stop_dl.config(state="normal" if downloading else "disabled")
        self.btn_download.config(state="disabled" if downloading else
                                 ("normal" if self.checked_count > 0 else "disabled"))

    def _on_dl_done(self, ok, fail, stopped):
        self.downloading = False
        self.paused = False
        self._dl_progress_info = [0, 0, "", 0]  # 清除进度

        # 更新侧边栏日志
        for u, p, sz in ok:
            fname = pathlib.Path(p).name
            sz_str = f"{sz/1024/1024:.1f}MB" if sz > 1024*1024 else f"{sz/1024:.0f}KB"
            self.download_log.append((u, fname, "✅ 已完成", sz_str))
        for u, e in fail:
            self.download_log.append((u, e[:25], "❌ 失败", ""))
        self._refresh_sidebar()
        self.pause_event.clear()
        self.stop_flag.clear()
        self.btn_pause.config(state="disabled", text="⏸", fg=ORANGE)
        self.btn_stop_dl.config(state="disabled")
        self.btn_download.config(state="normal" if self.checked_count > 0 else "disabled", text="⬇  下 载")
        self.progress["value"] = 100 if not stopped else self.progress["value"]
        self.lbl_progress.config(text="")
        self.lbl_progress.config(text="")

        if stopped:
            self.lbl_status.config(text="⏹ 下载已取消", fg=ORANGE)
        else:
            self.lbl_status.config(
                text=f"✅ 完成: 成功 {len(ok)} 项, 失败 {len(fail)} 项", fg=GREEN)

        msg_parts = []
        if stopped:
            msg_parts.append(f"⏹ 下载已取消\n\n")
        else:
            msg_parts.append(f"✅ 下载完成！\n\n")
        msg_parts.append(f"成功: {len(ok)} 项\n失败: {len(fail)} 项\n")

        if ok:
            msg_parts.append(f"\n保存目录: {self.save_dir}\n")
            msg_parts.append("\n已下载文件:\n")
            for u, p, sz in ok:
                fname = pathlib.Path(p).name
                sz_str = f"{sz/1024/1024:.1f}MB" if sz > 1024*1024 else f"{sz/1024:.0f}KB"
                icon = "🎵" if ".mp3" in p.lower() or ".m4a" in p.lower() else \
                       "🎬" if ".mp4" in p.lower() else "📄"
                msg_parts.append(f"  {icon} {fname[:40]} ({sz_str})")
        if fail:
            msg_parts.append(f"\n失败列表:\n")
            for u, e in fail[:5]:
                msg_parts.append(f"  • {u[:35]}...\n    → {e[:50]}\n")
        if stopped:
            msg_parts.append(f"\n取消项: {len(stopped)}")

        messagebox.showinfo("下载结果", "".join(msg_parts))
        self.progress["value"] = 0
        self._update_count()


# ══════════════════════════════════════════════════════════
#  启动
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app = ScraperApp(root)

    # Tk 8.6+ DPI 感知
    try:
        root.tk.call("tk", "scaling", 1.3)  # 适中的缩放
    except Exception:
        pass

    root.mainloop()
