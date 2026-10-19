"""Original program-drawn cutout fixture. Not AI artwork or a mocap sample."""
from __future__ import annotations
import math
from PIL import Image, ImageDraw
from .models import Project,Rig,Part,Motion,BONES
from . import storage


def default_rig(short=False):
    j={'pelvis':(0,.51),'chest':(0,.74),'neck':(0,.87),'head':(.012,1.025),
       'l_shoulder':(-.095,.76),'l_elbow':(-.14,.605),'l_wrist':(-.10,.45),
       'r_shoulder':(.095,.76),'r_elbow':(.18,.62),'r_wrist':(.235,.48),
       'l_hip':(-.055,.49),'l_knee':(-.01,.277),'l_ankle':(-.06,.065),'l_toe':(.055,.065),
       'r_hip':(.055,.49),'r_knee':(.102,.277),'r_ankle':(.07,.065),'r_toe':(.185,.065)}
    if short:
        for k,(x,y) in list(j.items()):
            j[k]=(x,y*.73 if y<.51 else y-.1377)
    return Rig(joints=j,approved=True)


def part_art(kind,far=False):
    dark='#182b38'; steel='#96b5bc'; mid='#527580'; mint='#9ae0bd'; cream='#eff0d8'; gold='#dbc179'
    if kind=='head':
        im=Image.new('RGBA',(180,220)); d=ImageDraw.Draw(im)
        d.polygon([(40,176),(32,116),(40,51),(62,30),(117,25),(144,61),(150,130),(137,179),(113,198),(71,198)],fill=dark)
        d.polygon([(46,125),(47,57),(64,40),(114,38),(135,64),(138,126),(120,158),(64,158)],fill=cream)
        d.rounded_rectangle((48,90,85,112),7,fill=dark); d.rounded_rectangle((102,86,133,108),7,fill=dark)
        d.polygon([(91,114),(83,132),(99,132)],fill=mid)
        d.rectangle((65,143,118,177),fill=cream)
        for x in (76,90,104): d.line((x,149,x,176),fill=mid,width=3)
        d.polygon([(42,69),(30,49),(37,18),(70,22),(89,39)],fill=mid)
        d.polygon([(130,57),(137,27),(158,13),(161,56),(145,85)],fill=mid)
        d.polygon([(40,27),(64,30),(71,43),(44,48)],fill=steel)
        return im,(.5,.87),(.5,.34)
    if kind=='torso':
        im=Image.new('RGBA',(230,260));d=ImageDraw.Draw(im)
        d.polygon([(21,38),(73,14),(163,14),(213,44),(186,162),(196,238),(33,238),(46,156)],fill=dark)
        d.polygon([(44,45),(179,40),(164,157),(60,159)],fill=mid)
        d.polygon([(67,54),(99,47),(119,132),(95,153)],fill=mint)
        d.polygon([(134,43),(170,51),(156,147),(131,132)],fill=steel)
        d.rectangle((47,165,182,193),fill=gold);d.rectangle((100,161,127,198),fill=dark)
        d.polygon([(63,196),(111,199),(108,238),(48,238)],fill=mid)
        d.polygon([(126,199),(168,196),(183,238),(130,238)],fill=mid)
        return im,(.5,.88),(.5,.12)
    if kind=='weapon':
        im=Image.new('RGBA',(300,90));d=ImageDraw.Draw(im)
        d.polygon([(83,35),(243,26),(286,43),(246,61),(83,54)],fill=dark)
        d.polygon([(100,38),(243,32),(273,43),(101,44)],fill='#d3e5df')
        d.polygon([(101,45),(273,43),(243,55),(100,51)],fill=mid)
        d.rectangle((48,36,94,53),fill=gold)
        d.rectangle((33,39,64,49),fill=dark)
        d.rectangle((83,21,99,67),fill=mint)
        d.ellipse((25,36,40,52),fill=gold)
        return im,(.17,.5),(.90,.5)
    if kind=='foot':
        im=Image.new('RGBA',(200,94));d=ImageDraw.Draw(im)
        d.polygon([(14,15),(73,12),(99,41),(173,45),(191,69),(188,89),(12,89)],fill=dark)
        d.polygon([(23,23),(63,23),(88,52),(162,53),(179,69),(23,69)],fill=mid)
        d.line((18,77,185,77),fill=steel,width=6)
        return im,(.2,.39),(.80,.39)
    im=Image.new('RGBA',(230,88));d=ImageDraw.Draw(im)
    d.rounded_rectangle((6,17,223,74),22,fill=dark)
    d.rounded_rectangle((22,25,203,64),15,fill=mid if far else steel)
    d.polygon([(65,22),(155,22),(169,37),(146,59),(75,59),(56,43)],fill=mid)
    d.line((84,30,147,30),fill=mint if not far else gold,width=5)
    d.ellipse((10,26,43,63),fill=gold);d.ellipse((183,26,216,63),fill=dark)
    return im,(.12,.5),(.88,.5)


def new_project(name='守卫 · 动作实验',demo=True,short=False):
    rig=default_rig(short); rig.approved=bool(demo)
    p=Project(id=storage.uid(),name=name,rig=rig,
        note='内置角色为程序绘制的分层测试素材；不是 AI 生图或专业动作质量示例。' if demo else '先上传角色图，拖动关节确认，再拆件或绑定独立 PNG。')
    if demo:
        order=[('l_foot','foot'),('l_shin','limb'),('l_thigh','limb'),
            ('l_upper_arm','limb'),('l_forearm','limb'),('neck','limb'),('spine','torso'),
            ('r_thigh','limb'),('r_shin','limb'),('r_foot','foot'),
            ('head','head'),('r_upper_arm','limb'),('r_forearm','limb'),('weapon','weapon')]
        for i,(bone,kind) in enumerate(order):
            im,a,b=part_art(kind,bone.startswith('l_'))
            path=storage.put_image(p.id,im)
            p.parts.append(Part(id='demo_'+bone,name={'torso':'胸甲','head':'头部','weapon':'武器'}.get(kind,bone),
                bone=bone,image=path,anchor_a=a,anchor_b=b,z=i,scale=1.13 if kind=='limb' else 1))
        from .renderer import render_frame
        from .motion import vadd,rotate
        pts=dict(rig.joints);pts['weapon_tip']=vadd(pts['r_wrist'],rotate((rig.weapon_length,0),math.radians(65)))
        frame={'joints':pts}
        image,_=render_frame(p,frame,size=768)
        p.reference_image=storage.put_image(p.id,image)
        # Store full image in the same fixed world space as the rendering camera.
        cam=p.camera; s=cam.pixels_per_unit
        p.reference_placement=(-cam.root_x*768/s,cam.ground_y*768/s,768/s,768/s)
    return storage.save(p)
