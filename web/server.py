#!/usr/bin/env python
"""
网页资源爬虫 - 本地 HTTP 服务器
启动: python server.py
打开: http://localhost:18777
"""
import json, re, pathlib, threading, time, uuid, sys, io
import requests as _requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PORT = 18777
SAVE_DIR = pathlib.Path("E:/downloads")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# 核心模块
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from core.scraper import fetch_html, parse_resources, Resource
from core.downloader import download_all

# 任务管理
_tasks = {}

def start_download(resources):
    """在后台线程启动下载"""
    task_id = str(uuid.uuid4())[:8]
    stop = threading.Event()
    log = []
    progress_info = {"total": 0, "done": 0, "name": "", "pct": 0, "done_flag": False,
                     "ok": 0, "fail": 0, "resources": []}

    def cb(t, d, n):
        pct = min(int(d / t * 100), 100) if t else 0
        progress_info["total"] = t
        progress_info["done"] = d
        progress_info["name"] = n
        progress_info["pct"] = pct
        log.append(f"[{pct}%] {n[:60]}")

    def _run():
        try:
            results = download_all(resources, SAVE_DIR, stop_flag=stop, progress_cb=cb)
            ok = sum(1 for u, p in results if p and pathlib.Path(p).exists())
            fail = len(results) - ok
            progress_info["ok"] = ok
            progress_info["fail"] = fail
            progress_info["done_flag"] = True
            progress_info["pct"] = 100
            for u, p in results:
                if p and pathlib.Path(p).exists():
                    log.append(f"✅ {pathlib.Path(p).name}")
                else:
                    log.append(f"❌ {p or u}")
        except Exception as e:
            progress_info["done_flag"] = True
            progress_info["fail"] = len(resources)
            log.append(f"❌ 异常: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _tasks[task_id] = {"thread": t, "stop": stop, "info": progress_info, "log": log}
    return task_id

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_OPTIONS(self): self._cors()

    def _cors(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            html = (pathlib.Path(__file__).parent / "index.html").read_text(encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if path == "/progress":
            qs = parse_qs(urlparse(self.path).query)
            task_id = qs.get("task", [None])[0]
            task = _tasks.get(task_id)
            if not task:
                self._json({"done": True, "ok": 0, "fail": 0, "status": "任务不存在"}, 404)
                return
            info = task["info"]
            self._json({
                "done": info["done_flag"],
                "pct": info["pct"],
                "ok": info["ok"],
                "fail": info["fail"],
                "status": info["name"] if not info["done_flag"] else f"成功 {info['ok']}, 失败 {info['fail']}",
                "log": task["log"][-20:]
            })
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/fetch":
            urls = body.get("urls", [])
            norm = []
            for u in urls:
                u = u.strip()
                if u:
                    if not u.startswith(("http://", "https://")):
                        u = "https://" + u
                    norm.append(u)

            all_resources = []
            for url in norm:
                try:
                    # asmr.one API 直连
                    m = re.search(r'asmr\.one/work/(RJ\d+)', url, re.I)
                    if m:
                        rj = m.group(1)
                        info = _requests.get(f"https://api.asmr.one/api/workInfo/{rj}",
                                      headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                        work_id = info.json().get("id")
                        if work_id:
                            tracks = _requests.get(f"https://api.asmr.one/api/tracks/{work_id}",
                                           headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                            tree = tracks.json()

                            def walk(nodes, prefix=""):
                                out = []
                                if isinstance(nodes, list):
                                    for n in nodes: out.extend(walk(n, prefix))
                                elif isinstance(nodes, dict):
                                    t = nodes.get("type", "")
                                    title = nodes.get("title", "?")
                                    p = (prefix + "/" + title) if prefix else title
                                    if t == "audio":
                                        dl = nodes.get("mediaDownloadUrl", "") or nodes.get("mediaStreamUrl", "")
                                        if dl: out.append({"name": p, "url": dl, "rtype": "音频", "checked": False})
                                    elif t == "text":
                                        dl = nodes.get("mediaDownloadUrl", "")
                                        if dl and title: out.append({"name": p, "url": dl, "rtype": "字幕", "checked": False})
                                    elif t == "folder":
                                        for c in nodes.get("children", []):
                                            out.extend(walk(c, p))
                                return out
                            all_resources.extend(walk(tree))
                            continue
                    html = fetch_html(url)
                    res = parse_resources(html, url, source_url=url)
                    for r in res:
                        all_resources.append({"name": r.name, "url": r.url, "rtype": r.rtype, "checked": r.checked})
                except Exception as e:
                    pass
            self._json({"resources": all_resources})
            return

        if path == "/download":
            res_list = body.get("resources", [])
            resources = []
            for r in res_list:
                obj = Resource(url=r["url"], rtype=r["rtype"], name=r["name"], source="")
                resources.append(obj)
            task_id = start_download(resources)
            self._json({"taskId": task_id})
            return

        if path == "/stop":
            for t in _tasks.values():
                t["stop"].set()
            self._json({"ok": True})
            return

        self._json({"error": "not found"}, 404)

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"服务已启动: http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
