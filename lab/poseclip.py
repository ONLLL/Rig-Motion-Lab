"""Editable template snapshots: fixed-length FK with independent pose keyframes.

Converting captures the current solved motion, including all legacy correction
tracks. Sampling this driver NEVER calls the original parametric generator.
Targets/contacts are diagnostic metadata, not claims of physical constraints.
"""
from __future__ import annotations
import math
import numpy as np
from .models import BONES, CHAINS, Rig, Motion, PoseKey, Project

PARENT_BONE = {bone: next((n for n, (_, end) in BONES.items() if end == a), None)
               for bone, (a, _) in BONES.items()}


def capture_pose(rig: Rig, frame: dict, *, root_mode: str) -> PoseKey:
    pts = frame['world_joints']
    world_angles = {n: math.atan2(pts[b][1]-pts[a][1],pts[b][0]-pts[a][0])
                    for n,(a,b) in BONES.items()}
    travel = frame['root_motion'][0]
    targets = {n: (q[0]+(travel if root_mode=='in_place' else 0),q[1])
               for n,q in frame['targets'].items()}
    root=(pts['pelvis'][0]-rig.joints['pelvis'][0]-travel,
          pts['pelvis'][1]-rig.joints['pelvis'][1])
    return PoseKey(phase=frame['phase'],root=root,travel_x=travel,
                   angles={n: math.degrees(a-(world_angles[PARENT_BONE[n]] if PARENT_BONE[n] else 0))
                           for n,a in world_angles.items()},
                   weapon=math.degrees(frame['weapon_angle']-world_angles['r_forearm']),
                   targets=targets,contacts=frame['contacts'],contact_ids=frame['contact_ids'])


def convert_to_keyframes(project: Project) -> Motion:
    from .motion import template_frame
    from .reference import retarget
    m = project.motion
    if m.driver != 'template': raise ValueError('只能转换尚未烘焙的参数模板。')
    loop = m.kind in ('idle','walk')
    phases = [i/m.frames if loop else i/(m.frames-1) for i in range(m.frames)]
    if loop: phases.append(1.)
    if m.kind=='reference':
        if project.reference_motion is None: raise ValueError('请先导入参考动作。')
        frames, _ = retarget(project, phases)
    else:
        frames = [template_frame(project.rig,m,u) for u in phases]
    keys = [capture_pose(project.rig,f,root_mode=m.root_mode) for f in frames]
    # Preserve the sampled poses while avoiding -180/180 discontinuities.
    for bone in BONES:
        degrees = np.degrees(np.unwrap(np.radians([k.angles[bone] for k in keys])))
        for k,a in zip(keys,degrees): k.angles[bone]=float(a)
    degrees = np.degrees(np.unwrap(np.radians([k.weapon for k in keys])))
    for k,a in zip(keys,degrees): k.weapon=float(a)
    data=m.model_dump()
    backup=dict(data);backup['source_motion']=None;backup['pose_keys']=[]
    data.update(driver='keyframes',pose_keys=[k.model_dump() for k in keys],
                source_motion=backup,keys=[])
    return Motion.model_validate(data)


def interpolate_pose(m: Motion, phase: float) -> PoseKey:
    keys=m.pose_keys
    if not keys: raise ValueError('当前动作没有姿势关键帧。')
    u=max(0.,min(1.,phase))
    if u<=keys[0].phase: return keys[0].model_copy(update={'phase':u},deep=True)
    if u>=keys[-1].phase: return keys[-1].model_copy(update={'phase':u},deep=True)
    for a,b in zip(keys,keys[1:]):
        if abs(u-b.phase)<1e-12: return b.model_copy(deep=True)
        if a.phase<=u<b.phase:
            t=(u-a.phase)/(b.phase-a.phase)
            if a.interpolation=='smooth': t=t*t*(3-2*t)
            elif a.interpolation=='step': t=0.
            lerp=lambda x,y: x+(y-x)*t
            targets={}
            for n in set(a.targets)|set(b.targets):
                p=a.targets.get(n,b.targets.get(n));q=b.targets.get(n,p)
                # During one contact interval use the target fixed at the segment
                # start. Do not smooth a world-space plant point into foot sliding.
                side=n[0]
                planted=n.endswith('_ankle') and a.contacts.get(side,False)
                targets[n]=p if planted else tuple(lerp(x,y) for x,y in zip(p,q))
            return PoseKey(phase=u,root=tuple(lerp(x,y) for x,y in zip(a.root,b.root)),
                travel_x=lerp(a.travel_x,b.travel_x),angles={n:lerp(a.angles[n],b.angles[n]) for n in BONES},
                weapon=lerp(a.weapon,b.weapon),interpolation=a.interpolation,targets=targets,
                contacts=dict(a.contacts),contact_ids=dict(a.contact_ids))
    raise ValueError('关键帧范围无效。')


def pose_frame(rig: Rig,m: Motion,phase: float) -> dict:
    k=interpolate_pose(m,phase)
    points={'pelvis':(rig.joints['pelvis'][0]+k.root[0]+k.travel_x,
                      rig.joints['pelvis'][1]+k.root[1])}
    angles={}
    for name,(a,b) in BONES.items():
        theta=math.radians(k.angles[name])+(angles[PARENT_BONE[name]] if PARENT_BONE[name] else 0)
        length=math.dist(rig.joints[a],rig.joints[b]);angles[name]=theta
        points[b]=(points[a][0]+length*math.cos(theta),points[a][1]+length*math.sin(theta))
    weapon_angle=angles['r_forearm']+math.radians(k.weapon)
    points['weapon_tip']=(points['r_wrist'][0]+rig.weapon_length*math.cos(weapon_angle),
                          points['r_wrist'][1]+rig.weapon_length*math.sin(weapon_angle))
    errors={chain:math.dist(points[end],k.targets[end]) for chain,(_,_,end) in CHAINS.items() if end in k.targets}
    world={n:list(p) for n,p in points.items()}
    travel=k.travel_x if m.root_mode=='in_place' else 0.
    return {'phase':phase,'time':phase*m.duration,'joints':{n:[q[0]-travel,q[1]] for n,q in points.items()},
            'world_joints':world,'targets':{n:[q[0]-travel,q[1]] for n,q in k.targets.items()},
            'reach_errors':errors,'contacts':dict(k.contacts),
            'contact_ids':{s:k.contact_ids.get(s) if k.contacts.get(s) else None for s in ('l','r')},
            'root_motion':[k.travel_x,k.root[1]],'weapon_angle':weapon_angle,
            'bone_error':max(abs(math.dist(points[a],points[b])-math.dist(rig.joints[a],rig.joints[b])) for a,b in BONES.values())}
