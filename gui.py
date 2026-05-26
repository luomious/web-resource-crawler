"""
网页资源爬虫 — PyQt5 版 (彻底解决 Tkinter 线程问题)
"""
import sys, json, pathlib, re, threading
from typing import List, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QListWidget,
    QListWidgetItem, QFrame, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from core.scraper import fetch_html, parse_resources, Resource
from core.downloader import download_all

import os as _os
_appdata = pathlib.Path(_os.environ.get("APPDATA", pathlib.Path.home() / "AppData" / "Roaming"))
_config_dir = _appdata / "WebScraper"
_config_dir.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = _config_dir / "config.json"

def _load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except: pass
    return {}

def _save_config(cfg: dict):
    try: CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def _load_history() -> list:
    return _load_config().get("history", [])
def _save_history(urls: list):
    cfg = _load_config(); cfg["history"] = urls[:50]; _save_config(cfg)

class FetchWorker(QThread):
    finished = pyqtSignal(str, list)
    def __init__(self, urls: list):
        super().__init__(); self.urls = urls
    def run(self):
        all_resources = []
        for url in self.urls:
            try:
                html = fetch_html(url)
                res = parse_resources(html, url, source_url=url)
                all_resources.extend(res)
            except: pass
        label = self.urls[0] if len(self.urls)==1 else f"{len(self.urls)}个网页"
        self.finished.emit(label, all_resources)

class DownloadWorker(QThread):
    progress = pyqtSignal(int, int, str, int)
    finished = pyqtSignal(list, list, list)
    def __init__(self, rlist, savedir, stopflag):
        super().__init__(); self.rlist=rlist; self.savedir=savedir; self.stopflag=stopflag; self._c=0
    def run(self):
        def cb(t,d,n):
            p=min(int(d/t*100),100) if t else 0; self._c+=1
            if self._c%20==0 or "OK" in n: self.progress.emit(t,d,n,p)
        results = download_all(self.rlist, self.savedir, stop_flag=self.stopflag, progress_cb=cb)
        ok,fail,stop=[],[],[]
        for u,p in results:
            if p=="__STOPPED__": stop.append((u,p))
            elif p and pathlib.Path(p).exists():
                ok.append((u,p,pathlib.Path(p).stat().st_size))
            else: fail.append((u,p or "error"))
        self.finished.emit(ok,fail,stop)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web Resource Crawler")
        self.setGeometry(100,100,1200,800)
        self.resources:List[Resource]=[]
        self.downloading=False; self.stop_flag=threading.Event()
        self.history=_load_history()
        self.save_dir=pathlib.Path(_load_config().get("save_dir","E:/"))
        self._fetch:Optional[FetchWorker]=None; self._dl:Optional[DownloadWorker]=None
        self._build_ui()

    def _build_ui(self):
        c=QWidget(); self.setCentralWidget(c); lo=QVBoxLayout(c); lo.setSpacing(8); lo.setContentsMargins(12,12,12,12)
        t=QLabel("Web Resource Crawler"); t.setFont(QFont("Segoe UI",14)); lo.addWidget(t)
        uf=QFrame(); uf.setFrameStyle(QFrame.StyledPanel); ul=QVBoxLayout(uf)
        ul.addWidget(QLabel("URL:")); ir=QHBoxLayout()
        self.url=QLineEdit(); self.url.setPlaceholderText("https://..."); self.url.returnPressed.connect(self._do_fetch)
        ir.addWidget(self.url)
        fb=QPushButton("Fetch"); fb.clicked.connect(self._do_fetch); ir.addWidget(fb); ul.addLayout(ir)
        pr=QHBoxLayout(); pr.addWidget(QLabel("Save: "+str(self.save_dir)))
        ch=QPushButton("Change"); ch.clicked.connect(self._ch_dir); pr.addWidget(ch); pr.addStretch(); ul.addLayout(pr)
        lo.addWidget(uf)
        ct=QHBoxLayout()
        lt=QVBoxLayout(); lt.addWidget(QLabel("Downloads")); self.dl_list=QListWidget(); lt.addWidget(self.dl_list)
        ct.addLayout(lt,1)
        md=QVBoxLayout()
        self.res_list=QListWidget(); self.res_list.itemClicked.connect(self._preview); md.addWidget(self.res_list)
        cr=QHBoxLayout()
        cr.addWidget(QPushButton("All",clicked=self._sel_all)); cr.addWidget(QPushButton("None",clicked=self._sel_none))
        self.cnt=QLabel("0"); cr.addWidget(self.cnt)
        self.pb=QProgressBar(); self.pb.setRange(0,100); cr.addWidget(self.pb)
        db=QPushButton("Download"); db.clicked.connect(self._do_dl); cr.addWidget(db)
        md.addLayout(cr); ct.addLayout(md,3)
        rt=QVBoxLayout(); rt.addWidget(QLabel("Preview"))
        self.pv=QLabel("Click a resource"); self.pv.setAlignment(Qt.AlignCenter); self.pv.setMinimumWidth(220); rt.addWidget(self.pv)
        ct.addLayout(rt,1); lo.addLayout(ct,1)
        self.st=QLabel("Ready"); lo.addWidget(self.st)

    def _do_fetch(self):
        raw=self.url.text().strip()
        if not raw: return
        urls=[u.strip() for u in re.split(r'[,\n]+', raw) if u.strip()]
        if not urls: return
        norm=[u if u.startswith(("http://","https://")) else "https://"+u for u in urls]
        if norm[0] not in self.history: self.history.insert(0,norm[0]); _save_history(self.history)
        self.res_list.clear(); self.st.setText("Fetching...")
        self._fetch=FetchWorker(norm)
        self._fetch.finished.connect(self._on_fetch); self._fetch.start()

    def _on_fetch(self,label,resources):
        self.resources=resources; self.st.setText(f"Found {len(resources)} resources")
        for r in resources:
            it=QListWidgetItem(f"{r.rtype}: {r.name}"); it.setData(Qt.UserRole,r); it.setCheckState(Qt.Checked); self.res_list.addItem(it)
        self._upd_cnt()

    def _sel_all(self):
        for i in range(self.res_list.count()): self.res_list.item(i).setCheckState(Qt.Checked)
        self._upd_cnt()
    def _sel_none(self):
        for i in range(self.res_list.count()): self.res_list.item(i).setCheckState(Qt.Unchecked)
        self._upd_cnt()
    def _upd_cnt(self):
        n=sum(1 for i in range(self.res_list.count()) if self.res_list.item(i).checkState()==Qt.Checked)
        self.cnt.setText(str(n))

    def _preview(self,item):
        r=item.data(Qt.UserRole); self.pv.setText(f"{r.rtype}\n{r.name}\n{r.url}")

    def _do_dl(self):
        checked=[self.res_list.item(i).data(Qt.UserRole) for i in range(self.res_list.count()) if self.res_list.item(i).checkState()==Qt.Checked]
        if not checked: QMessageBox.information(self,"Info","Select resources first"); return
        self.save_dir.mkdir(parents=True,exist_ok=True); self.downloading=True; self.stop_flag.clear(); self.st.setText("Downloading...")
        self._dl=DownloadWorker(checked,self.save_dir,self.stop_flag)
        self._dl.progress.connect(self._on_prog); self._dl.finished.connect(self._on_done); self._dl.start()

    def _on_prog(self,t,d,n,p):
        self.pb.setValue(p); self.st.setText(f"[{d}/{t}] {n[:30]}"); self.dl_list.addItem(f"{n[:60]} ({p}%)")

    def _on_done(self,ok,fail,stop):
        self.downloading=False; self.pb.setValue(100); self.st.setText(f"Done: {len(ok)} ok, {len(fail)} failed")
        QMessageBox.information(self,"Result",f"OK: {len(ok)}\nFailed: {len(fail)}\nStopped: {len(stop) if stop else 0}")

    def _ch_dir(self):
        d=QFileDialog.getExistingDirectory(self,"Choose",str(self.save_dir))
        if d: self.save_dir=pathlib.Path(d); _save_config({**_load_config(),"save_dir":d})

if __name__=="__main__":
    app=QApplication(sys.argv); app.setFont(QFont("Segoe UI",10))
    w=MainWindow(); w.show(); sys.exit(app.exec_())
