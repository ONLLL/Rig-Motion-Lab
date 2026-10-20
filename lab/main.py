"""Rig Motion Lab: local-only experimental motion workbench, port 8020."""
from __future__ import annotations
import io,json,os,threading,time,zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import FastAPI,Request,UploadFile,File,Form,HTTPException
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image,ImageDraw,ImageChops
from pydantic import ValidationError
from urllib.parse import urlparse
from . import storage,video
from .models import Project,Rig,Part,SaveRequest,BakeRequest,CropRequest,Reference,Motion,JOINTS,BONES,LABELS
from .demo import new_project,default_rig
from .motion import solve_project
from .renderer import prepare_preview,bake
from .reference import synthetic_reference

app=FastAPI(title='Rig Motion Lab',version='0.3.0')
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])
app.mount('/static',StaticFiles(directory=storage.ROOT/'lab/static'),name='static')
_jobs={};_jobs_lock=threading.Lock();_pool=ThreadPoolExecutor(max_workers=1)

@app.middleware('http')
async def local_guard(request:Request,call_next):
    if request.method in ('POST','PUT','PATCH','DELETE'):
        if request.headers.get('x-rig-request')!='1': return JSONResponse({'detail':'缺少本地请求标头 X-Rig-Request: 1。'},403)
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'): return JSONResponse({'detail':'拒绝跨站写入。'},403)
        try: length=int(request.headers.get('content-length','0'))
        except ValueError: return JSONResponse({'detail':'请求长度无效。'},400)
        if length>64*1024*1024 or request.headers.get('transfer-encoding'): return JSONResponse({'detail':'请求超过 64 MB 或使用了不受支持的分块上传。'},413)
    resp=await call_next(request)
    resp.headers['X-Content-Type-Options']='nosniff';resp.headers['Referrer-Policy']='no-referrer';resp.headers['X-Frame-Options']='DENY'
    if request.url.path.startswith('/api/'): resp.headers['Cache-Control']='no-store'
    return resp

@app.exception_handler(storage.Conflict)
async def conflict(request,exc): return JSONResponse({'detail':str(exc)},409)
@app.exception_handler(ValueError)
async def bad_value(request,exc): return JSONResponse({'detail':str(exc)[:800]},422)
@app.exception_handler(FileNotFoundError)
async def missing(request,exc): return JSONResponse({'detail':str(exc)[:200]},404)

@app.get('/')
def index(): return FileResponse(storage.ROOT/'lab/static/index.html')
@app.get('/api/health')
def health(): return {'ok':True,'version':'0.3.0','image_generation_calls':0}
@app.get('/api/config')
def config():
    return {'version':'0.3.0','joints':list(JOINTS),'labels':LABELS,'bones':BONES,
            'video':video.availability(),'api_keys_required':False,'editor_version':3,'motion_default':Motion().model_dump(),'scope':'Planar rig + fixed cutouts; not a trained motion generator.'}
@app.get('/api/projects')
def projects():
    out=[]
    for f in sorted(storage.data_root().glob('*/project.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:
        try:
            p=storage.load(f.parent.name);out.append({'id':p.id,'name':p.name,'revision':p.revision})
        except (ValueError,OSError): pass
    return out
@app.post('/api/projects')
def create(name:str=Form('新角色实验'),demo:bool=Form(False),short:bool=Form(False)):
    return storage.public(new_project(name,demo,short))
@app.get('/api/projects/{pid}')
def get_project(pid:str): return storage.public(storage.load(pid))
@app.put('/api/projects/{pid}')
def save_project(pid:str,body:SaveRequest):
    if pid!=body.project.id: raise ValueError('工程 ID 不匹配。')
    for part in body.project.parts: storage.asset_file(pid,part.image)
    if body.project.reference_image: storage.asset_file(pid,body.project.reference_image)
    return storage.public(storage.save(body.project,body.expected_revision))
@app.get('/api/projects/{pid}/assets/{name}')
def asset(pid:str,name:str): return FileResponse(storage.asset_file(pid,'assets/'+name),media_type='image/png')
@app.post('/api/projects/{pid}/solve')
def solve(pid:str):
    p=storage.load(pid);return prepare_preview(p,solve_project(p))


from .models import Strict
from pydantic import Field
class MotionConvertRequest(Strict):
    expected_revision: int = Field(ge=0)

@app.post('/api/projects/{pid}/motion/convert')
def convert_template(pid:str,body:MotionConvertRequest):
    from .poseclip import convert_to_keyframes
    p=storage.load(pid);check_revision(p,body.expected_revision)
    if p.motion.driver=='keyframes': raise ValueError('当前动作已经是姿势关键帧。')
    p.motion=convert_to_keyframes(p)
    return storage.public(storage.save(p,body.expected_revision))

@app.post('/api/projects/{pid}/motion/restore')
def restore_template(pid:str,body:MotionConvertRequest):
    p=storage.load(pid);check_revision(p,body.expected_revision)
    if p.motion.driver!='keyframes' or not p.motion.source_motion: raise ValueError('没有可恢复的参数模板。')
    # Keep present draw-order edits; restore the original motion parameters/offsets.
    layers=p.motion.layer_keys
    p.motion=Motion.model_validate(p.motion.source_motion)
    p.motion.layer_keys=layers
    return storage.public(storage.save(p,body.expected_revision))


def checked_image(file): return storage.open_image(file.file.read(8*1024*1024+1))

def check_revision(p,revision):
    if p.revision!=revision: raise storage.Conflict('工程版本已变化，请重新载入。')

@app.post('/api/projects/{pid}/reference-image')
def reference_image(pid:str,expected_revision:int=Form(...),file:UploadFile=File(...)):
    p=storage.load(pid);check_revision(p,expected_revision);im=checked_image(file)
    p.reference_image=storage.put_image(pid,im)
    alpha=im.getchannel('A');box=alpha.getbbox()
    x0,y0,x1,y1=box; h=y1-y0; s=1.1/max(h,1);cx=(x0+x1)/2
    p.reference_placement=(-cx*s,y1*s,im.width*s,im.height*s)
    p.rig=default_rig();p.rig.approved=False
    # Do not retain robot parts under a new user's reference. Originals remain on disk.
    p.parts=[]
    p.motion.layer_keys=[]
    for motion in p.motion_library.values(): motion.layer_keys=[]
    p.note='新参考图采用比例模板关节建议，不是识别结果。拖动确认并拆件/上传独立 PNG 后渲染。'
    return storage.public(storage.save(p,expected_revision))

@app.post('/api/projects/{pid}/part-image')
def part_image(pid:str,expected_revision:int=Form(...),bone:str=Form('weapon'),part_id:str=Form(''),file:UploadFile=File(...)):
    p=storage.load(pid);check_revision(p,expected_revision);im=checked_image(file);path=storage.put_image(pid,im)
    old=next((v for v in p.parts if v.id==part_id),None)
    if old: old.image=path;old.anchor_a=(.12,.5);old.anchor_b=(.88,.5)
    else: p.parts.append(Part(id=storage.uid(),name=(file.filename or '新部件')[:60],bone=bone,image=path,z=len(p.parts)))
    return storage.public(storage.save(p,expected_revision))

@app.post('/api/projects/{pid}/crop')
def crop(pid:str,body:CropRequest):
    p=storage.load(pid);check_revision(p,body.expected_revision)
    if not p.reference_image or not p.reference_placement: raise ValueError('请先上传角色参考图。')
    im=storage.image(pid,p.reference_image);mask=Image.new('L',im.size)
    polygon=[(round(x*(im.width-1)),round(y*(im.height-1))) for x,y in body.polygon]
    ImageDraw.Draw(mask).polygon(polygon,fill=255)
    alpha=ImageChops.multiply(im.getchannel('A'),mask);box=alpha.getbbox()
    if not box: raise ValueError('选区没有可见像素。')
    im.putalpha(alpha);cut=im.crop(box);path=storage.put_image(pid,cut)
    # Initialize source anchors from annotated bone endpoints in reference image space.
    left,top,ww,hh=p.reference_placement
    a,b=('r_wrist','r_elbow') if body.bone=='weapon' else BONES[body.bone]
    def local(j):
        x,y=p.rig.joints[j];px=(x-left)/ww*im.width-box[0];py=(top-y)/hh*im.height-box[1]
        return (max(0,min(1,px/cut.width)),max(0,min(1,py/cut.height)))
    aa,bb=local(a),local(b)
    import math
    if math.dist(aa,bb)<.02: aa,bb=(.12,.5),(.88,.5)
    p.parts.append(Part(id=storage.uid(),name=body.name,bone=body.bone,image=path,anchor_a=aa,anchor_b=bb,z=len(p.parts)))
    p.note='手工选区拆件不会补齐被遮挡的身体区域；转动后出现空洞需自行补画。'
    return storage.public(storage.save(p,body.expected_revision))

def activate_reference(p):
    """Keep a keyed walk/attack in its library when replacing reference input."""
    existing=p.motion if p.motion.kind=='reference' else p.motion_library.get('reference')
    if existing is not None and existing.driver=='keyframes':
        raise ValueError('参考动作已转换成关键帧；请先保存工程并返回该动作的参数模板，再导入新轨迹。')
    p.motion_library[p.motion.kind]=p.motion.model_copy(deep=True)
    p.motion=existing.model_copy(deep=True) if existing is not None else Motion(kind='reference',duration=p.motion.duration,frames=p.motion.frames,root_mode=p.motion.root_mode)
    p.motion.reference_bind=0

@app.post('/api/projects/{pid}/reference-example')
def reference_example(pid:str,expected_revision:int=Form(...)):
    p=storage.load(pid);check_revision(p,expected_revision);activate_reference(p);p.reference_motion=synthetic_reference()
    return storage.public(storage.save(p,expected_revision))
@app.post('/api/projects/{pid}/reference-motion')
def reference_motion(pid:str,expected_revision:int=Form(...),file:UploadFile=File(...)):
    p=storage.load(pid);check_revision(p,expected_revision);data=file.file.read(4*1024*1024+1)
    if len(data)>4*1024*1024: raise ValueError('轨迹 JSON 不得超过 4 MB。')
    ref=Reference.model_validate_json(data);activate_reference(p);p.reference_motion=ref
    return storage.public(storage.save(p,expected_revision))

@app.post('/api/projects/{pid}/video')
def upload_video(pid:str,expected_revision:int=Form(...),file:UploadFile=File(...)):
    p=storage.load(pid);check_revision(p,expected_revision)
    available=video.availability()
    if not all(available[k] for k in ('mediapipe','opencv','model_present')): raise HTTPException(409,'视频识别依赖或模型未安装。请按 README 配置；没有发起任何外部请求。')
    if Path(file.filename or '').suffix.lower() not in ('.mp4','.mov','.webm','.avi'): raise ValueError('仅接受视频文件。')
    data=file.file.read(50*1024*1024+1)
    if len(data)>50*1024*1024: raise ValueError('视频不得超过 50 MB。')
    with _jobs_lock:
        if any(j['status'] in ('queued','running') for j in _jobs.values()): raise HTTPException(409,'已有视频解析任务，请等待完成。')
        jid=storage.uid();_jobs[jid]={'id':jid,'status':'queued','progress':0,'pid':pid}
    tmp=storage.folder(pid)/(jid+Path(file.filename).suffix.lower());tmp.write_bytes(data)
    def run():
        try:
            _jobs[jid].update(status='running')
            ref,audit=video.extract_video(tmp,lambda n:_jobs[jid].update(progress=n))
            (storage.folder(pid)/(jid+'-observations.json')).write_text(json.dumps(audit,ensure_ascii=False),encoding='utf-8')
            (storage.folder(pid)/(jid+'-reference.json')).write_text(ref.model_dump_json(indent=2),encoding='utf-8')
            current=storage.load(pid);check_revision(current,expected_revision)
            activate_reference(current);current.reference_motion=ref
            storage.save(current,expected_revision);_jobs[jid].update(status='complete',progress=1)
        except (ValueError,OSError) as e: _jobs[jid].update(status='failed',error=str(e)[:700])
        except Exception:
            import logging;logging.getLogger('rig-lab').exception('Video analysis failed')
            _jobs[jid].update(status='failed',error='视频解析失败，请查看本地终端。没有自动重试。')
        finally: tmp.unlink(missing_ok=True)
    _pool.submit(run);return _jobs[jid]
@app.get('/api/jobs/{jid}')
def job(jid:str):
    if jid not in _jobs: raise FileNotFoundError('任务不存在或服务已重启。')
    return _jobs[jid]

@app.post('/api/projects/{pid}/export')
def export(pid:str,body:BakeRequest):
    p=storage.load(pid);check_revision(p,body.expected_revision)
    result=bake(p,solve_project(p),body.size,body.allow_clipping)
    return Response(result,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="rig-motion-frames.zip"'})

@app.get('/api/projects/{pid}/download')
def project_download(pid:str):
    p=storage.load(pid);files={v.image for v in p.parts}
    if p.reference_image: files.add(p.reference_image)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json',p.model_dump_json(indent=2))
        for f in sorted(files): z.writestr(f,storage.asset_file(pid,f).read_bytes())
    return Response(buf.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="character.riglab.zip"'})

@app.post('/api/import-project')
def import_project(file:UploadFile=File(...)):
    data=file.file.read(64*1024*1024+1)
    if len(data)>64*1024*1024: raise ValueError('工程包超过 64 MB。')
    try: z=zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc: raise ValueError('不是有效工程 ZIP。') from exc
    with z:
        names=z.namelist();infos=z.infolist()
        if len(names)>40 or len(set(names))!=len(names) or sum(v.file_size for v in infos)>64*1024*1024: raise ValueError('工程包有重复文件或超过大小限制。')
        if 'project.json' not in names or z.getinfo('project.json').file_size>8*1024*1024: raise ValueError('缺少有效 project.json。')
        p=Project.model_validate_json(z.read('project.json'));newid=storage.uid()
        expected={a.image for a in p.parts}|({'project.json',p.reference_image} if p.reference_image else {'project.json'})
        if set(names)!=expected: raise ValueError('工程包文件清单不匹配；拒绝未声明路径。')
        images={name:storage.open_image(z.read(name)) for name in names if name!='project.json'}
        p.id=newid;p.revision=0
        for path,im in images.items():
            out=storage.folder(newid)/path;out.parent.mkdir(parents=True,exist_ok=True);im.save(out,'PNG')
        return storage.public(storage.save(p))

# Structure editing is separate from pose keyframing. Existing save/zip APIs
# persist both; the same revision lease prevents overwriting a newer project.
from .editing import RigEdit, edit_rig

@app.post('/api/projects/{pid}/rig/edit')
def edit_structure(pid:str,body:RigEdit):
    p=storage.load(pid);check_revision(p,body.expected_revision)
    p.rig=edit_rig(p.rig,body)
    return storage.public(storage.save(p,body.expected_revision))
