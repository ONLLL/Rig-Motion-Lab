"""Local-only project store; generated IDs, atomic revisions, bounded image IO."""
from __future__ import annotations
import io, json, os, re, threading, uuid
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from dotenv import load_dotenv
from .models import Project
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
_LOCK=threading.RLock()

class Conflict(ValueError): pass

def data_root():
    p=Path(os.getenv('RIG_LAB_DATA_DIR',str(ROOT/'data'))).expanduser().resolve()
    p.mkdir(parents=True,exist_ok=True); return p

def uid(): return uuid.uuid4().hex

def folder(pid):
    if not re.fullmatch(r'[a-f0-9]{32}',pid): raise ValueError('无效工程 ID。')
    return data_root()/pid

def load(pid):
    file=folder(pid)/'project.json'
    if not file.is_file(): raise FileNotFoundError('工程不存在。')
    return Project.model_validate_json(file.read_text('utf-8'))

def save(p:Project,expected=None):
    # Revalidate in-place list/field edits before persisting the complete state.
    p=Project.model_validate(p.model_dump())
    with _LOCK:
        d=folder(p.id); d.mkdir(parents=True,exist_ok=True)
        file=d/'project.json'
        if file.exists():
            old=load(p.id)
            if expected is None or old.revision!=expected: raise Conflict('工程已更新，请重新载入后再保存，避免覆盖。')
            p=p.model_copy(deep=True); p.revision=old.revision+1
        elif expected not in (None,0): raise Conflict('工程尚未创建。')
        else: p=p.model_copy(deep=True); p.revision=1
        tmp=d/('project-'+uid()+'.tmp')
        tmp.write_text(p.model_dump_json(indent=2),encoding='utf-8'); os.replace(tmp,file)
        return p

def asset_file(pid,path):
    if not re.fullmatch(r'assets/[a-f0-9]{32}\.png',path): raise ValueError('无效素材路径。')
    f=folder(pid)/path
    if f.is_symlink() or f.resolve().parent!=(folder(pid)/'assets').resolve(): raise ValueError('禁止越界素材路径。')
    if not f.is_file(): raise FileNotFoundError('素材不存在。')
    return f

def open_image(data:bytes):
    if not 0<len(data)<=8*1024*1024: raise ValueError('图片必须小于 8 MB。')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('PNG','JPEG','WEBP') or max(im.size)>2048 or im.width*im.height>4*1024*1024: raise ValueError('只接受 PNG/JPEG/WebP，边长至多 2048。')
            result=ImageOps.exif_transpose(im).convert('RGBA'); result.load()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc: raise ValueError('图片损坏或格式不受支持。') from exc
    if result.getchannel('A').getbbox() is None: raise ValueError('图片完全透明。')
    return result

def put_image(pid,im):
    d=folder(pid)/'assets'; d.mkdir(parents=True,exist_ok=True)
    name=uid()+'.png'; im.save(d/name,'PNG'); return 'assets/'+name

def image(pid,path):
    with Image.open(asset_file(pid,path)) as im: return im.convert('RGBA')

def public(p):
    d=p.model_dump(); d['asset_prefix']=f'/api/projects/{p.id}/'
    return d
