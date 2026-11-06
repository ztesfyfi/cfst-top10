#!/usr/bin/env python3
import http.server, json, os, re, secrets, subprocess, threading, time, ipaddress
from pathlib import Path
from urllib.parse import urlparse

BASE = Path.home() / "CFST"
BIN = BASE / "cfst_linux_amd64"
CONFIG = BASE / "config"
TOKEN_FILE = BASE / ".panel-token"
LOG = BASE / "panel-task.log"
PID_FILE = BASE / ".panel-task.pid"
HOST = os.environ.get("CFST_PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("CFST_PANEL_PORT", "8765"))
MAX_BODY = 2 * 1024 * 1024
lock = threading.Lock()
task = None

def read_config():
    data = {}
    if CONFIG.exists():
        for line in CONFIG.read_text(errors="replace").splitlines():
            m = re.match(r"^([A-Z_]+)='(.*)'$", line)
            if m: data[m.group(1)] = m.group(2)
    return data

def valid_ips(raw):
    out, seen = [], set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        try:
            net = ipaddress.ip_network(line, strict=False)
        except ValueError:
            raise ValueError("无效 IP/CIDR: " + line[:100])
        normalized = str(net)
        if "/" not in line:
            normalized = str(net.network_address)
        if normalized not in seen:
            seen.add(normalized); out.append(normalized)
        if len(out) > 100000: raise ValueError("最多允许 100000 条地址/网段")
    if not out: raise ValueError("IP 列表不能为空")
    return "\n".join(out) + "\n", len(out)

def tail(path, limit=250):
    try: return path.read_text(errors="replace").splitlines()[-limit:]
    except OSError: return []

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "CFSTPanel/1.0"
    def log_message(self, fmt, *args):
        pass
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)
    def body(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n < 0 or n > MAX_BODY: raise ValueError("请求内容过大")
        return self.rfile.read(n)
    def authorized(self):
        return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + TOKEN)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            b = (BASE / "panel.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        if not self.authorized(): return self.send_json({"error":"未授权"}, 401)
        if path == "/api/status":
            cfg = read_config()
            ips = BIN / "ip.txt"
            result = BASE / "ips.txt"
            running = False
            if PID_FILE.exists():
                try:
                    p = int(PID_FILE.read_text().strip()); os.kill(p, 0); running = True
                except Exception: pass
            self.send_json({"running":running, "mode":"VPS远程发布" if cfg.get("MODE")=="2" else "本地模式",
                "ip_count":sum(1 for x in ips.read_text(errors="ignore").splitlines() if x.strip()) if ips.exists() else 0,
                "result_count":sum(1 for x in result.read_text(errors="ignore").splitlines() if x.strip()) if result.exists() else 0,
                "result_exists":result.exists(), "result_mtime":int(result.stat().st_mtime) if result.exists() else None,
                "target_count":cfg.get("IP_COUNT","10"), "publish_host":cfg.get("VPS_HOST","") or "未配置",
                "publish_dir":cfg.get("REMOTE_DIR","") or "未配置", "public_url":cfg.get("PUBLIC_URL",""),
                "schedule":"每天 03:30"})
        elif path == "/api/logs":
            self.send_json({"lines":tail(LOG)})
        elif path == "/api/ips":
            p = BIN / "ip.txt"
            self.send_json({"content":p.read_text(errors="replace") if p.exists() else ""})
        elif path == "/api/result":
            p = BASE / "ips.txt"
            if not p.exists(): return self.send_json({"error":"暂无结果"},404)
            b=p.read_bytes(); self.send_response(200); self.send_header("Content-Type","text/plain; charset=utf-8")
            self.send_header("Content-Disposition",'attachment; filename="ips.txt"'); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
        else: self.send_error(404)
    def do_POST(self):
        path=urlparse(self.path).path
        if not self.authorized(): return self.send_json({"error":"未授权"},401)
        try:
            raw=self.body()
            if path == "/api/ips":
                obj=json.loads(raw); content,count=valid_ips(obj.get("content",""))
                target=BIN/"ip.txt"; backup=BASE/"ip.txt.backup"
                if target.exists(): backup.write_bytes(target.read_bytes())
                tmp=target.with_suffix(".txt.tmp"); tmp.write_text(content); os.replace(tmp,target)
                return self.send_json({"ok":True,"count":count,"backup":str(backup)})
            if path == "/api/count":
                obj=json.loads(raw); n=int(obj.get("count",0))
                if not 1 <= n <= 100000: raise ValueError("数量范围为 1～100000")
                cfg=CONFIG.read_text()
                cfg=re.sub(r"(?m)^IP_COUNT='[^']*'$",f"IP_COUNT='{n}'",cfg)
                CONFIG.write_text(cfg); os.chmod(CONFIG,0o600)
                return self.send_json({"ok":True,"count":n})
            if path == "/api/run":
                with lock:
                    global task
                    if task and task.poll() is None: return self.send_json({"error":"测速任务正在运行"},409)
                    LOG.write_text("")
                    p=subprocess.Popen([str(BASE/"run.sh")],cwd=str(BASE),stdin=subprocess.DEVNULL,
                        stdout=open(LOG,"ab",buffering=0),stderr=subprocess.STDOUT,start_new_session=True)
                    task=p; PID_FILE.write_text(str(p.pid))
                return self.send_json({"ok":True,"pid":p.pid})
            if path == "/api/reset-ips":
                backup=BASE/"ip.txt.backup"
                if not backup.exists(): raise ValueError("没有找到备份 IP 文件")
                (BIN/"ip.txt").write_bytes(backup.read_bytes())
                return self.send_json({"ok":True})
            return self.send_error(404)
        except (ValueError,KeyError,json.JSONDecodeError) as e: return self.send_json({"error":str(e)},400)
        except Exception as e: return self.send_json({"error":str(e)},500)

TOKEN = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""
if not TOKEN:
    TOKEN=secrets.token_urlsafe(36); TOKEN_FILE.write_text(TOKEN); os.chmod(TOKEN_FILE,0o600)
(BASE/"panel.html").exists() or (_ for _ in ()).throw(SystemExit("缺少 panel.html"))
http.server.ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
