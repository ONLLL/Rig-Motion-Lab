"""Numerical control trajectories -> fixed-length poses. No image-model calls.

Planar, kinematic experiment. Not an anatomical/full-body dynamics solver.
Unreachable contacts are reported; they are never presented as successful locks.
"""
from __future__ import annotations
import math
import numpy as np
from .models import Rig, Motion, Project, BONES, CHAINS, JOINTS
from .topology import single, project_single, active_bones
from .math2d import two_bone_ik, walking_foot, hermite


def vadd(a,b): return (a[0]+b[0],a[1]+b[1])
def vsub(a,b): return (a[0]-b[0],a[1]-b[1])
def rotate(v,a): return (math.cos(a)*v[0]-math.sin(a)*v[1],math.sin(a)*v[0]+math.cos(a)*v[1])
def mix(a,b,u): return a+(b-a)*u
def angle(a,b): return math.atan2(b[1]-a[1],b[0]-a[0])

def key_offset(m:Motion,target:str,u:float):
    keys=sorted((k for k in m.keys if k.target==target),key=lambda k:k.phase)
    if not keys: return (0.,0.,0.)
    values=[(k.phase,(k.dx,k.dy,math.radians(k.angle)),k.interpolation) for k in keys]
    if values[0][0]>0: values.insert(0,(0.,(0.,0.,0.),'smooth'))
    if values[-1][0]<1: values.append((1.,(0.,0.,0.),'smooth'))
    if u<=values[0][0]: return values[0][1]
    for (a,va,easing),(b,vb,_) in zip(values,values[1:]):
        if u<=b:
            # Small correction tracks have zero endpoint velocities by design;
            # base attack tracks do NOT stop at every authored key.
            f=(u-a)/(b-a)
            if easing=='step': f=1. if u==b else 0.
            elif easing=='smooth': f=f*f*(3-2*f)
            return tuple(mix(x,y,f) for x,y in zip(va,vb))
    return values[-1][1]


def curve(u,keys):
    """C1 cubic curve with finite-difference tangents (doesn't stop at impact)."""
    u=max(0,min(1,u)); n=len(keys)
    if u>=keys[-1][0]: return keys[-1][1]
    def tangent(i):
        if i in (0,n-1): return 0.
        return (keys[i+1][1]-keys[i-1][1])/(keys[i+1][0]-keys[i-1][0])
    for i in range(n-1):
        a,va=keys[i]; b,vb=keys[i+1]
        if a<=u<=b: return hermite((u-a)/(b-a),va,vb,tangent(i),tangent(i+1),b-a)
    return keys[0][1]


def _upper(rig:Rig,root,tilt):
    bind=rig.joints; points={'pelvis':root}
    # Torso is rigid in this MVP; both hips retain their bind offsets to pelvis.
    for name in ('chest','neck','head','l_shoulder','r_shoulder'):
        points[name]=vadd(root,rotate(vsub(bind[name],bind['pelvis']),tilt))
    for side in ('l','r'):
        points[side+'_hip']=vadd(root,vsub(bind[side+'_hip'],bind['pelvis']))
    return points


def _solve_chain(rig:Rig,points,chain,target,errors):
    if single(rig,chain):
        errors[chain]=project_single(rig,points,chain,target)
        return
    a,b,c=CHAINS[chain]
    upper=math.dist(rig.joints[a],rig.joints[b]); lower=math.dist(rig.joints[b],rig.joints[c])
    result=two_bone_ik(points[a],target,upper,lower,rig.bend[chain],fallback_direction=vsub(rig.joints[c],rig.joints[a]))
    points[b],points[c]=result.joint,result.end
    errors[chain]=result.residual


def template_frame(rig:Rig,m:Motion,u:float):
    bind=rig.joints; t=u*m.duration; root=bind['pelvis']; root_x=0.
    tilt=0.; dy=0.; feet={}; contacts={}; contact_ids={}
    hit=m.hit_phase; follow=hit+(1-hit)*.4
    if m.kind=='walk':
        speed=m.stride/(m.stance*m.duration); root_x=speed*t
        dy=-.022+.005*math.cos(4*math.pi*u)
        tilt=-.025*m.amplitude
        for side,offset in [('l',0.),('r',.5)]:
            ft=walking_foot(t,period=m.duration,stance_fraction=m.stance,
                stance_travel=m.stride,lift=m.lift,ankle_height=bind[side+'_ankle'][1],phase_offset=offset)
            feet[side]=vadd((bind[side+'_ankle'][0],0),ft.world_ankle)
            contacts[side]=ft.contact; contact_ids[side]=ft.contact_id
    elif m.kind=='idle':
        dy=.003*math.sin(2*math.pi*u); tilt=.018*math.sin(2*math.pi*u)*m.amplitude
    elif m.kind=='attack':
        tilt=math.radians(curve(u,[(0,0),(m.anticipation,14),(hit,-18),(follow,-12),(1,0)]))*m.amplitude
        dy=-.013*math.sin(math.pi*u)**2
    elif m.kind=='jump':
        if u<.2: dy=-.045*math.sin(math.pi*u/.4)
        elif u<=.8: dy=m.jump_height*4*((u-.2)/.6)*(1-(u-.2)/.6)
        else: dy=-.035*math.sin(math.pi*(u-.8)/.2)
        tilt=-.045*math.sin(math.pi*u)
    dxk,dyk,_=key_offset(m,'pelvis',u)
    root=(root[0]+root_x+dxk,root[1]+dy+dyk)
    points=_upper(rig,root,tilt)
    targets={}; errors={}; weapon_angle=math.radians(65)
    for side in ('l','r'):
        if side not in feet:
            airborne=m.kind=='jump' and .2<u<.8
            feet[side]=vadd(bind[side+'_ankle'],(root_x,dy if airborne else 0))
            contacts[side]=not airborne; contact_ids[side]=0 if not airborne else None
        off=key_offset(m,side+'_ankle',u)
        feet[side]=vadd(feet[side],off[:2]); targets[side+'_ankle']=feet[side]
        _solve_chain(rig,points,side+'_leg',feet[side],errors)
        # Flat-foot template; ankle->toe remains a rigid vector, no ground bbox reset.
        points[side+'_toe']=vadd(points[side+'_ankle'],vsub(bind[side+'_toe'],bind[side+'_ankle']))
        vec=vsub(bind[side+'_wrist'],bind[side+'_shoulder'])
        swing=(.5 if side=='l' else -.5)*math.sin(2*math.pi*u)*m.amplitude if m.kind=='walk' else 0
        target=vadd(points[side+'_shoulder'],rotate(vec,tilt+swing))
        if m.kind=='attack' and side=='r':
            reach=(math.dist(bind['r_shoulder'],bind['r_elbow'])+math.dist(bind['r_elbow'],bind['r_wrist']))*.92
            x=curve(u,[(0,.45),(m.anticipation,-.54),(hit,.95),(follow,.70),(1,.45)])
            y=curve(u,[(0,-.65),(m.anticipation,.58),(hit,-.10),(follow,-.56),(1,-.65)])
            # Amplitude modifies deviation, not body/limb lengths.
            x=.45+(x-.45)*m.amplitude; y=-.65+(y+.65)*m.amplitude
            target=vadd(points['r_shoulder'],(x*reach,y*reach))
            weapon_angle=math.radians(curve(u,[(0,65),(m.anticipation,150),(hit,-30),(follow,-68),(1,65)]))
        if m.kind=='jump': target=vadd(target,(0,.07*math.sin(math.pi*u)))
        off=key_offset(m,side+'_wrist',u); target=vadd(target,off[:2]); targets[side+'_wrist']=target
        _solve_chain(rig,points,side+'_arm',target,errors)
    weapon_angle+=key_offset(m,'weapon',u)[2]
    if m.kind=='walk': weapon_angle+=.12*math.sin(2*math.pi*u)
    return finish_frame(rig,m,u,points,targets,errors,contacts,contact_ids,root_x,weapon_angle)


def finish_frame(rig,m,u,points,targets,errors,contacts,contact_ids,root_x,weapon_angle):
    from .editing import apply_fk_offsets
    # Explicit FK corrections have priority after IK. Report broken contacts rather
    # than silently undoing the user's authored pose or claiming a successful lock.
    forearm_before=angle(points['r_elbow'],points['r_wrist'])
    apply_fk_offsets(points, m, u, key_offset, rig)
    forearm_after=angle(points['r_elbow'],points['r_wrist'])
    weapon_angle+=math.atan2(math.sin(forearm_after-forearm_before),math.cos(forearm_after-forearm_before))
    for chain,(_,_,end) in CHAINS.items():
        if end in targets: errors[chain]=math.dist(points[end],targets[end])
    points['weapon_tip']=vadd(points['r_wrist'],rotate((rig.weapon_length,0),weapon_angle))
    world_points={k:list(v) for k,v in points.items()}
    if m.root_mode=='in_place':
        points={k:(v[0]-root_x,v[1]) for k,v in points.items()}
        targets={k:(v[0]-root_x,v[1]) for k,v in targets.items()}
    bone_error=max(abs(math.dist(points[a],points[b])-math.dist(rig.joints[a],rig.joints[b])) for a,b in active_bones(rig).values())
    return {'phase':u,'time':u*m.duration,'joints':{k:list(v) for k,v in points.items()},
        'world_joints':world_points,'targets':{k:list(v) for k,v in targets.items()},
        'reach_errors':errors,'bone_error':bone_error,'contacts':contacts,'contact_ids':contact_ids,
        'root_motion':[root_x,points['pelvis'][1]-rig.joints['pelvis'][1]],'weapon_angle':weapon_angle}


def solve_project(p:Project):
    m=p.motion
    loop=m.kind in ('idle','walk')
    phases=[i/m.frames if loop else i/(m.frames-1) for i in range(m.frames)]
    if m.driver=='keyframes':
        from .poseclip import pose_frame
        frames=[pose_frame(p.rig,m,u) for u in phases]
        source_notes=['已使用独立姿势关键帧，不再执行参数模板；FK 插值不自动锁脚，请检查接触误差。']
    elif m.kind=='reference':
        if p.reference_motion is None: raise ValueError('请先导入参考动作 JSON 或提取视频关键点。')
        from .reference import retarget
        frames,source_notes=retarget(p,phases)
    else:
        frames=[template_frame(p.rig,m,u) for u in phases]; source_notes=[]
    # End holds are explicit: loops omit duplicate closure frame.
    durations=[1000*m.duration/(m.frames if loop else m.frames-1)]*m.frames
    if not loop: durations[-1]=120.
    # Quantize cumulative time so rounding doesn't drift over the whole clip.
    cumul=0.; prev=0
    for f,d in zip(frames,durations):
        cumul+=d; end=round(cumul); f['duration_ms']=end-prev; prev=end
    max_reach=max(max(f['reach_errors'].values(),default=0) for f in frames)
    contact_errors=[f['reach_errors'].get(s+'_leg',0) for f in frames for s in ('l','r') if f['contacts'].get(s)]
    contact_slip=0.; prev_contacts={}
    for f in frames:
        for side in ('l','r'):
            cid=f['contact_ids'].get(side)
            if cid is None: prev_contacts.pop(side,None); continue
            pt=f['world_joints'][side+'_ankle']
            old=prev_contacts.get(side)
            if old and old[0]==cid: contact_slip=max(contact_slip,math.dist(old[1],pt))
            prev_contacts[side]=(cid,pt)
    notes=list(source_notes)
    if any(v=='single' for v in p.rig.limb_modes.values()):
        notes.append('单段肢体整段刚性旋转；目标投影到固定长度圆周，不会自动弯肘/膝或拉长。旧中间关节、轨道及绑定保留，切回双段可恢复；旧下段角度轨道在单段模式不生效。')
    if not p.rig.approved: notes.append('骨架为待确认标注；当前仍可实验预览，导出前请确认关节。')
    if max_reach>.002: notes.append('部分手脚目标未满足（不可达或被 FK 改写），已保持骨长并报告误差；请调整轨道、幅度或骨盆。')
    if not p.parts: notes.append('尚未绑定角色部件；当前仅可查看骨架，不能导出角色素材。')
    if any(k.target.startswith('bone:') for k in m.keys):
        notes.append('已应用手工 FK 角度轨道；它优先于 IK，可能解除手脚接触，请检查误差与姿态。')
    return {'format':'rig-motion-clip.v1','project_revision':p.revision,'rig':p.rig.model_dump(),
        'motion':m.model_dump(),'loop':loop,'duration_ms':sum(f['duration_ms'] for f in frames),
        'frames':frames,'events':[{'phase':m.hit_phase,'name':'hit','frame':min(range(len(frames)),key=lambda i:abs(frames[i]['phase']-m.hit_phase))}] if m.kind=='attack' else [],
        'diagnostics':{'max_bone_error':max(f['bone_error'] for f in frames),
            'max_reach_error':max_reach,'max_contact_error':max(contact_errors,default=0),
            'max_stance_step_slip':contact_slip,'warnings':notes,
            'scope':'二维运动约束指标，不是美术质量、物理真实性或碰撞验证。'}}
