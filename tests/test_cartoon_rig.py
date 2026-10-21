"""Single-segment cartoon regression tests; no AI or artistic-quality claim."""
import io
import json
import math
import zipfile

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from lab import storage
from lab.demo import default_rig
from lab.editing import RigEdit, edit_rig
from lab.models import BONES, CHAINS, SINGLE_BONES, Rig, Motion, Key, Part, Project
from lab.motion import solve_project, template_frame, _solve_chain
from lab.poseclip import capture_pose, convert_to_keyframes, pose_frame
from lab.renderer import bake, render_frame, part_matrix
from lab.topology import active_bones, active_joints


def rig_modes(*single):
    r=default_rig()
    r.limb_modes.update({c:'single' for c in single})
    return r


def assert_rigid(rig, frame):
    pts=frame['joints']
    for chain,(a,b,c) in CHAINS.items():
        if rig.limb_modes[chain]=='single':
            for p,q in ((a,c),(a,b),(b,c)):
                assert math.dist(pts[p],pts[q])==pytest.approx(math.dist(rig.joints[p],rig.joints[q]),abs=1e-10)
    for a,b in active_bones(rig).values():
        assert math.dist(pts[a],pts[b])==pytest.approx(math.dist(rig.joints[a],rig.joints[b]),abs=1e-10)
    assert frame['bone_error']<1e-10


@pytest.mark.parametrize('kind',['idle','walk','attack','jump'])
@pytest.mark.parametrize('single',[(),('l_arm',),('r_arm','l_leg'),('l_arm','r_arm'),tuple(CHAINS)])
def test_all_templates_hold_physical_lengths(kind,single):
    r=rig_modes(*single)
    for u in (0,.15,.3,.5,.75,1):
        assert_rigid(r,template_frame(r,Motion(kind=kind),u))


def test_old_project_without_modes_is_exact_standard():
    old=default_rig().model_dump();old.pop('limb_modes')
    migrated=Rig.model_validate(old)
    assert migrated.limb_modes==dict.fromkeys(CHAINS,'two')
    for kind in ('idle','walk','attack','jump'):
        m=Motion(kind=kind)
        for u in (0,.25,.5,1):
            assert template_frame(migrated,m,u)==template_frame(default_rig(),m,u)
    assert active_bones(migrated)==BONES


@pytest.mark.parametrize('chain',list(CHAINS))
def test_single_has_no_intermediate_control_joint(chain):
    r=rig_modes(chain);a,b,c=CHAINS[chain]
    assert b not in active_joints(r)
    assert a in active_joints(r) and c in active_joints(r)
    assert active_bones(r)[chain]==(a,c)
    assert all(b not in pair for pair in active_bones(r).values())
    assert len(r.joints)==18  # archived compatibility data are not discarded


@pytest.mark.parametrize('chain',list(CHAINS))
@pytest.mark.parametrize('offset',[(0,0),(10,10),(.005,0)])
def test_single_target_projection_coincident_near_far(chain,offset):
    r=rig_modes(chain);a,b,c=CHAINS[chain];pts=dict(r.joints);errors={}
    target=(pts[a][0]+offset[0],pts[a][1]+offset[1])
    _solve_chain(r,pts,chain,target,errors)
    assert math.dist(pts[a],pts[c])==pytest.approx(math.dist(r.joints[a],r.joints[c]))
    assert errors[chain]==pytest.approx(math.dist(pts[c],target))
    assert errors[chain]>0
    assert all(math.isfinite(v) for pt in pts.values() for v in pt)


def test_invalid_single_length_or_mode_rejected():
    r=rig_modes('r_arm').model_dump();r['joints']['r_wrist']=r['joints']['r_shoulder']
    with pytest.raises(ValidationError): Rig.model_validate(r)
    r=default_rig().model_dump();r['limb_modes']['r_arm']='elastic'
    with pytest.raises(ValidationError): Rig.model_validate(r)


@pytest.mark.parametrize('chain',list(CHAINS))
def test_whole_limb_fk_preserves_rigid_triangle(chain):
    r=rig_modes(chain);m=Motion(kind='idle')
    original=template_frame(r,m,0)
    m.keys=[Key(phase=0,target='bone:'+chain,angle=35)]
    f=template_frame(r,m,0);a,b,c=CHAINS[chain]
    assert_rigid(r,f)
    assert f['joints'][a]==original['joints'][a]
    assert f['joints'][c]!=original['joints'][c]


@pytest.mark.parametrize('chain',list(CHAINS))
def test_single_pose_capture_and_baked_roundtrip(chain):
    r=rig_modes(chain);p=Project(id='a'*32,rig=r,motion=Motion(kind='walk',frames=8))
    before=[template_frame(r,p.motion,u) for u in (0,.25,.5,.75)]
    p.motion=convert_to_keyframes(p)
    assert all(chain in k.angles for k in p.motion.pose_keys)
    loaded=Project.model_validate_json(p.model_dump_json())
    for u,original in zip((0,.25,.5,.75),before):
        f=pose_frame(loaded.rig,loaded.motion,u)
        assert_rigid(r,f)
        for joint in original['joints']:
            assert f['joints'][joint]==pytest.approx(original['joints'][joint],abs=1e-8)


def test_switch_modes_preserves_existing_keys_bindings_and_restores_pose(project):
    project.motion=convert_to_keyframes(project)
    original=project.model_dump()
    before=solve_project(project)['frames']
    project.rig.limb_modes=dict.fromkeys(CHAINS,'single')
    for f in solve_project(project)['frames']: assert_rigid(project.rig,f)
    assert project.motion.model_dump()==original['motion']
    assert [p.model_dump() for p in project.parts]==original['parts']
    project.rig.limb_modes=dict.fromkeys(CHAINS,'two')
    assert solve_project(project)['frames']==before


def test_single_bind_editor_rotates_and_scales_whole_limb_without_new_joint():
    r=rig_modes('r_arm');old=r.model_dump()
    result=edit_rig(r,RigEdit(expected_revision=0,kind='bone',target='r_arm',length=.32,angle=-30))
    a,_,c=CHAINS['r_arm']
    assert math.dist(result.joints[a],result.joints[c])==pytest.approx(.32)
    assert math.atan2(result.joints[c][1]-result.joints[a][1],result.joints[c][0]-result.joints[a][0])==pytest.approx(math.radians(-30))
    assert r.model_dump()==old
    assert not result.approved


def test_png_whole_limb_anchor_preview_export_and_save_reload(project):
    project.rig.limb_modes['r_arm']='single'
    im=Image.new('RGBA',(180,60));d=ImageDraw.Draw(im)
    d.rounded_rectangle((8,9,172,51),18,fill='#ef962c');d.ellipse((18,23,32,37),fill='black')
    part=Part(id='whole_arm',name='整段手臂',bone='r_arm',image=storage.put_image(project.id,im),anchor_a=(.14,.5),anchor_b=(.86,.5))
    project.parts=[part];project.motion=Motion(kind='walk',frames=8)
    saved=storage.save(project,project.revision);loaded=storage.load(saved.id)
    assert loaded.rig.limb_modes['r_arm']=='single'
    clip=solve_project(loaded)
    for f in clip['frames']:
        mat=part_matrix(loaded,part,f,im.size)
        root=f['joints']['r_shoulder'];c=loaded.camera
        assert mat.apply((part.anchor_a[0]*im.width,part.anchor_a[1]*im.height))==pytest.approx((c.root_x*768+root[0]*c.pixels_per_unit,c.ground_y*768-root[1]*c.pixels_per_unit))
        rendered,_=render_frame(loaded,f,128)
        assert rendered.getchannel('A').getbbox()
    with zipfile.ZipFile(io.BytesIO(bake(loaded,clip,128))) as z:
        meta=json.loads(z.read('motion.json'))
        assert meta['rig']['limb_modes']['r_arm']=='single'
        for i,f in enumerate(clip['frames']):
            export=Image.open(io.BytesIO(z.read(f'frames/{i:03d}.png'))).convert('RGBA')
            preview,_=render_frame(loaded,f,128)
            assert export.tobytes()==preview.tobytes()


def test_api_config_and_project_mode_persistence(client,project):
    config=client.get('/api/config').json()
    assert set(config['single_bones'])==set(CHAINS)
    data=project.model_dump();data['rig']['limb_modes']['l_arm']='single'
    result=client.put(f'/api/projects/{project.id}',json={'expected_revision':project.revision,'project':data})
    assert result.status_code==200,result.text
    loaded=client.get(f'/api/projects/{project.id}').json()
    assert loaded['rig']['limb_modes']['l_arm']=='single'
    solved=client.post(f'/api/projects/{project.id}/solve')
    assert solved.status_code==200,solved.text


@pytest.mark.parametrize('locked',[False,True])
def test_reference_retarget_and_bake_respect_single_modes(locked):
    from lab.reference import synthetic_reference
    p=Project(id='b'*32,rig=rig_modes(*CHAINS),reference_motion=synthetic_reference(),motion=Motion(kind='reference',frames=8,lock_contacts=locked))
    original=solve_project(p)
    for f in original['frames']: assert_rigid(p.rig,f)
    p.motion=convert_to_keyframes(p)
    for f in solve_project(p)['frames']: assert_rigid(p.rig,f)


def test_archived_elbow_track_does_not_bend_single_arm():
    r=rig_modes('r_arm');m=Motion(kind='idle')
    baseline=template_frame(r,m,0)
    m.keys=[Key(phase=0,target='bone:r_forearm',angle=90)]
    result=template_frame(r,m,0)
    assert result['joints']==baseline['joints']
    assert m.keys[0].angle==90  # retained for switching back
    r.limb_modes['r_arm']='two'
    assert template_frame(r,m,0)['joints']!=template_frame(r,Motion(kind='idle'),0)['joints']


def test_mixed_legacy_and_new_pose_alias_keys_interpolate_continuously():
    r=rig_modes('r_arm');p=Project(id='c'*32,rig=r,motion=Motion(kind='idle',frames=4))
    p.motion=convert_to_keyframes(p)
    # Remove an alias from one otherwise complete legacy-compatible pose only.
    del p.motion.pose_keys[1].angles['r_arm']
    for u in (.249999,.25,.250001,.4):
        assert_rigid(r,pose_frame(r,p.motion,u))
    a=pose_frame(r,p.motion,.249999)['joints']['r_wrist']
    b=pose_frame(r,p.motion,.250001)['joints']['r_wrist']
    assert math.dist(a,b)<1e-5


@pytest.mark.parametrize('kind,target',[('joint','r_elbow'),('bone','r_forearm')])
def test_hidden_joint_and_bone_cannot_be_edited(kind,target):
    rig=rig_modes('r_arm');original=rig.model_dump()
    kwargs={'x':.2,'y':.7} if kind=='joint' else {'length':.2,'angle':0}
    with pytest.raises(ValueError):edit_rig(rig,RigEdit(expected_revision=0,kind=kind,target=target,**kwargs))
    assert rig.model_dump()==original


def test_single_minimum_length_allows_short_archived_segments():
    rig=rig_modes('r_arm')
    edited=edit_rig(rig,RigEdit(expected_revision=0,kind='bone',target='r_arm',length=.008,angle=0))
    assert math.dist(edited.joints['r_shoulder'],edited.joints['r_wrist'])==pytest.approx(.008)
    assert math.dist(edited.joints['r_shoulder'],edited.joints['r_elbow'])<.008
    assert_rigid(edited,template_frame(edited,Motion(kind='idle'),0))
    # Reverting after destructive shortening must reject, not invent geometry.
    data=edited.model_dump();data['limb_modes']['r_arm']='two'
    with pytest.raises(ValidationError):Rig.model_validate(data)
