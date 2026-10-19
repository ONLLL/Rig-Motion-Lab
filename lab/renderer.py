"""A single deterministic cutout transform is shared by preview and PNG export."""
from __future__ import annotations
import io, math, json, zipfile
import numpy as np
from PIL import Image,ImageDraw
from .models import BONES,Project,Part
from .math2d import Affine
from . import storage
from .editing import ordered_parts
BASE_SIZE=768


def bone_endpoints(p:Project,part:Part,frame):
    a,b=('r_wrist','weapon_tip') if part.bone=='weapon' else BONES[part.bone]
    pts=frame['joints']; start,end=pts[a],pts[b]
    length=p.rig.weapon_length if part.bone=='weapon' else math.dist(p.rig.joints[a],p.rig.joints[b])
    return start,end,length


def part_matrix(p:Project,part:Part,frame,image_size,size=BASE_SIZE):
    start,end,bind_length=bone_endpoints(p,part,frame)
    w,h=image_size; a=(part.anchor_a[0]*w,part.anchor_a[1]*h); b=(part.anchor_b[0]*w,part.anchor_b[1]*h)
    source_angle=math.atan2(-(b[1]-a[1]),b[0]-a[0])
    unit_scale=bind_length*part.scale/math.dist(a,b)
    theta=math.atan2(end[1]-start[1],end[0]-start[0]); factor=size/BASE_SIZE; c=p.camera
    camera=Affine.translation(c.root_x*size,c.ground_y*size)@Affine.scale(c.pixels_per_unit*factor,-c.pixels_per_unit*factor)
    return (camera@Affine.translation(*start)@Affine.rotation(theta)@Affine.translation(*part.offset)
        @Affine.rotation(math.radians(part.rotation)-source_angle)@Affine.scale(unit_scale,-unit_scale)@Affine.translation(-a[0],-a[1]))


def assets(p):
    images={};pixels=0
    for part in p.parts:
        if part.image in images: continue
        if not part.visible and not any(k.part_id==part.id and k.visible for k in p.motion.layer_keys): continue
        image=storage.image(p.id,part.image);pixels+=image.width*image.height
        if pixels>32*1024*1024: raise ValueError('可见素材累计超过 32M 像素，请缩小原图或隐藏部分素材。')
        images[part.image]=image
    return images


def draw_commands(p,frame,images,size=BASE_SIZE):
    out=[]
    for part in ordered_parts(p,frame.get('phase',0)):
        im=images[part.image]; mat=part_matrix(p,part,frame,im.size,size)
        out.append({'id':part.id,'image':part.image,'matrix':[mat.a,mat.b,mat.c,mat.d,mat.tx,mat.ty],
                    'size':list(im.size),'bone':part.bone})
    return out


def render_frame(p,frame,size=256,images=None):
    images=assets(p) if images is None else images
    canvas=Image.new('RGBA',(size,size)); clipped=[]
    for part in ordered_parts(p,frame.get('phase',0)):
        im=images[part.image]; mat=part_matrix(p,part,frame,im.size,size); inv=mat.inverse()
        bbox=im.getchannel('A').getbbox()
        if bbox:
            x0,y0,x1,y1=bbox
            corners=[mat.apply(pt) for pt in ((x0,y0),(x1,y0),(x0,y1),(x1,y1))]
            if any(x<0 or y<0 or x>size or y>size for x,y in corners): clipped.append(part.id)
        # Nearest sampling preserves sharp cutouts; no per-frame bbox normalization.
        layer=im.transform((size,size),Image.Transform.AFFINE,(inv.a,inv.c,inv.tx,inv.b,inv.d,inv.ty),
                           resample=Image.Resampling.NEAREST)
        canvas.alpha_composite(layer)
    return canvas,clipped


def prepare_preview(p,clip):
    images=assets(p); clipped=set()
    for frame in clip['frames']:
        frame['draws']=draw_commands(p,frame,images)
        for cmd in frame['draws']:
            # Conservative alpha-bbox corner check, not collision detection.
            im=images[cmd['image']]; box=im.getchannel('A').getbbox()
            if box:
                a,b,c,d,e,f=cmd['matrix']; x0,y0,x1,y1=box
                pts=[(a*x+c*y+e,b*x+d*y+f) for x,y in ((x0,y0),(x1,y0),(x0,y1),(x1,y1))]
                if any(x<0 or y<0 or x>768 or y>768 for x,y in pts): clipped.add(cmd['id'])
    clip['diagnostics']['clipping_parts']=sorted(clipped)
    if clipped: clip['diagnostics']['warnings'].append('固定画布可能裁切 '+str(len(clipped))+' 个部件；请统一缩小相机比例或明确允许裁切。')
    return clip


def bake(p,clip,size=256,allow_clipping=False):
    if not p.rig.approved: raise ValueError('导出前请在关节页确认骨架。')
    if not any(ordered_parts(p,f.get('phase',0)) for f in clip['frames']): raise ValueError('没有绑定可见素材；不能用骨架冒充角色导出。')
    images=assets(p); frames=[]; clipped=set()
    for frame in clip['frames']:
        im,bad=render_frame(p,frame,size,images);frames.append(im);clipped.update(bad)
    if clipped and not allow_clipping: raise ValueError('导出可能裁切可见素材，请调小相机比例或明确勾选允许裁切。')
    durations=[f['duration_ms'] for f in clip['frames']]
    cols=min(8,len(frames));rows=math.ceil(len(frames)/cols)
    sheet=Image.new('RGBA',(cols*size,rows*size))
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        atlas=[]
        for i,im in enumerate(frames):
            b=io.BytesIO();im.save(b,'PNG');fn=f'frames/{i:03d}.png';z.writestr(fn,b.getvalue())
            x,y=(i%cols)*size,(i//cols)*size;sheet.paste(im,(x,y))
            atlas.append({'file':fn,'x':x,'y':y,'w':size,'h':size,'duration_ms':durations[i]})
        b=io.BytesIO();sheet.save(b,'PNG');z.writestr('spritesheet.png',b.getvalue())
        # All GIF frames map to a shared palette; reserved index 255 for transparent.
        pal=sheet.convert('RGB').quantize(colors=255,method=Image.Quantize.MEDIANCUT)
        gifs=[]
        for im in frames:
            q=im.convert('RGB').quantize(palette=pal,dither=Image.Dither.NONE)
            alpha=np.asarray(im.getchannel('A'));ar=np.array(q);ar[alpha<128]=255
            out=Image.fromarray(ar,'P');out.putpalette(pal.getpalette());out.info['transparency']=255;gifs.append(out)
        b=io.BytesIO(); kwargs={'loop':0} if clip['loop'] else {}
        gifs[0].save(b,'GIF',save_all=True,append_images=gifs[1:],duration=durations,disposal=2,transparency=255,**kwargs)
        z.writestr('preview.gif',b.getvalue())
        safe={k:v for k,v in clip.items() if k!='frames'}
        safe['frames']=[{k:v for k,v in f.items() if k not in ('draws',)} for f in clip['frames']]
        safe['export']={'size':size,'camera':p.camera.model_dump(),'allow_clipping':allow_clipping,
            'clipped_parts':sorted(clipped),'spriteforge_import':'Use numbered PNG sequence import; set FPS/timing separately.'}
        z.writestr('motion.json',json.dumps(safe,ensure_ascii=False,indent=2))
        z.writestr('atlas.json',json.dumps({'frames':atlas,'loop':clip['loop'],'pivot':[p.camera.root_x,p.camera.ground_y]},indent=2))
        z.writestr('README.txt','Rig Motion Lab 导出。固定 PNG 素材 + 数值动作；不是 AI 逐帧出图。\nPNG 帧尺寸固定。motion.json 为本工具格式，不是 Spine JSON。\nGIF 为索引色预览，不能代替含完整 Alpha 的 PNG。\n')
    return buf.getvalue()
