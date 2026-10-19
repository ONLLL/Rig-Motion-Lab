import math,random
import pytest
from lab.math2d import two_bone_ik,walking_foot,unwrap_angles,Affine
from lab.demo import default_rig
from lab.models import Motion,BONES,Project,Key
from lab.motion import template_frame,solve_project,key_offset
from lab.reference import synthetic_reference


def test_random_two_link_chains_preserve_lengths_and_report_projection():
    r=random.Random(213)
    for i in range(1000):
        root=(r.uniform(-2,2),r.uniform(-2,2));target=(r.uniform(-3,3),r.uniform(-3,3))
        a,b=r.uniform(.04,1),r.uniform(.04,1);out=two_bone_ik(root,target,a,b,r.choice((-1,1)))
        assert math.dist(root,out.joint)==pytest.approx(a,abs=1e-8)
        assert math.dist(out.joint,out.end)==pytest.approx(b,abs=1e-8)
        assert out.residual==pytest.approx(math.dist(target,out.end))

@pytest.mark.parametrize('side',[-1,1])
def test_coincident_target_uses_explicit_bend(side):
    out=two_bone_ik((0,0),(0,0),.2,.2,side,(0,-1));assert all(math.isfinite(x) for x in out.joint+out.end)
    assert out.joint[0]*side>0

@pytest.mark.parametrize('offset',[0,.5])
def test_stance_is_stationary_in_world_not_screen(offset):
    seen={}
    for i in range(2000):
        f=walking_foot(i/1000,phase_offset=offset)
        if f.contact:
            old=seen.setdefault(f.contact_id,f.world_ankle);assert f.world_ankle==pytest.approx(old)
    assert walking_foot(.3).local_ankle[0]<walking_foot(.1).local_ankle[0]

@pytest.mark.parametrize('u',[.6,1.])
def test_swing_velocity_continuity(u):
    h=1e-6;pts=[walking_foot(u+v).world_ankle for v in (-h,0,h)]
    for d in (0,1):assert (pts[1][d]-pts[0][d])/h==pytest.approx((pts[2][d]-pts[1][d])/h,abs=1e-4)

@pytest.mark.parametrize('kind',['idle','walk','attack','jump'])
@pytest.mark.parametrize('short',[False,True])
def test_template_fixed_length_both_proportions(kind,short):
    rig=default_rig(short);m=Motion(kind=kind,stride=.13,lift=.04)
    fs=[template_frame(rig,m,i/80) for i in range(81)]
    assert max(f['bone_error'] for f in fs)<1e-8
    for f in fs:
        assert math.dist(f['joints']['r_wrist'],f['joints']['weapon_tip'])==pytest.approx(rig.weapon_length)
        assert all(math.isfinite(v) for p in f['joints'].values() for v in p)


def test_default_walk_targets_and_sliding_report(project):
    clip=solve_project(project);d=clip['diagnostics']
    assert d['max_contact_error']<1e-8 and d['max_stance_step_slip']<1e-8
    assert clip['frames'][-1]['phase']<1 and clip['duration_ms']==1000


def test_large_stride_is_not_hidden_with_bone_stretch(project):
    project.motion.stride=.45;clip=solve_project(project)
    assert clip['diagnostics']['max_reach_error']>.01
    assert clip['diagnostics']['max_bone_error']<1e-8
    assert any('不可达' in s for s in clip['diagnostics']['warnings'])


def test_jump_preserves_vertical_motion_and_releases_contacts(project):
    project.motion.kind='jump';c=solve_project(project)
    f=c['frames'][len(c['frames'])//2]
    assert f['joints']['pelvis'][1]>project.rig.joints['pelvis'][1]+.1
    assert not any(f['contacts'].values());assert c['loop'] is False


def test_root_world_and_in_place_differ_only_by_horizontal_root(project):
    f=template_frame(project.rig,project.motion,.3);project.motion.root_mode='world';g=template_frame(project.rig,project.motion,.3)
    for k in f['joints']:
        assert g['joints'][k][0]-f['joints'][k][0]==pytest.approx(f['root_motion'][0])
        assert g['joints'][k][1]==pytest.approx(f['joints'][k][1])


def test_keyframe_correction_has_exact_value_and_keeps_structure(project):
    project.motion.keys=[Key(phase=.5,target='r_wrist',dx=.03,dy=.02)]
    assert key_offset(project.motion,'r_wrist',.5)==pytest.approx((.03,.02,0))
    frame=template_frame(project.rig,project.motion,.5);assert frame['bone_error']<1e-8


def test_reference_retarget_fixed_lengths_and_explicit_calibration(project):
    project.reference_motion=synthetic_reference();project.motion.kind='reference'
    project.motion.smoothing=1
    clip=solve_project(project)
    for k in project.rig.joints:
        assert clip['frames'][0]['joints'][k]==pytest.approx(project.rig.joints[k])
    assert clip['diagnostics']['max_bone_error']<1e-8
    assert clip['diagnostics']['max_stance_step_slip']<1e-8
    assert 'not human mocap' in project.reference_motion.provenance


def test_bad_reference_bind_is_rejected(project):
    project.reference_motion=synthetic_reference();project.motion.kind='reference';project.motion.reference_bind=239
    with pytest.raises(ValueError,match='校准帧'):solve_project(project)


def test_angle_unwrap_and_affine_inverse():
    x=unwrap_angles([math.radians(v) for v in (179,-179,-178)])
    assert math.degrees(x[-1])==pytest.approx(182)
    m=Affine.translation(2,5)@Affine.rotation(.7)@Affine.scale(.3,-.3)
    assert m.inverse().apply(m.apply((14,29)))==pytest.approx((14,29))
