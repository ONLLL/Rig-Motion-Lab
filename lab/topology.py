"""Reversible limb topology views over the legacy project data.

Archived intermediate points and tracks remain in the file, but are not joints
of a single-segment chain. Their rigid transforms only support old PNG bindings.
"""
import math
from .models import BONES, CHAINS, SINGLE_BONES

PRIMARY = {'l_arm':'l_upper_arm','r_arm':'r_upper_arm','l_leg':'l_thigh','r_leg':'r_thigh'}
SECONDARY = {'l_arm':'l_forearm','r_arm':'r_forearm','l_leg':'l_shin','r_leg':'r_shin'}


def single(rig, chain): return rig.limb_modes[chain] == 'single'


def active_bones(rig):
    out={}
    for name,pair in BONES.items():
        chain=next((c for c in CHAINS if single(rig,c) and name in (PRIMARY[c],SECONDARY[c])),None)
        if chain:
            if name==PRIMARY[chain]: out[chain]=SINGLE_BONES[chain]
        else: out[name]=pair
    return out


def active_joints(rig):
    hidden={CHAINS[c][1] for c in CHAINS if single(rig,c)}
    return [j for j in rig.joints if j not in hidden]


def place_single(rig, points, chain, theta):
    a,b,c=CHAINS[chain]; bind=rig.joints
    rest=math.atan2(bind[c][1]-bind[a][1],bind[c][0]-bind[a][0])
    delta=theta-rest; co,si=math.cos(delta),math.sin(delta)
    for name in (b,c):
        x,y=bind[name][0]-bind[a][0],bind[name][1]-bind[a][1]
        points[name]=(points[a][0]+co*x-si*y,points[a][1]+si*x+co*y)


def project_single(rig,points,chain,target):
    a,_,c=CHAINS[chain]; dx,dy=target[0]-points[a][0],target[1]-points[a][1]
    if math.hypot(dx,dy)<1e-12:
        dx,dy=rig.joints[c][0]-rig.joints[a][0],rig.joints[c][1]-rig.joints[a][1]
    place_single(rig,points,chain,math.atan2(dy,dx))
    return math.dist(points[c],target)
