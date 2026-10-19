import math
import numpy as np
import pytest
from pydantic import ValidationError
from lab.video import fill_short_gaps
from lab.reference import synthetic_reference
from lab.models import Reference


def test_short_occlusion_interpolates_without_filling_endpoints():
    s=np.arange(20,dtype=float).reshape(10,2);s[4:6]=np.nan
    filled=fill_short_gaps(s);assert filled[4].tolist()==pytest.approx([8,9])

@pytest.mark.parametrize('slice_',[slice(0,1),slice(9,10),slice(3,8)])
def test_long_or_endpoint_occlusions_require_review(slice_):
    s=np.arange(20,dtype=float).reshape(10,2);s[slice_]=np.nan
    with pytest.raises(ValueError):fill_short_gaps(s)


def test_motion_time_must_be_monotonic():
    r=synthetic_reference().model_dump();r['frames'][2]['time']=r['frames'][1]['time']
    with pytest.raises(ValidationError):Reference.model_validate(r)


def test_reference_missing_joint_and_nonfinite_values_rejected():
    r=synthetic_reference().model_dump();del r['frames'][0]['joints']['neck']
    with pytest.raises(ValidationError):Reference.model_validate(r)
    r=synthetic_reference().model_dump();r['frames'][0]['joints']['neck']=[float('nan'),1]
    with pytest.raises(ValidationError):Reference.model_validate(r)


def test_video_tasks_contract_rgb_timestamps_and_fixed_calibration(monkeypatch,tmp_path):
    """Protocol test with explicit stub detector; NOT real ML inference."""
    import sys,types
    from lab import video
    from lab.demo import default_rig
    class Capture:
        def __init__(self,*args):self.i=0
        def isOpened(self):return True
        def get(self,k):return {1:12,2:8,3:max(0,self.i-1)*1000/12}[k]
        def read(self):
            if self.i>=8:return False,None
            self.i+=1;return True,np.zeros((240,160,3),dtype=np.uint8)
        def release(self):pass
    cv=types.ModuleType('cv2');cv.VideoCapture=Capture;cv.CAP_PROP_FPS=1;cv.CAP_PROP_FRAME_COUNT=2;cv.CAP_PROP_POS_MSEC=3;cv.COLOR_BGR2RGB=4
    cv.cvtColor=lambda ar,code:ar[:,:,::-1].copy();cv.resize=lambda ar,size:ar
    mp=types.ModuleType('mediapipe');mp.Image=lambda **kw:kw;mp.ImageFormat=types.SimpleNamespace(SRGB='RGB')
    tasks=types.ModuleType('mediapipe.tasks');py=types.ModuleType('mediapipe.tasks.python');vis=types.ModuleType('mediapipe.tasks.python.vision')
    times=[];options=[];rig=default_rig()
    class Detector:
        @classmethod
        def create_from_options(cls,opts):options.append(opts);return cls()
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def detect_for_video(self,img,ts):
            times.append(ts);assert img['image_format']=='RGB'
            marks=[types.SimpleNamespace(x=.5,y=.5,visibility=1.,presence=1.) for _ in range(33)]
            for name,i in video.MAPPING.items():
                x,y=rig.joints[name];marks[i].x=(80+x*140)/160;marks[i].y=(220-y*170)/240
            marks[0].x=.5;marks[0].y=.19
            return types.SimpleNamespace(pose_landmarks=[marks])
    py.BaseOptions=lambda **kw:kw;vis.PoseLandmarkerOptions=lambda **kw:kw;vis.RunningMode=types.SimpleNamespace(VIDEO='VIDEO');vis.PoseLandmarker=Detector
    tasks.python=py;py.vision=vis;mp.tasks=tasks
    for name,mod in [('cv2',cv),('mediapipe',mp),('mediapipe.tasks',tasks),('mediapipe.tasks.python',py),('mediapipe.tasks.python.vision',vis)]:monkeypatch.setitem(sys.modules,name,mod)
    monkeypatch.setattr(video,'availability',lambda:{'mediapipe':True,'opencv':True,'model_present':True})
    ref,audit=video.extract_video(tmp_path/'fake-video.mp4')
    assert len(ref.frames)==8 and len(audit['confidence'])==8
    assert all(b>a for a,b in zip(times,times[1:]))
    assert options[0]['running_mode']=='VIDEO'
    assert audit['calibration']['height']>30
    assert 'not 3D mocap' in ref.provenance
    assert all(f.joints['pelvis'][0]==pytest.approx(0) for f in ref.frames)
