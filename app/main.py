import hmac
import ipaddress
import re
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .config import Settings
from .db import Database
from .engine import EngineManager
from .sources import merge_ip_sources, parse_ip_list, read_text_file

settings = Settings.from_env()
settings.data_dir.mkdir(parents=True, exist_ok=True)
sources_dir = settings.data_dir / "sources"
sources_dir.mkdir(parents=True, exist_ok=True)
db = Database(settings.data_dir)
builtin_file = settings.engine_dir / "ip.txt"

with db.session() as conn:
    conn.execute(
        "INSERT OR IGNORE INTO sources(id,name,kind,path,enabled) VALUES('builtin','项目自带 IP 库','builtin',?,1)",
        (str(builtin_file),),
    )

engine = EngineManager(settings.data_dir, settings.engine_dir, db)
app = FastAPI(title="CFST TOP10", version="0.2.0")

def auth(authorization: str | None = Header(default=None)):
    if not authorization or not hmac.compare_digest(authorization, "Bearer " + settings.admin_token):
        raise HTTPException(status_code=401, detail="未授权")

class Toggle(BaseModel):
    enabled: bool

class RunRequest(BaseModel):
    top_n: int = 10

@app.on_event("shutdown")
def shutdown_engine():
    engine.stop()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>CFST TOP10</title><style>body{font:15px system-ui;background:#0b1220;color:#e8eefb;margin:28px}main{max-width:850px;margin:auto}section{background:#152039;padding:18px;border:1px solid #2b3b5b;border-radius:12px;margin:14px 0}input,button{padding:9px;border-radius:7px}pre{white-space:pre-wrap}</style>
<main><h1>CFST TOP10</h1><p>Docker 开发版 · IP 来源管理</p><section><input id="token" type="password" placeholder="管理 Token"><button onclick="load()">连接</button><p id="status">尚未连接</p></section>
<section><h2>来源列表</h2><div id="sources"></div><h3>上传 TXT 来源</h3><input id="name" placeholder="来源名称"><input id="file" type="file" accept=".txt"><button onclick="upload()">上传</button></section>
<section><h2>测速执行</h2><input id="topn" type="number" min="1" max="1000" value="10"><button onclick="runEngine()">开始测速</button> <button onclick="stopEngine()">停止测速</button> <button onclick="engineStatus()">刷新状态</button> <button onclick="downloadResult('ipv4')">下载 IPv4</button> <button onclick="downloadResult('ipv6')">下载 IPv6</button><pre id="engine">尚未执行</pre></section><section><h2>合并统计</h2><button onclick="preview()">预览合并</button><pre id="result"></pre></section></main>
<script>
const $=x=>document.getElementById(x), headers=()=>({Authorization:'Bearer '+$('token').value});
async function req(path,opt={}){let r=await fetch(path,{...opt,headers:{...headers(),...(opt.headers||{})}});let j=await r.json();if(!r.ok)throw Error(j.detail||'请求失败');return j}
async function load(){try{let a=await req('/api/sources');$('sources').innerHTML=a.map(x=>'<p>'+x.name+' · '+x.kind+' · '+x.entries+' 条 · '+(x.enabled?'启用':'停用')+' <button onclick="toggle(\''+x.id+'\','+(!x.enabled)+')">切换</button>'+(x.kind==='file'?' <button onclick="removeSource(\''+x.id+'\')">删除</button>':'' )+'</p>').join('');$('status').textContent='连接成功'}catch(e){$('status').textContent=e.message}}
async function upload(){try{let f=$('file').files[0];if(!f)throw Error('请选择 TXT');let d=new FormData();d.append('file',f);d.append('name',$('name').value||f.name);let r=await fetch('/api/sources/upload',{method:'POST',headers:headers(),body:d}),j=await r.json();if(!r.ok)throw Error(j.detail);await load()}catch(e){alert(e.message)}}
async function toggle(id,enabled){try{await req('/api/sources/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});load()}catch(e){alert(e.message)}}
async function removeSource(id){if(!confirm('删除这个来源？'))return;try{await req('/api/sources/'+id,{method:'DELETE'});load()}catch(e){alert(e.message)}}
async function preview(){try{$('result').textContent=JSON.stringify(await req('/api/sources/preview'),null,2)}catch(e){$('result').textContent=e.message}}
async function runEngine(){try{$('engine').textContent=JSON.stringify(await req('/api/engine/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({top_n:Number($('topn').value)})}),null,2)}catch(e){alert(e.message)}}
async function stopEngine(){try{$('engine').textContent=JSON.stringify(await req('/api/engine/stop',{method:'POST'}),null,2)}catch(e){alert(e.message)}}
async function engineStatus(){try{let s=await req('/api/engine/status'),l=await req('/api/engine/logs');$('engine').textContent=JSON.stringify(s,null,2)+'\n\n'+l.lines.join('\n')}catch(e){$('engine').textContent=e.message}}
async function downloadResult(family){try{let r=await fetch('/api/results/'+family,{headers:headers()});if(!r.ok)throw Error((await r.json()).detail||'下载失败');let b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=family+'.txt';a.click();URL.revokeObjectURL(u)}catch(e){alert(e.message)}}
</script></html>"""

@app.get("/api/sources", dependencies=[Depends(auth)])
def list_sources():
    result = []
    for row in db.list_sources():
        count = None
        path = Path(row["path"]) if row["path"] else None
        if path and path.is_file():
            try:
                count = len(parse_ip_list(read_text_file(path)).entries)
            except (OSError, ValueError, UnicodeDecodeError):
                count = 0
        result.append({"id":row["id"],"name":row["name"],"kind":row["kind"],
                       "enabled":bool(row["enabled"]),"entries":count})
    return result

@app.post("/api/sources/upload", dependencies=[Depends(auth)])
async def upload_source(name: str = "用户 TXT 来源", file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() != ".txt":
        raise HTTPException(400, "仅支持 TXT 文件")
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "文件超过 8 MiB")
    try:
        parsed = parse_ip_list(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if not parsed.entries:
        raise HTTPException(400, "没有有效 IP/CIDR")
    source_id = uuid.uuid4().hex
    safe_name = re.sub(r"[\x00-\x1f/\\]+", "_", name.strip())[:80] or "用户 TXT 来源"
    target = sources_dir / (source_id + ".txt")
    temp = target.with_suffix(".tmp")
    temp.write_text("\n".join(parsed.entries) + "\n", encoding="utf-8")
    temp.replace(target)
    try:
        db.add_file_source(source_id, safe_name, str(target))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"id":source_id,"name":safe_name,"entries":len(parsed.entries),
            "invalid":parsed.invalid,"duplicates":parsed.duplicates}

@app.patch("/api/sources/{source_id}", dependencies=[Depends(auth)])
def toggle_source(source_id: str, body: Toggle):
    if not db.set_enabled(source_id, body.enabled):
        raise HTTPException(404, "来源不存在或不可修改")
    return {"ok":True}

@app.delete("/api/sources/{source_id}", dependencies=[Depends(auth)])
def delete_source(source_id: str):
    row = next((x for x in db.list_sources() if x["id"] == source_id), None)
    if not row or row["kind"] != "file":
        raise HTTPException(404, "来源不存在或不可删除")
    if not db.delete_file_source(source_id):
        raise HTTPException(404, "来源不存在")
    if row["path"]:
        Path(row["path"]).unlink(missing_ok=True)
    return {"ok":True}

@app.get("/api/engine/status", dependencies=[Depends(auth)])
def engine_status():
    return engine.status()

@app.get("/api/engine/logs", dependencies=[Depends(auth)])
def engine_logs():
    return {"lines": engine.logs()}

@app.post("/api/engine/run", dependencies=[Depends(auth)])
def run_engine(body: RunRequest):
    try:
        return engine.start(body.top_n)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.post("/api/engine/stop", dependencies=[Depends(auth)])
def stop_engine():
    return engine.stop()

@app.get("/api/results/{family}", dependencies=[Depends(auth)])
def download_result(family: str):
    if family not in {"ipv4", "ipv6"}:
        raise HTTPException(404, "未知结果类型")
    target = settings.data_dir / f"{family}.txt"
    if not target.is_file():
        raise HTTPException(404, "暂无测速结果")
    return FileResponse(target, media_type="text/plain; charset=utf-8", filename=f"{family}.txt")
@app.get("/api/sources/preview", dependencies=[Depends(auth)])
def preview_sources():
    rows = [x for x in db.list_sources() if x["enabled"]]
    contents, stats = [], []
    for row in rows:
        path = Path(row["path"]) if row["path"] else None
        if path is None or not path.is_file():
            stats.append({"id":row["id"],"name":row["name"],"entries":0,"error":"来源文件不存在"})
            continue
        try:
            raw = read_text_file(path)
            parsed = parse_ip_list(raw)
            contents.append(raw)
            stats.append({"id":row["id"],"name":row["name"],"entries":len(parsed.entries),
                          "invalid":parsed.invalid,"duplicates":parsed.duplicates})
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            stats.append({"id":row["id"],"name":row["name"],"entries":0,"error":str(exc)})
    merged = merge_ip_sources(contents)
    return {"sources":stats,"total_before_dedup":sum(x.get("entries",0) + x.get("duplicates",0) for x in stats),
            "duplicates":merged.duplicates,"invalid":merged.invalid,
            "total_after_dedup":len(merged.entries),
            "ipv4":sum(1 for x in merged.entries if ipaddress.ip_network(x,strict=False).version==4),
            "ipv6":sum(1 for x in merged.entries if ipaddress.ip_network(x,strict=False).version==6)}
