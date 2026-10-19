"""Optional local MediaPipe Tasks VIDEO importer. No cloud API, no automatic download.

Official contract: monotonically increasing ms, RGB mp.Image,
PoseLandmarkerOptions(... running_mode=VIDEO). See docs/SOURCES.md.
"""
from __future__ import annotations
import importlib.util, math, os
from pathlib import Path
import numpy as np
from .models import JOINTS,Reference,ReferenceFrame
from .storage import ROOT
MAPPING={'l_shoulder':11,'r_shoulder':12,'l_elbow':13,'r_elbow':14,'l_wrist':15,'r_wrist':16,
         'l_hip':23,'r_hip':24,'l_knee':25,'r_knee':26,'l_ankle':27,'r_ankle':28,'l_toe':31,'r_toe':32}


def model_path():
    p=Path(os.getenv('RIG_LAB_POSE_MODEL','models/pose_landmarker_lite.task')).expanduser()
    return p if p.is_absolute() else ROOT/p

def availability():
    return {'mediapipe':bool(importlib.util.find_spec('mediapipe')),'opencv':bool(importlib.util.find_spec('cv2')),
            'model_present':model_path().is_file(),'network_calls':False,
            'note':'人体检测需单独安装可选依赖和模型；未配置时不会以合成动作冒充视频识别。'}


def fill_short_gaps(series,max_gap=3):
    """Interpolate internal gaps only. Reject missing endpoints and long occlusions."""
    ar=np.asarray(series,dtype=float).copy()
    for col in range(ar.shape[1]):
        good=np.isfinite(ar[:,col]);idx=np.where(good)[0]
        if len(idx)<4 or not good[0] or not good[-1]: raise ValueError('起止帧或多数关节不可见，请裁剪视频到人物完整出现的一段。')
        gaps=np.diff(idx)-1
        if np.any(gaps>max_gap): raise ValueError('关节存在连续遮挡，超过 3 个采样帧；请换固定机位视频或人工修正参考 JSON。')
        ar[:,col]=np.interp(np.arange(len(ar)),idx,ar[idx,col])
    return ar


def extract_video(path:Path,progress=lambda _:None):
    caps=availability()
    if not all(caps[k] for k in ('mediapipe','opencv','model_present')):
        raise ValueError('视频识别未配置。安装 requirements-video.txt，并在 .env 设置 RIG_LAB_POSE_MODEL；可先导入示例轨迹测试后续流程。')
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    cap=cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened(): raise ValueError('视频无法解码。')
        fps=cap.get(cv2.CAP_PROP_FPS); n=cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not math.isfinite(fps) or not math.isfinite(n) or n<4 or not 1<=fps<=240 or n/fps>20 or n>4800: raise ValueError('视频须有有效帧率，时长不超过 20 秒。')
        stride=max(1,math.ceil(fps/12),math.ceil(n/240));rows=[];times=[];confidence=[]
        options=vision.PoseLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(model_path())),
                running_mode=vision.RunningMode.VIDEO,num_poses=1)
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            index=0;last_ts=-1
            while index<4800:
                ok,frame=cap.read()
                if not ok: break
                if index%stride==0:
                    h,w=frame.shape[:2]
                    if w*h>16*1024*1024: raise ValueError('视频帧过大。')
                    size=min(1.,960/max(w,h)); small=cv2.resize(frame,(round(w*size),round(h*size))) if size<1 else frame
                    timestamp=cap.get(cv2.CAP_PROP_POS_MSEC)
                    if not math.isfinite(timestamp) or timestamp<=last_ts: timestamp=index/fps*1000
                    ts=max(last_ts+1,round(timestamp)); last_ts=ts
                    result=landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=cv2.cvtColor(small,cv2.COLOR_BGR2RGB)),ts)
                    pts={};conf=[]
                    if result.pose_landmarks:
                        marks=result.pose_landmarks[0]
                        def get(i):
                            lm=marks[i];q=min(float(lm.visibility or 0),float(lm.presence or 0));conf.append(q)
                            return (lm.x*w,lm.y*h) if q>=.5 else (np.nan,np.nan)
                        for name,i in MAPPING.items(): pts[name]=get(i)
                        pts['pelvis']=tuple((np.array(pts['l_hip'])+pts['r_hip'])/2)
                        shoulder=(np.array(pts['l_shoulder'])+pts['r_shoulder'])/2
                        nose=np.array(get(0));pts['head']=tuple(nose)
                        pts['chest']=tuple(shoulder*.8+np.array(pts['pelvis'])*.2)
                        pts['neck']=tuple(shoulder*.8+nose*.2)
                    else: pts={k:(np.nan,np.nan) for k in JOINTS}
                    rows.append([v for k in JOINTS for v in pts[k]]);times.append(ts/1000);confidence.append(float(np.mean(conf)) if conf else 0)
                    progress(min(.95,index/max(n,1)))
                index+=1
        if len(rows)<4: raise ValueError('视频有效采样不足 4 帧。')
        raw=np.asarray(rows);clean=fill_short_gaps(raw);pts=clean.reshape(len(rows),len(JOINTS),2)
        head=pts[:,JOINTS.index('head')];feet=pts[:,[JOINTS.index('l_toe'),JOINTS.index('r_toe')]]
        ground=float(np.percentile(feet[:,:,1],95));height=float(np.median(feet[:,:,1].max(axis=1)-head[:,1]))
        if height<30: raise ValueError('人物太小或关键点识别失败。')
        origin=float(pts[0,JOINTS.index('pelvis'),0]);normalized=pts.copy()
        normalized[:,:,0]=(pts[:,:,0]-origin)/height;normalized[:,:,1]=(ground-pts[:,:,1])/height
        time=np.array(times)-times[0];frames=[];contact={}
        for side in ('l','r'):
            ankle=normalized[:,JOINTS.index(side+'_ankle')]
            velocity=np.linalg.norm(np.gradient(ankle,time,axis=0),axis=1)
            floor=float(np.percentile(ankle[:,1],15))
            contact[side]=(velocity<.10)&(ankle[:,1]<floor+.04)
        for i,t in enumerate(time):
            frames.append(ReferenceFrame(time=float(t),joints={k:tuple(normalized[i,j]) for j,k in enumerate(JOINTS)},
                contacts={s:bool(contact[s][i]) for s in ('l','r')}))
        ref=Reference(name='视频关键点 · 待校正',provenance='MediaPipe PoseLandmarker VIDEO; fixed image calibration, not 3D mocap',frames=frames)
        # Retain raw measurements, including missing values, separately for audits.
        audit={'format':'rig-motion-observations.v1','timestamps':times,'confidence':confidence,
               'joint_order':list(JOINTS),'observed_pixels':[[None if not math.isfinite(v) else v for v in row] for row in raw.tolist()],
               'calibration':{'ground_y':ground,'height':height,'origin_x':origin},
               'warning':'接触标记为速度/高度启发式。相机运动、遮挡、镜像和深度变化需人工处理；不包含武器识别。'}
        return ref,audit
    finally: cap.release()
