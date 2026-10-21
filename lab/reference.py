"""Planar local-angle retargeting. Human observation != solved motion.

A reference JSON uses fixed image-to-world calibration. First/source_bind frame
is an explicit calibration pose; pose deltas are transferred, not pixel lengths.
"""
from __future__ import annotations
import math
import numpy as np
from .models import Project,Reference,BONES,CHAINS
from .topology import active_bones, place_single
from .models import SINGLE_BONES
from .motion import angle,rotate,vadd,vsub,key_offset,_solve_chain,finish_frame


def _smooth(values,window):
    if window==1: return np.asarray(values)
    pad=window//2; return np.convolve(np.pad(values,(pad,pad),mode='edge'),np.ones(window)/window,mode='valid')


def retarget(p:Project,phases):
    source=p.reference_motion; m=p.motion;rig=p.rig
    if m.reference_bind>=len(source.frames): raise ValueError('参考校准帧超出范围。')
    src=source.frames;ts=np.array([f.time for f in src]);ts=(ts-ts[0])/(ts[-1]-ts[0])
    bones=active_bones(rig)
    incoming={b:name for name,(a,b) in bones.items()}
    src_angles={}; local={}; target_bind={}
    for name,(a,b) in bones.items():
        src_angles[name]=np.unwrap([angle(f.joints[a],f.joints[b]) for f in src])
        parent=incoming.get(a)
        local[name]=_smooth(src_angles[name]-(src_angles[parent] if parent else 0),m.smoothing)
        target_bind[name]=angle(rig.joints[a],rig.joints[b])-(angle(rig.joints[bones[parent][0]],rig.joints[bones[parent][1]]) if parent else 0)
    root=np.array([f.joints['pelvis'] for f in src]);root=np.column_stack([_smooth(root[:,i],m.smoothing) for i in (0,1)])
    # Input is already normalized to fixed rest-height units. Infer one body scale
    # from torso+leg geometry, not frame-by-frame bbox or changing image height.
    s0=src[m.reference_bind].joints
    target_h=math.dist(rig.joints['pelvis'],rig.joints['head'])+sum(math.dist(rig.joints[a],rig.joints[b]) for a,b in (('l_hip','l_knee'),('l_knee','l_ankle')))
    source_h=math.dist(s0['pelvis'],s0['head'])+sum(math.dist(s0[a],s0[b]) for a,b in (('l_hip','l_knee'),('l_knee','l_ankle')))
    scale=target_h/max(source_h,.02)
    frames=[];locks={}; spans={'l':0,'r':0};previous_contacts={'l':False,'r':False}
    notes=['参考轨迹按局部角度变化重定向。源校准帧对齐目标初始姿势；未做三维恢复、全身碰撞或自动镜像。']
    for u in phases:
        rt=np.array([np.interp(u,ts,root[:,i]) for i in (0,1)])-root[m.reference_bind]
        rx,ry=rt*scale*m.reference_gain
        k=key_offset(m,'pelvis',u); points={'pelvis':vadd(rig.joints['pelvis'],(rx+k[0],ry+k[1]))};angles={}
        for name,(a,b) in bones.items():
            parent=incoming.get(a)
            delta=float(np.interp(u,ts,local[name])-local[name][m.reference_bind])*m.reference_gain
            world=(angles[parent] if parent else 0)+target_bind[name]+delta
            angles[name]=world
            if name in SINGLE_BONES: place_single(rig,points,name,world)
            else: points[b]=vadd(points[a],rotate((math.dist(rig.joints[a],rig.joints[b]),0),world))
        j=min(len(src)-1,max(0,int(np.searchsorted(ts,u,side='right')-1)))
        contacts={s:bool(src[j].contacts.get(s,False)) and m.lock_contacts for s in ('l','r')}
        ids={};targets={};errors={}
        for side in ('l','r'):
            ankle=side+'_ankle';toe=side+'_toe';wrist=side+'_wrist'
            footvec=vsub(points[toe],points[ankle]); off=key_offset(m,ankle,u)
            if contacts[side]:
                if not previous_contacts[side]: locks[side]=points[ankle];spans[side]+=1
                target=vadd(locks[side],off[:2]);ids[side]=spans[side]
                targets[ankle]=target;_solve_chain(rig,points,side+'_leg',target,errors)
            else:
                ids[side]=None
                if abs(off[0])+abs(off[1])>0:
                    target=vadd(points[ankle],off[:2]);targets[ankle]=target;_solve_chain(rig,points,side+'_leg',target,errors)
            points[toe]=vadd(points[ankle],footvec)
            previous_contacts[side]=contacts[side]
            off=key_offset(m,wrist,u)
            if abs(off[0])+abs(off[1])>0:
                target=vadd(points[wrist],off[:2]);targets[wrist]=target;_solve_chain(rig,points,side+'_arm',target,errors)
        wa=math.radians(65)+(angle(points['r_elbow'],points['r_wrist'])-angle(rig.joints['r_elbow'],rig.joints['r_wrist']))*.6+key_offset(m,'weapon',u)[2]
        frames.append(finish_frame(rig,m,u,points,targets,errors,contacts,ids,float(rx),wa))
    if not any(f.contacts for f in src): notes.append('源动作没有接触标记，不会声称已完成脚底锁定。')
    return frames,notes


def synthetic_reference():
    """Round-trip fixture for UI evaluation. Clearly NOT motion capture."""
    from .demo import default_rig
    from .models import Motion,ReferenceFrame
    from .motion import template_frame
    rig=default_rig();m=Motion(kind='attack',frames=40,duration=1.3)
    frames=[]
    for i in range(40):
        u=i/39;f=template_frame(rig,m,u)
        # Different, fixed source body scale and origin. No variable frame fitting.
        j={k:(v[0]*1.15+.27,v[1]*1.15) for k,v in f['joints'].items() if k!='weapon_tip'}
        frames.append(ReferenceFrame(time=u*1.3,joints=j,contacts={'l':True,'r':True}))
    return Reference(name='合成斩击轨迹 · 非视频',provenance='programmatic test fixture; not human mocap',frames=frames)
