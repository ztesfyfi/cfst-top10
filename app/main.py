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
from .publish import Publisher, PublishError
from .scheduler import Scheduler

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
publisher = Publisher(settings.data_dir)
scheduler = Scheduler(settings.data_dir, engine)
app = FastAPI(title="CFST TOP10", version="0.2.0")

def auth(authorization: str | None = Header(default=None)):
    if not authorization or not hmac.compare_digest(authorization, "Bearer " + settings.admin_token):
        raise HTTPException(status_code=401, detail="未授权")

class Toggle(BaseModel):
    enabled: bool

class RunRequest(BaseModel):
    top_n: int = 10

class PublishConfigRequest(BaseModel):
    gist_id: str | None = None
    github_token: str | None = None
    worker_url: str | None = None
    worker_token: str | None = None

class ScheduleRequest(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    interval_hours: int | None = None
    daily_time: str | None = None
    timezone: str | None = None
    top_n: int | None = None

@app.on_event("startup")
def startup_scheduler():
    scheduler.start()

@app.on_event("shutdown")
def shutdown_engine():
    scheduler.stop()
    engine.stop()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CFST TOP10</title>
<style>
:root{color-scheme:dark;--bg:#0a1020;--panel:#131e34;--line:#263653;--muted:#9aabc5;--text:#edf3ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#172746 0,var(--bg) 55%);color:var(--text);font:14px system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1600px;margin:auto;padding:14px;min-height:100vh;display:flex;flex-direction:column;gap:10px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:48px}h1{font-size:21px;margin:0}h2{font-size:15px;margin:0 0 9px}h3{font-size:13px;margin:9px 0 5px;color:#c9d8ef}
.sub,.muted,small{color:var(--muted)}.login{display:flex;gap:7px;align-items:center}.login input{width:210px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;flex:1;min-height:0}
.card{background:linear-gradient(145deg,#17243d,#111b30);border:1px solid var(--line);border-radius:12px;padding:12px;min-width:0;overflow:auto}
.card.wide{grid-column:span 2}.row{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.split{display:flex;justify-content:space-between;align-items:center;gap:8px}
input,select,button{font:inherit;border-radius:7px;border:1px solid #344765;background:#0d1729;color:var(--text);padding:8px;min-width:0}
input[type=number]{width:80px}input[type=time]{width:120px}button{cursor:pointer;background:#203657;border-color:#38547d}button:hover{filter:brightness(1.18)}button.primary{background:#28549a}button.danger{background:#65323d}
input:focus,select:focus,button:focus{outline:2px solid #6ca4ff;outline-offset:1px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1424;border:1px solid #23334f;border-radius:8px;padding:8px;margin:8px 0 0;max-height:115px;overflow:auto;font:12px ui-monospace,monospace}
.pill{display:inline-block;border-radius:20px;padding:3px 8px;background:#263653;color:#cfe0fa;font-size:12px}.source{padding:5px 0;border-bottom:1px solid #263653}.source:last-child{border:0}
.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.field{min-width:0}.field input{width:100%}.secret{display:flex;gap:5px}.secret input{flex:1;width:40px}
.stat{display:flex;gap:12px;flex-wrap:wrap}.stat b{font-size:18px}.actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
@media(max-width:760px){main{padding:10px}.grid{grid-template-columns:1fr}.card.wide{grid-column:span 1}header{align-items:flex-start;flex-direction:column}.login{width:100%}.login input{flex:1;width:60px}.fields{grid-template-columns:1fr}}
@media(min-width:761px) and (min-height:850px){body{overflow:hidden}.grid{grid-template-rows:repeat(3,minmax(0,1fr))}.card{overflow:auto}}
@media(max-height:849px) and (min-width:761px){main{min-height:100vh}.grid{grid-template-rows:auto auto auto}}
</style></head><body><main>
<header><div><h1>CFST TOP10</h1><div class="sub">Cloudflare IP 优选 · 本地 Docker 管理面板</div></div><div class="login"><input id="token" type="password" placeholder="管理 Token"><button class="primary" onclick="load()">连接面板</button><span id="status" class="muted">未连接</span></div></header>
<div class="grid">
<section class="card"><div class="split"><h2>IP 来源</h2><button onclick="loadSources()">刷新</button></div><div id="sources" class="muted">连接后加载来源</div><div class="row" style="margin-top:8px"><input id="name" placeholder="来源名称" style="flex:1"><input id="file" type="file" accept=".txt" style="max-width:180px"><button onclick="upload()">上传 TXT</button></div><div class="actions"><button onclick="preview()">合并预览</button></div><pre id="merge">尚无合并统计</pre></section>
<section class="card"><div class="split"><h2>测速任务</h2><span id="taskBadge" class="pill">未连接</span></div><div class="row">TOP N <input id="topn" type="number" min="1" max="1000" value="10"><button id="runBtn" class="primary" onclick="runEngine()">开始测速</button><button id="stopBtn" class="danger" onclick="stopEngine()">停止</button><button onclick="engineStatus()">刷新状态</button></div><div id="taskSummary" class="muted" style="margin-top:9px">等待任务状态</div><pre id="engine">尚未执行</pre></section>
<section class="card"><h2>定时测速</h2><div class="row"><label><input id="schedEnabled" type="checkbox"> 启用</label><select id="schedMode" onchange="modeChanged()"><option value="interval">每隔 N 小时</option><option value="daily">每天指定时间</option></select></div><div class="row" style="margin-top:8px"><span id="intervalLabel">间隔小时</span><input id="intervalHours" type="number" min="1" max="720" value="12"><span id="dailyLabel" hidden>每日时间</span><input id="dailyTime" type="time" value="03:30" hidden></div><div class="row" style="margin-top:8px">时区 <input id="timezone" value="Asia/Shanghai" style="flex:1"> TOP N <input id="schedTopn" type="number" min="1" max="1000" value="10"></div><div class="actions"><button class="primary" onclick="saveSchedule()">保存定时设置</button><button onclick="loadSchedule()">刷新</button></div><pre id="scheduleInfo">尚未读取定时配置</pre></section>
<section class="card"><h2>测速结果与发布</h2><div class="stat"><div>IPv4 <b id="v4count">—</b></div><div>IPv6 <b id="v6count">—</b></div></div><div class="actions"><button onclick="downloadResult('ipv4')">下载 IPv4 TXT</button><button onclick="downloadResult('ipv6')">下载 IPv6 TXT</button></div><h3>手动发布</h3><div class="row">IPv4 <button onclick="publishOne('gist','ipv4')">Gist</button><button onclick="publishOne('cloudflare','ipv4')">CF</button><button onclick="publishOne('all','ipv4')">双发布</button></div><div class="row" style="margin-top:6px">IPv6 <button onclick="publishOne('gist','ipv6')">Gist</button><button onclick="publishOne('cloudflare','ipv6')">CF</button><button onclick="publishOne('all','ipv6')">双发布</button></div><pre id="publishStatus">发布状态尚未加载</pre></section>
<section class="card wide"><div class="split"><h2>发布凭据配置</h2><span class="muted">重新打开面板会读取已保存值；默认星号遮罩</span></div><div class="fields">
<div class="field"><label>Gist ID</label><input id="gistId" autocomplete="off" placeholder="Gist ID"></div>
<div class="field"><label>GitHub Token</label><div class="secret"><input id="gistToken" type="password" autocomplete="off" placeholder="已保存"><button type="button" onclick="toggleSecret('gistToken',this)">显示</button></div></div>
<div class="field"><label>Cloudflare Worker HTTPS 地址</label><input id="workerUrl" type="url" placeholder="https://你的 Worker 域名"></div>
<div class="field"><label>Worker 上传 Token</label><div class="secret"><input id="workerToken" type="password" autocomplete="off" placeholder="已保存"><button type="button" onclick="toggleSecret('workerToken',this)">显示</button></div></div>
</div><div class="actions"><button class="primary" onclick="savePublishConfig()">保存发布配置</button><button onclick="loadPublishConfig()">重新读取配置</button><span id="configStatus" class="muted">未读取</span></div></section>
</div></main>
<script>
const $=x=>document.getElementById(x),headers=()=>({Authorization:'Bearer '+$('token').value});
async function req(path,opt={}){let r=await fetch(path,{...opt,headers:{...headers(),...(opt.headers||{})}});let j=await r.json();if(!r.ok)throw Error(j.detail||'请求失败');return j}
async function load(){try{await req('/api/sources');$('status').textContent='已连接';await Promise.all([loadSources(),preview(),engineStatus(),loadSchedule(),loadPublishConfig(),publishStatus()])}catch(e){$('status').textContent=e.message}}
async function loadSources(){try{let a=await req('/api/sources');$('sources').innerHTML=a.map(x=>'<div class="source">'+x.name+' · '+x.kind+' · '+(x.entries??'—')+' 条 · '+(x.enabled?'启用':'停用')+' <button onclick="toggle(\''+x.id+'\','+(!x.enabled)+')">切换</button>'+(x.kind==='file'?' <button onclick="removeSource(\''+x.id+'\')">删除</button>':'' )+'</div>').join('')}catch(e){$('sources').textContent=e.message}}
async function upload(){try{let f=$('file').files[0];if(!f)throw Error('请选择 TXT');let d=new FormData();d.append('file',f);d.append('name',$('name').value||f.name);let r=await fetch('/api/sources/upload',{method:'POST',headers:headers(),body:d}),j=await r.json();if(!r.ok)throw Error(j.detail);await loadSources()}catch(e){alert(e.message)}}
async function toggle(id,enabled){try{await req('/api/sources/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});loadSources()}catch(e){alert(e.message)}}
async function removeSource(id){if(!confirm('删除这个来源？'))return;try{await req('/api/sources/'+id,{method:'DELETE'});loadSources()}catch(e){alert(e.message)}}
async function preview(){try{$('merge').textContent=JSON.stringify(await req('/api/sources/preview'),null,2)}catch(e){$('merge').textContent=e.message}}
async function runEngine(){try{let s=await req('/api/engine/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({top_n:Number($('topn').value)})});$('engine').textContent=JSON.stringify(s,null,2);engineStatus()}catch(e){alert(e.message)}}
async function stopEngine(){try{await req('/api/engine/stop',{method:'POST'});engineStatus()}catch(e){alert(e.message)}}
async function engineStatus(){try{let s=await req('/api/engine/status'),l=await req('/api/engine/logs');$('taskBadge').textContent=s.status;$('runBtn').disabled=['running','stopping'].includes(s.status);$('stopBtn').disabled=!['running','stopping'].includes(s.status);$('taskSummary').textContent='阶段：'+(s.phase||'—')+' · 协议：'+(s.current_family||'—')+' · 候选：'+(s.candidate_count??0)+' · 已完成协议：'+(s.completed_families||[]).join(',')+' · 耗时：'+(s.elapsed_seconds??0)+' 秒';$('engine').textContent=JSON.stringify(s,null,2)+'\n'+l.lines.join('\n');$('v4count').textContent=s.results?.ipv4?.count??'—';$('v6count').textContent=s.results?.ipv6?.count??'—'}catch(e){$('engine').textContent=e.message}}
async function downloadResult(f){try{let r=await fetch('/api/results/'+f,{headers:headers()});if(!r.ok)throw Error((await r.json()).detail||'下载失败');let b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=f+'.txt';a.click();URL.revokeObjectURL(u)}catch(e){alert(e.message)}}
function modeChanged(){let d=$('schedMode').value==='daily';$('intervalHours').hidden=d;$('intervalLabel').hidden=d;$('dailyTime').hidden=!d;$('dailyLabel').hidden=!d}
async function loadSchedule(){try{let s=await req('/api/schedule');$('schedEnabled').checked=s.enabled;$('schedMode').value=s.mode;$('intervalHours').value=s.interval_hours;$('dailyTime').value=s.daily_time;$('timezone').value=s.timezone;$('schedTopn').value=s.top_n;modeChanged();$('scheduleInfo').textContent='下次执行：'+(s.next_run_at||'未启用')+'\n上次执行：'+(s.last_run_at||'暂无')+'\n上次结果：'+JSON.stringify(s.last_result||'暂无')+'\n调度器：'+(s.scheduler_running?'运行中':'未运行')}catch(e){$('scheduleInfo').textContent=e.message}}
async function saveSchedule(){try{let b={enabled:$('schedEnabled').checked,mode:$('schedMode').value,interval_hours:Number($('intervalHours').value),daily_time:$('dailyTime').value,timezone:$('timezone').value,top_n:Number($('schedTopn').value)};await req('/api/schedule',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});await loadSchedule()}catch(e){alert(e.message)}}
async function publishStatus(){try{let s=await req('/api/publish/status');$('publishStatus').textContent=JSON.stringify(s.targets,null,2)}catch(e){$('publishStatus').textContent=e.message}}
function toggleSecret(id,b){let e=$(id),show=e.type==='password';e.type=show?'text':'password';b.textContent=show?'隐藏':'显示'}
async function loadPublishConfig(){try{let s=await req('/api/publish/config');$('gistId').value=s.gist_id||'';$('gistToken').value=s.github_token||'';$('workerUrl').value=s.worker_url||'';$('workerToken').value=s.worker_token||'';$('gistToken').placeholder=s.github_token?'已保存（留空保持原值）':'尚未配置';$('workerToken').placeholder=s.worker_token?'已保存（留空保持原值）':'尚未配置';$('gistToken').type='password';$('workerToken').type='password';$('configStatus').textContent='已读取本地保存配置'}catch(e){$('configStatus').textContent=e.message}}
async function savePublishConfig(){try{await req('/api/publish/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({gist_id:$('gistId').value,github_token:$('gistToken').value,worker_url:$('workerUrl').value,worker_token:$('workerToken').value})});$('configStatus').textContent='配置已保存';await loadPublishConfig();await publishStatus()}catch(e){$('configStatus').textContent=e.message}}
async function publishOne(t,f){try{let p=t==='all'?'/api/publish/all/'+f:'/api/publish/one/'+t+'/'+f;let r=await req(p,{method:'POST'});$('publishStatus').textContent=JSON.stringify(r,null,2);await publishStatus()}catch(e){$('publishStatus').textContent=e.message;await publishStatus()}}
setInterval(()=>{if($('token').value)engineStatus()},3000);
</script></body></html>"""

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

@app.get("/api/schedule", dependencies=[Depends(auth)])
def get_schedule():
    return scheduler.status()

@app.put("/api/schedule", dependencies=[Depends(auth)])
def update_schedule(body: ScheduleRequest):
    try:
        return scheduler.update(body.model_dump(exclude_unset=True))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc

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


@app.get("/api/publish/status", dependencies=[Depends(auth)])
def publish_status():
    return publisher.status()

@app.get("/api/publish/config", dependencies=[Depends(auth)])
def get_publish_config():
    return publisher.config_for_ui()


@app.put("/api/publish/config", dependencies=[Depends(auth)])
def save_publish_config(body: PublishConfigRequest):
    try:
        return publisher.save_config(body.model_dump(exclude_unset=True))
    except PublishError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/publish/one/{target}/{family}", dependencies=[Depends(auth)])
def publish_result(target: str, family: str):
    try:
        return publisher.publish(target, family)
    except PublishError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/publish/all/{family}", dependencies=[Depends(auth)])
def publish_all_results(family: str):
    if family not in {"ipv4", "ipv6"}:
        raise HTTPException(404, "未知结果类型")
    return publisher.publish_all(family)
