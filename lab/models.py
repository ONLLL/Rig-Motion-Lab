"""Validated, versioned data contracts. Lengths use one fixed bind-height unit."""
from __future__ import annotations
import math
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

JOINTS = ('pelvis','chest','neck','head','l_shoulder','l_elbow','l_wrist',
          'r_shoulder','r_elbow','r_wrist','l_hip','l_knee','l_ankle','l_toe',
          'r_hip','r_knee','r_ankle','r_toe')
# Topological order is part of the retarget contract, NOT alphabetical order.
BONES = {
    'spine':('pelvis','chest'), 'neck':('chest','neck'), 'head':('neck','head'),
    'l_clavicle':('chest','l_shoulder'), 'l_upper_arm':('l_shoulder','l_elbow'),
    'l_forearm':('l_elbow','l_wrist'), 'r_clavicle':('chest','r_shoulder'),
    'r_upper_arm':('r_shoulder','r_elbow'), 'r_forearm':('r_elbow','r_wrist'),
    'l_pelvis':('pelvis','l_hip'), 'l_thigh':('l_hip','l_knee'),
    'l_shin':('l_knee','l_ankle'), 'l_foot':('l_ankle','l_toe'),
    'r_pelvis':('pelvis','r_hip'), 'r_thigh':('r_hip','r_knee'),
    'r_shin':('r_knee','r_ankle'), 'r_foot':('r_ankle','r_toe'),
}
CHAINS = {'l_arm':('l_shoulder','l_elbow','l_wrist'),
          'r_arm':('r_shoulder','r_elbow','r_wrist'),
          'l_leg':('l_hip','l_knee','l_ankle'),
          'r_leg':('r_hip','r_knee','r_ankle')}
LABELS = dict(zip(JOINTS, ('骨盆','胸部','颈部','头','左肩','左肘','左腕','右肩','右肘','右腕',
                         '左髋','左膝','左踝','左脚尖','右髋','右膝','右踝','右脚尖')))
Vec = tuple[float,float]

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Rig(Strict):
    joints: dict[str,Vec]
    bend: dict[str,int] = Field(default_factory=lambda:dict(l_arm=1,r_arm=-1,l_leg=1,r_leg=1))
    weapon_length: float = Field(default=.38,ge=.03,le=1.2)
    approved: bool = False
    @model_validator(mode='after')
    def validate_geometry(self):
        if set(self.joints) != set(JOINTS): raise ValueError('关节名称必须完整，不可增删标准关节。')
        for p in self.joints.values():
            if not all(math.isfinite(v) and -3 <= v <= 3 for v in p): raise ValueError('关节坐标必须是 -3 到 3 的有限数值。')
        for a,b in BONES.values():
            length=math.dist(self.joints[a],self.joints[b])
            if not .008<=length<=2: raise ValueError(f'{a} → {b} 骨长异常；请分开连接点。')
        if set(self.bend)!=set(CHAINS) or any(v not in (-1,1) for v in self.bend.values()):
            raise ValueError('弯曲方向必须为 -1 或 1。')
        return self

class Part(Strict):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,48}$')
    name: str = Field(min_length=1,max_length=60)
    bone: str
    image: str = Field(pattern=r'^assets/[a-f0-9]{32}\.png$')
    anchor_a: Vec = (.12,.5)
    anchor_b: Vec = (.88,.5)
    scale: float = Field(default=1,ge=.1,le=4)
    rotation: float = Field(default=0,ge=-360,le=360)
    offset: Vec = (0,0)
    z: int = Field(default=0,ge=-100,le=100)
    visible: bool = True
    @model_validator(mode='after')
    def validate_part(self):
        if self.bone not in (*BONES,'weapon'): raise ValueError('未知绑定骨骼。')
        for p in (self.anchor_a,self.anchor_b):
            if any(not 0<=v<=1 for v in p): raise ValueError('素材锚点需在图片范围内。')
        if math.dist(self.anchor_a,self.anchor_b)<.015: raise ValueError('两个素材锚点不能重合。')
        if any(abs(v)>.8 for v in self.offset): raise ValueError('局部偏移超过范围。')
        return self

class Camera(Strict):
    pixels_per_unit: float = Field(default=390,ge=80,le=700)
    root_x: float = Field(default=.45,ge=.1,le=.9)
    ground_y: float = Field(default=.86,ge=.3,le=.97)

class Key(Strict):
    phase: float = Field(ge=0,le=1)
    target: str = Field(max_length=64)
    interpolation: Literal['smooth','linear','step'] = 'smooth'
    dx: float = Field(default=0,ge=-.6,le=.6)
    dy: float = Field(default=0,ge=-.6,le=.6)
    angle: float = Field(default=0,ge=-180,le=180)

    @model_validator(mode='after')
    def track_target(self):
        if self.target not in ('l_wrist','r_wrist','l_ankle','r_ankle','pelvis','weapon') and self.target not in tuple('bone:'+b for b in BONES):
            raise ValueError('未知动作轨道；使用手脚目标、骨盆、武器或标准骨骼角度。')
        if self.target.startswith('bone:') or self.target == 'weapon':
            if self.dx or self.dy: raise ValueError('角度轨道不接受 X/Y 偏移。')
        elif self.angle:
            raise ValueError('位置轨道不接受角度；请使用骨骼角度轨道。')
        return self

class LayerKey(Strict):
    phase: float = Field(ge=0,le=1)
    part_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,48}$')
    z: int = Field(ge=-100,le=100)
    visible: bool

class Motion(Strict):
    kind: Literal['idle','walk','attack','jump','reference'] = 'walk'
    duration: float = Field(default=1.0,ge=.3,le=10)
    frames: int = Field(default=24,ge=4,le=64)
    stride: float = Field(default=.17,ge=.02,le=.45)
    lift: float = Field(default=.06,ge=0,le=.25)
    stance: float = Field(default=.6,ge=.51,le=.8)
    amplitude: float = Field(default=1,ge=.2,le=1.5)
    anticipation: float = Field(default=.3,ge=.15,le=.4)
    hit_phase: float = Field(default=.5,ge=.2,le=.9)
    jump_height: float = Field(default=.18,ge=.02,le=.5)
    root_mode: Literal['in_place','world'] = 'in_place'
    keys: list[Key] = Field(default_factory=list,max_length=128)
    layer_keys: list[LayerKey] = Field(default_factory=list,max_length=256)
    reference_gain: float = Field(default=1,ge=.1,le=1.5)
    reference_bind: int = Field(default=0,ge=0,le=239)
    smoothing: Literal[1,3,5] = 3
    lock_contacts: bool = True
    @model_validator(mode='after')
    def key_times(self):
        ids=[(k.phase,k.target) for k in self.keys]
        if len(set(ids))!=len(ids): raise ValueError('同一轨道同一时间只能保留一个校正点。')
        layer_ids=[(k.phase,k.part_id) for k in self.layer_keys]
        if len(set(layer_ids))!=len(layer_ids): raise ValueError('同一部件同一时间只能保留一个层级关键帧。')
        if self.hit_phase <= self.anticipation + .03:
            raise ValueError('命中时间必须晚于蓄力结束至少 3%。')
        return self

class ReferenceFrame(Strict):
    time: float = Field(ge=0,le=30)
    joints: dict[str,Vec]
    contacts: dict[str,bool] = Field(default_factory=dict)
    @model_validator(mode='after')
    def check(self):
        if set(self.joints)!=set(JOINTS): raise ValueError('参考帧缺少标准关节。')
        if any(not math.isfinite(v) or abs(v)>8 for p in self.joints.values() for v in p): raise ValueError('参考坐标超限。')
        if any(k not in ('l','r') for k in self.contacts): raise ValueError('未知接触侧。')
        return self

class Reference(Strict):
    format: Literal['rig-motion-reference.v1'] = 'rig-motion-reference.v1'
    space: Literal['x-right,y-up,fixed-height'] = 'x-right,y-up,fixed-height'
    name: str = Field(default='参考动作',max_length=100)
    provenance: str = Field(default='user',max_length=500)
    frames: list[ReferenceFrame] = Field(min_length=4,max_length=240)
    @model_validator(mode='after')
    def check_times(self):
        t=[f.time for f in self.frames]
        if any(b<=a for a,b in zip(t,t[1:])) or t[-1]-t[0]<.1: raise ValueError('参考帧时间必须严格递增且时长至少 0.1 秒。')
        for f in self.frames:
            for a,b in BONES.values():
                if math.dist(f.joints[a],f.joints[b])<1e-5: raise ValueError('参考骨骼端点重合；请检查识别结果。')
        return self

class Project(Strict):
    format: Literal['rig-motion-lab.v1'] = 'rig-motion-lab.v1'
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    name: str = Field(default='新角色实验',min_length=1,max_length=80)
    revision: int = Field(default=0,ge=0)
    rig: Rig
    parts: list[Part] = Field(default_factory=list,max_length=32)
    reference_image: str|None = Field(default=None,pattern=r'^assets/[a-f0-9]{32}\.png$')
    reference_placement: tuple[float,float,float,float]|None = None
    camera: Camera = Field(default_factory=Camera)
    motion: Motion = Field(default_factory=Motion)
    motion_library: dict[str,Motion] = Field(default_factory=dict,max_length=5)
    reference_motion: Reference|None = None
    note: str = Field(default='',max_length=500)
    @model_validator(mode='after')
    def ids(self):
        if len({p.id for p in self.parts})!=len(self.parts): raise ValueError('部件 ID 重复。')
        for kind,motion in self.motion_library.items():
            if kind != motion.kind: raise ValueError('动作库键与动作类型不一致。')
        # The active motion is authoritative. Older v1 projects migrate with defaults.
        self.motion_library[self.motion.kind] = self.motion.model_copy(deep=True)
        part_ids={p.id for p in self.parts}
        for motion in self.motion_library.values():
            if any(k.part_id not in part_ids for k in motion.layer_keys):
                raise ValueError('层级关键帧引用了不存在的部件；删除部件时须同步清理轨道。')
        if self.reference_placement and (any(abs(v)>5 for v in self.reference_placement) or min(self.reference_placement[2:])<=0):
            raise ValueError('参考图片位置异常。')
        return self

class SaveRequest(Strict):
    expected_revision: int = Field(ge=0)
    project: Project

class BakeRequest(Strict):
    expected_revision: int = Field(ge=0)
    size: Literal[64,128,256,512] = 256
    allow_clipping: bool = False

class CropRequest(Strict):
    expected_revision: int
    bone: str
    polygon: list[Vec] = Field(min_length=3,max_length=80)
    name: str = Field(default='拆分部件',min_length=1,max_length=60)
    @model_validator(mode='after')
    def valid(self):
        if self.bone not in (*BONES,'weapon'): raise ValueError('未知骨骼。')
        if any(not 0<=v<=1 for p in self.polygon for v in p): raise ValueError('选区超出原图。')
        return self
