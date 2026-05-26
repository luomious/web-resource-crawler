"""
网页资源爬虫 — PyQt5 中文版
"""
import sys, json, pathlib, re, threading
from typing import List, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QListWidget,
    QListWidgetItem, QFrame, QMessageBox, QFileDialog, QTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from core.scraper import fetch_html, parse_resources
from core.downloader import download_all

import os as _os
_appdata = pathlib.Path(_os.environ.get("APPDATA", pathlib.Path.home() / "AppData" / "Roaming"))
_config_dir = _appdata / "WebScraper"
_config_dir.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = _config_dir / "config.json"

def _load_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except: pass
    return {}

def _save_config(cfg):
    try: CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def _load_history():
    return _load_config().get("history", [])

def _save_history(urls):
    cfg = _load_config(); cfg["history"] = urls[:50]; _save_config(cfg)

class FetchWorker(QThread):
    finished = pyqtSignal(str, list)
    def __init__(self, urls):
        super().__init__(); self.urls = urls
    def run(self):
        all_resources = []
        for url in self.urls:
            try:
                html = fetch_html(url)
                res = parse_resources(html, url, source_url=url)
                all_resources.extend(res)
            except Exception as e:
                pass
        label = self.urls[0] if len(self.urls)==1 else f"{len(self.urls)}个网页"
        self.finished.emit(label, all_resources)

class DownloadWorker(QThread):
    progress = pyqtSignal(int, int, str, int)
    finished = pyqtSignal(list, list, list)
    def __init__(self, rlist, savedir, stopflag):
        super().__init__(); self.rlist = rlist; self.savedir = savedir
        self.stopflag = stopflag; self._c = 0
    def run(self):
        def cb(t, d, n):
            p = min(int(d/t*100), 100) if t else 0
            self._c += 1
            if self._c % 15 == 0 or "OK" in n or "Done" in n:
                self.progress.emit(t, d, n, p)

        try:
            results = download_all(self.rlist, self.savedir, stop_flag=self.stopflag, progress_cb=cb)
        except Exception as e:
            self.finished.emit([], [(r.url, str(e)) for r in self.rlist], [])
            return

        ok, fail, stop = [], [], []
        for u, p in results:
            if p == "__STOPPED__":
                stop.append((u, p))
            elif p and pathlib.Path(p).exists():
                try:
                    sz = pathlib.Path(p).stat().st_size
                    ok.append((u, p, sz))
                except:
                    ok.append((u, p, 0))
            else:
                fail.append((u, p or "下载失败"))
        self.finished.emit(ok, fail, stop)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("网页资源爬虫")
        self.setGeometry(100, 100, 1200, 800)

        cfg = _load_config()
        self.resources = []
        self.downloading = False
        self.stop_flag = threading.Event()
        self.history = _load_history()
        self.save_dir = pathlib.Path(cfg.get("save_dir", "E:/"))

        self._fetch_w = None
        self._dl_w = None
        self._dl_log = []

        self._build_ui()

    def _build_ui(self):
        c = QWidget()
        self.setCentralWidget(c)
        lo = QVBoxLayout(c)
        lo.setSpacing(6)
        lo.setContentsMargins(10, 10, 10, 10)

        # 标题
        t = QLabel("🌐  网页资源爬虫")
        t.setFont(QFont("Microsoft YaHei", 14))
        lo.addWidget(t)

        # URL 输入区
        uf = QFrame(); uf.setFrameStyle(QFrame.StyledPanel)
        ul = QVBoxLayout(uf)
        ul.addWidget(QLabel("网址 URL（多个用逗号或换行分隔）:"))

        ir = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com")
        self.url_input.returnPressed.connect(self._fetch)
        ir.addWidget(self.url_input)

        fb = QPushButton("🔍  抓 取")
        fb.setMinimumWidth(100)
        fb.clicked.connect(self._fetch)
        ir.addWidget(fb)
        ul.addLayout(ir)

        pr = QHBoxLayout()
        pr.addWidget(QLabel(f"保存目录: {self.save_dir}"))
        ch = QPushButton("📁 更换")
        ch.clicked.connect(self._change_dir)
        pr.addWidget(ch)
        pr.addStretch()
        ul.addLayout(pr)

        lo.addWidget(uf)

        # 主内容区
        ct = QHBoxLayout()

        # 左侧：下载管理
        lt = QVBoxLayout()
        lt.addWidget(QLabel("📥 下载管理"))
        self.dl_list = QListWidget()
        lt.addWidget(self.dl_list)
        ct.addLayout(lt, 1)

        # 中间：资源列表
        md = QVBoxLayout()

        ft = QHBoxLayout()
        ft.addWidget(QLabel("筛选:"))
        self.fb_all = QPushButton("全部")
        self.fb_all.clicked.connect(lambda: self._filter(None))
        ft.addWidget(self.fb_all)
        ft.addStretch()
        md.addLayout(ft)

        self.res_list = QListWidget()
        self.res_list.itemClicked.connect(self._preview)
        md.addWidget(self.res_list)

        cr = QHBoxLayout()
        cr.addWidget(QPushButton("☑ 全选", clicked=self._sel_all))
        cr.addWidget(QPushButton("☐ 取消", clicked=self._sel_none))
        self.cnt_label = QLabel("已选 0 项")
        cr.addWidget(self.cnt_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        cr.addWidget(self.progress)
        db = QPushButton("⬇  下 载")
        db.setMinimumWidth(100)
        db.clicked.connect(self._download)
        cr.addWidget(db)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.clicked.connect(self._stop_dl)
        cr.addWidget(self.stop_btn)

        md.addLayout(cr)
        ct.addLayout(md, 3)

        # 右侧：预览
        rt = QVBoxLayout()
        rt.addWidget(QLabel("📖 资源预览"))
        self.pv = QTextEdit()
        self.pv.setReadOnly(True)
        self.pv.setMinimumWidth(250)
        rt.addWidget(self.pv)
        ct.addLayout(rt, 1)

        lo.addLayout(ct, 1)

        # 状态栏
        self.st = QLabel("就绪")
        lo.addWidget(self.st)

    def _fetch(self):
        """抓取 - 每次创建新线程，无状态阻拦"""
        raw = self.url_input.text().strip()
        if not raw:
            return

        urls = [u.strip() for u in re.split(r'[,\n]+', raw) if u.strip()]
        if not urls:
            return

        norm = [u if u.startswith(("http://", "https://")) else "https://" + u for u in urls]

        if norm[0] not in self.history:
            self.history.insert(0, norm[0])
            if len(self.history) > 50:
                self.history = self.history[:50]
            _save_history(self.history)

        self.res_list.clear()
        self.pv.clear()
        self.st.setText(f"⏳ 正在抓取 {len(norm)} 个网页...")

        self._fetch_w = FetchWorker(norm)
        self._fetch_w.finished.connect(self._on_fetch_done)
        self._fetch_w.start()

    def _on_fetch_done(self, label, resources):
        self.resources = resources
        self.st.setText(f"✅ 找到 {len(resources)} 个资源")

        for r in resources:
            txt = f"[{r.rtype}] {r.name}"
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, r)
            it.setCheckState(Qt.Checked)
            self.res_list.addItem(it)

        self._upd_cnt()

    def _filter(self, ftype):
        self.res_list.clear()
        for r in self.resources:
            if ftype is None or r.rtype == ftype:
                it = QListWidgetItem(f"[{r.rtype}] {r.name}")
                it.setData(Qt.UserRole, r)
                it.setCheckState(Qt.Checked if getattr(r, 'checked', True) else Qt.Unchecked)
                self.res_list.addItem(it)
        self._upd_cnt()

    def _sel_all(self):
        for i in range(self.res_list.count()):
            self.res_list.item(i).setCheckState(Qt.Checked)
        self._upd_cnt()

    def _sel_none(self):
        for i in range(self.res_list.count()):
            self.res_list.item(i).setCheckState(Qt.Unchecked)
        self._upd_cnt()

    def _upd_cnt(self):
        n = sum(1 for i in range(self.res_list.count()) if self.res_list.item(i).checkState() == Qt.Checked)
        self.cnt_label.setText(f"已选 {n} 项")

    def _preview(self, item):
        r = item.data(Qt.UserRole)
        self.pv.setHtml(f"""
        <b>{r.rtype}</b><br><br>
        <b>文件名:</b> {r.name}<br><br>
        <b>URL:</b><br><small>{r.url}</small><br><br>
        <b>来源:</b> {getattr(r, 'source', '')}<br>
        """)

    def _download(self):
        checked = []
        for i in range(self.res_list.count()):
            item = self.res_list.item(i)
            if item.checkState() == Qt.Checked:
                checked.append(item.data(Qt.UserRole))

        if not checked:
            QMessageBox.information(self, "提示", "请先勾选要下载的资源")
            return

        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.downloading = True
        self.stop_flag.clear()
        self.st.setText("📻 开始下载...")
        self.dl_list.clear()

        # 记录下载项到列表
        for r in checked:
            self.dl_list.addItem(f"📥 下载中: {r.name}")

        self._dl_w = DownloadWorker(checked, self.save_dir, self.stop_flag)
        self._dl_w.progress.connect(self._on_dl_progress)
        self._dl_w.finished.connect(self._on_dl_done)
        self._dl_w.start()

    def _on_dl_progress(self, total, done, name, pct):
        """下载进度回写"""
        self.progress.setValue(pct)
        self.st.setText(f"📥 [{done}/{total}] {name[:30]}")

        # 更新下载列表最后一项
        cnt = self.dl_list.count()
        if cnt > 0:
            self.dl_list.item(cnt - 1).setText(f"[{pct}%] {name[:50]}")

    def _on_dl_done(self, ok, fail, stop):
        self.downloading = False
        self.progress.setValue(100)
        self.st.setText(f"✅ 完成: 成功 {len(ok)} 项, 失败 {len(fail)} 项")

        # 更新下载列表
        self.dl_list.clear()
        for _, path, sz in ok:
            fname = pathlib.Path(path).name
            sz_str = f"{sz/1024/1024:.1f}MB" if sz > 1024*1024 else f"{sz/1024:.0f}KB"
            self.dl_list.addItem(f"✅ {fname} ({sz_str})")
        for _, err in fail:
            self.dl_list.addItem(f"❌ {err[:50]}")

        msg = f"下载完成!\n\n成功: {len(ok)} 项\n失败: {len(fail)} 项"
        if stop:
            msg += f"\n取消: {len(stop)} 项"
        QMessageBox.information(self, "下载结果", msg)

    def _stop_dl(self):
        self.stop_flag.set()

    def _change_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", str(self.save_dir))
        if d:
            self.save_dir = pathlib.Path(d)
            cfg = _load_config()
            cfg["save_dir"] = d
            _save_config(cfg)
            self.st.setText(f"保存目录: {d}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
