"""Explicit structure, FK and draw-order editing. No automatic rerigging or AI.

The semantic biped topology is fixed; editing bone lengths/angles changes the bind
pose and invalidates approval. FK animation offsets rotate descendants and keep
lengths, but intentionally take priority over IK contact targets.
"""
from __future__ import annotations
import math
from typing import Literal
from pydantic import Field, model_validator
from .models import BONES, JOINTS, Rig, Project, Motion, Strict


def descendants(joint: str, include_self: bool = True) -> list[str]:
    result = [joint] if include_self else []
    def visit(parent):
        for a,b in BONES.values():
            if a==parent:
                result.append(b)
                visit(b)
    visit(joint)
    return result


def rotate_about(point, origin, angle):
    x,y=point[0]-origin[0],point[1]-origin[1]
    c,s=math.cos(angle),math.sin(angle)
    return (origin[0]+c*x-s*y, origin[1]+s*x+c*y)


class RigEdit(Strict):
    expected_revision: int = Field(ge=0)
    kind: Literal['joint','bone']
    target: str = Field(max_length=64)
    cascade: bool = True
    x: float | None = Field(default=None,ge=-3,le=3)
    y: float | None = Field(default=None,ge=-3,le=3)
    length: float | None = Field(default=None,ge=.008,le=2)
    angle: float | None = Field(default=None,ge=-360,le=360)
    @model_validator(mode='after')
    def valid(self):
        if self.kind=='joint':
            if self.target not in JOINTS or self.x is None or self.y is None:
                raise ValueError('关节编辑需要有效关节及 X/Y。')
            if self.length is not None or self.angle is not None:
                raise ValueError('关节位置编辑不接受骨长/角度。')
        else:
            if self.target not in BONES or self.length is None or self.angle is None:
                raise ValueError('骨骼编辑需要有效骨骼、骨长及世界角度。')
            if self.x is not None or self.y is not None:
                raise ValueError('骨骼编辑不接受 X/Y。')
        return self


def edit_rig(rig: Rig, edit: RigEdit) -> Rig:
    data=rig.model_dump()
    points=data['joints']
    if edit.kind=='joint':
        old=points[edit.target];dx,dy=edit.x-old[0],edit.y-old[1]
        names=descendants(edit.target) if edit.cascade else [edit.target]
        for name in names: points[name]=(points[name][0]+dx,points[name][1]+dy)
    else:
        a,b=BONES[edit.target];origin=points[a];old_end=points[b]
        theta=math.radians(edit.angle)
        end=(origin[0]+edit.length*math.cos(theta),origin[1]+edit.length*math.sin(theta))
        delta=theta-math.atan2(old_end[1]-origin[1],old_end[0]-origin[0])
        names=descendants(b) if edit.cascade else [b]
        for name in names:
            q=rotate_about(points[name],old_end,delta)
            points[name]=(q[0]+end[0]-old_end[0],q[1]+end[1]-old_end[1])
    data['approved']=False
    return Rig.model_validate(data)


def apply_fk_offsets(points: dict, motion: Motion, phase: float, evaluate):
    for name,(a,b) in BONES.items():
        delta=evaluate(motion,'bone:'+name,phase)[2]
        if abs(delta)<1e-12: continue
        origin=points[a]
        for joint in descendants(b):
            points[joint]=rotate_about(points[joint],origin,delta)


def ordered_parts(project: Project, phase: float):
    """Step/hold overrides: before the first key use bind-layer properties.

    Order ties are resolved by original list index, identical in PNG and preview.
    A layer's key replaces BOTH z and visible; returning to base is an explicit key.
    """
    overrides={}
    for key in sorted(project.motion.layer_keys,key=lambda k:k.phase):
        if key.phase<=phase+1e-9: overrides[key.part_id]=key
    out=[]
    for i,part in enumerate(project.parts):
        key=overrides.get(part.id)
        if (key.visible if key else part.visible):
            out.append((key.z if key else part.z,i,part))
    return [part for _,_,part in sorted(out,key=lambda v:(v[0],v[1]))]
