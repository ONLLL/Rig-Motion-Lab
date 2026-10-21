"""Local synthetic cutout validation, not an artistic animation acceptance test.

Run from repository root: .venv/bin/python tools/cartoon_rig_validation.py
Produces PNG/GIF/JSON evidence only; temporary project assets stay outside repo.
"""
from pathlib import Path
import json
import math
import os
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from lab import storage
from lab.demo import default_rig
from lab.models import CHAINS, Motion, Part, Project
from lab.motion import solve_project
from lab.poseclip import convert_to_keyframes
from lab.renderer import render_frame
from lab.topology import active_bones


def body_art(kind,color):
    if kind=='limb':
        im=Image.new('RGBA',(240,90));d=ImageDraw.Draw(im)
        d.rounded_rectangle((12,20,220,70),22,fill=color,outline='#20324a',width=4)
        d.ellipse((182,10,237,80),fill=color,outline='#20324a',width=4)
        d.line((45,33,165,33),fill='#fff0b0',width=5)
        d.ellipse((23,36,37,50),fill='#20324a')
        return im,(.125,.48),(.875,.48)
    if kind=='body':
        im=Image.new('RGBA',(160,200));d=ImageDraw.Draw(im)
        d.rounded_rectangle((15,10,145,195),40,fill=color,outline='#20324a',width=5)
        d.polygon([(40,65),(80,45),(120,65),(110,120),(50,120)],fill='#fff0b0')
        return im,(.5,.87),(.5,.14)
    im=Image.new('RGBA',(180,180));d=ImageDraw.Draw(im)
    d.ellipse((10,8,170,168),fill=color,outline='#20324a',width=5)
    for x in (60,120): d.ellipse((x-8,67,x+8,89),fill='#20324a')
    d.arc((53,82,128,137),0,180,fill='#20324a',width=5)
    return im,(.5,.86),(.5,.20)


def make_character():
    rig=default_rig();rig.limb_modes=dict.fromkeys(CHAINS,'single')
    project=Project(id=storage.uid(),name='Synthetic single-segment cartoon',rig=rig,motion=Motion(kind='walk',frames=16))
    for z,(bone,kind,color) in enumerate([
        ('l_leg','limb','#4bb2bd'),('l_arm','limb','#e5982d'),
        ('spine','body','#de6e55'),('neck','limb','#efbe49'),('r_leg','limb','#66cbd3'),
        ('head','head','#efbe49'),('r_arm','limb','#ffd05c')]):
        im,a,b=body_art(kind,color)
        project.parts.append(Part(id='cartoon_'+bone,name=bone,bone=bone,image=storage.put_image(project.id,im),anchor_a=a,anchor_b=b,z=z))
    return project


def main():
    root=Path(__file__).resolve().parents[1];out=root/'docs';out.mkdir(exist_ok=True)
    report={'fixture':'Original Pillow-drawn cartoon cutouts; no AI, no real-character artistic acceptance.',
            'scope':'Fixed limb radius and rigid PNG transform; real character weights, cleanup, style and joint art are not validated.',
            'motions':{}}
    with tempfile.TemporaryDirectory(prefix='rig-cartoon-validation-') as temp:
        os.environ['RIG_LAB_DATA_DIR']=temp
        p=make_character()
        contact=Image.new('RGB',(6*256,3*282),'#edf1f5');draw=ImageDraw.Draw(contact)
        animation=[]
        for row,kind in enumerate(('idle','walk','attack')):
            p.motion=Motion(kind=kind,frames=16)
            clip=solve_project(p)
            images=[render_frame(p,f,256)[0] for f in clip['frames']]
            for col,index in enumerate((0,3,6,9,12,15)):
                contact.paste(images[index],(col*256,row*282+26),images[index])
                draw.text((col*256+10,row*282+8),f'{kind} frame {index:02d}',fill='#20324a')
            if kind=='walk': animation=images
            report['motions'][kind]={'max_bone_error':clip['diagnostics']['max_bone_error'],
                'max_reach_error':clip['diagnostics']['max_reach_error'],
                'max_contact_error':clip['diagnostics']['max_contact_error'],
                'warnings':clip['diagnostics']['warnings']}
            for frame in clip['frames']:
                for chain,(a,_,c) in CHAINS.items():
                    assert abs(math.dist(frame['joints'][a],frame['joints'][c])-math.dist(p.rig.joints[a],p.rig.joints[c]))<1e-10
            p.motion=convert_to_keyframes(p)
            baked=solve_project(p)
            report['motions'][kind]['baked_max_bone_error']=baked['diagnostics']['max_bone_error']
        contact.save(out/'cartoon-rig-contact-sheet.png')
        # Shared paletted GIF is a viewing aid; authoritative alpha remains PNG.
        frames=[]
        for image in animation:
            canvas=Image.new('RGB',image.size,'#edf1f5');canvas.paste(image,mask=image.getchannel('A'));frames.append(canvas)
        frames[0].save(out/'cartoon-rig-walk.gif',save_all=True,append_images=frames[1:],duration=65,loop=0)
        report['active_bones']=active_bones(p.rig)
        report['artistic_review']='Contact sheet must be reviewed separately. Rigid legs cannot satisfy all walking contact targets; no perfect walk claim.'
        (out/'cartoon-rig-validation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__=='__main__': main()
