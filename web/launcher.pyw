#!/usr/bin/env pythonw
"""网页资源爬虫 - 自包含启动器"""
import http.server, webbrowser, threading, json, re, pathlib, sys, io, urllib.parse, uuid

sys.path.insert(0, r'E:\VSCode\VSCode-Workspace\Web Resource Crawler')
from core.scraper import fetch_html, parse_resources, Resource
from core.downloader import download_all
import requests as _rq

PORT = 18777
SAVE_DIR = pathlib.Path(r'E:\VSCode\VSCode-Workspace\Web Resource Crawler\downloads')
SAVE_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR = pathlib.Path(__file__).parent / "web"
_tasks = {}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def _cors(self):self.send_response(200);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Methods','GET,POST');self.send_header('Access-Control-Allow-Headers','Content-Type');self.end_headers()
    def _out(self,d,c=200,ct='application/json'):
        self.send_response(c);self.send_header('Content-Type',ct+';charset=utf-8');self.send_header('Access-Control-Allow-Origin','*');self.end_headers()
        if isinstance(d,str):self.wfile.write(d.encode('utf-8'))
        else:self.wfile.write(json.dumps(d,ensure_ascii=False).encode('utf-8'))
    def do_OPTIONS(self):self._cors()
    def do_GET(self):
        p=urllib.parse.urlparse(self.path).path
        if p=='/':
            html=(WEB_DIR/'index.html').read_text(encoding='utf-8');return self._out(html,200,'text/html')
        if p=='/progress':
            q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query);tid=q.get('task',[None])[0];t=_tasks.get(tid)
            if not t:return self._out({'done':True},404)
            i=t['info'];return self._out({'done':i['done_flag'],'pct':i['pct'],'ok':i['ok'],'fail':i['fail'],'status':i['name'],'log':t['log'][-20:]})
    def do_POST(self):
        p=urllib.parse.urlparse(self.path).path;l=int(self.headers.get('Content-Length',0));b=json.loads(self.rfile.read(l)) if l else {}
        if p=='/fetch':
            res=[]
            for url in [u if u.startswith('http') else 'https://'+u for u in b.get('urls',[]) if u.strip()]:
                try:
                    m=re.search(r'asmr\.one/work/(RJ\d+)',url,re.I)
                    if m:
                        rj=m.group(1)
                        info=_rq.get(f'https://api.asmr.one/api/workInfo/{rj}',headers={'User-Agent':'Mozilla/5.0'},timeout=15)
                        wid=info.json().get('id')
                        if wid:
                            tr=_rq.get(f'https://api.asmr.one/api/tracks/{wid}',headers={'User-Agent':'Mozilla/5.0'},timeout=15)
                            def walk(ns,px=''):
                                out=[]
                                if isinstance(ns,list):
                                    for n in ns:out.extend(walk(n,px))
                                elif isinstance(ns,dict):
                                    t=ns.get('type','');ti=ns.get('title','?');pth=(px+'/'+ti) if px else ti
                                    if t=='audio':
                                        dl=ns.get('mediaDownloadUrl','') or ns.get('mediaStreamUrl','')
                                        if dl:out.append({'name':pth,'url':dl,'rtype':'audio','checked':False})
                                    elif t=='text':
                                        dl=ns.get('mediaDownloadUrl','')
                                        if dl:out.append({'name':pth,'url':dl,'rtype':'subtitle','checked':False})
                                    elif t=='folder':
                                        for c in ns.get('children',[]):out.extend(walk(c,pth))
                                return out
                            res.extend(walk(tr.json()));continue
                    html=fetch_html(url);rr=parse_resources(html,url,source_url=url)
                    for r in rr:res.append({'name':r.name,'url':r.url,'rtype':r.rtype,'checked':r.checked})
                except:pass
            return self._out({'resources':res})
        if p=='/download':
            rlist=[Resource(url=x['url'],rtype=x['rtype'],name=x['name'],source='') for x in b.get('resources',[])]
            tid=str(uuid.uuid4())[:8];stop=threading.Event();log=[];info={'total':0,'done':0,'name':'','pct':0,'done_flag':False,'ok':0,'fail':0}
            def cb(t,d,n):
                pct=min(int(d/t*100),100) if t else 0;info.update(total=t,done=d,name=n,pct=pct);log.append(f'[{pct}%] {n[:60]}')
            def _run():
                try:
                    r=download_all(rlist,SAVE_DIR,stop_flag=stop,progress_cb=cb)
                    info['ok']=sum(1 for u,p in r if p and pathlib.Path(p).exists());info['fail']=len(r)-info['ok'];info['done_flag']=True;info['pct']=100
                except Exception as e:info['done_flag']=True;info['fail']=len(rlist)
            t=threading.Thread(target=_run,daemon=True);t.start();_tasks[tid]={'thread':t,'stop':stop,'info':info,'log':log}
            return self._out({'taskId':tid})
        if p=='/stop':
            for t in _tasks.values():t['stop'].set();return self._out({'ok':True})

if __name__=='__main__':
    threading.Thread(target=lambda:webbrowser.open(f'http://localhost:{PORT}'),daemon=True).start()
    http.server.HTTPServer(('0.0.0.0',PORT),H).serve_forever()
