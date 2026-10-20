"""Independent template editing: geometry, persistence, HTTP and rendered output.

These are deterministic tests; they do not exercise any generation/video model.
"""
import io
import math
import zipfile
import json
import pytest
from pydantic import ValidationError
from lab import storage
from lab.models import Motion, PoseKey, Key, Project, LayerKey, BONES
from lab.motion import solve_project
from lab.poseclip import capture_pose, convert_to_keyframes, pose_frame, interpolate_pose
from lab.reference import synthetic_reference
from lab.renderer import render_frame, bake, assets


@pytest.mark.parametrize('kind',['idle','walk','attack','jump','reference'])
@pytest.mark.parametrize('root_mode',['in_place','world'])
def test_conversion_preserves_every_original_sample(project,kind,root_mode):
    project.motion=Motion(kind=kind,root_mode=root_mode,frames=12)
    if kind=='reference': project.reference_motion=synthetic_reference()
    before=solve_project(project)
    project.motion=convert_to_keyframes(project)
    after=solve_project(project)
    assert len(project.motion.pose_keys)==(13 if kind in ('idle','walk') else 12)
    assert after['events']==before['events'] and after['duration_ms']==before['duration_ms']
    for old,new in zip(before['frames'],after['frames']):
        for joint in old['joints']:
            assert new['joints'][joint]==pytest.approx(old['joints'][joint],abs=1e-9)
            assert new['world_joints'][joint]==pytest.approx(old['world_joints'][joint],abs=1e-9)
        for name in old['targets']: assert new['targets'][name]==pytest.approx(old['targets'][name],abs=1e-9)
        assert new['contacts']==old['contacts']
        assert new['bone_error']<1e-9


def test_captures_old_correction_tracks_exactly_and_does_not_double_apply(project):
    project.motion=Motion(kind='idle',keys=[Key(phase=.5,target='bone:r_upper_arm',angle=30),Key(phase=.5,target='r_ankle',dx=.1)])
    before=solve_project(project)
    project.motion=convert_to_keyframes(project)
    assert not project.motion.keys and len(project.motion.source_motion['keys'])==2
    for a,b in zip(before['frames'],solve_project(project)['frames']):
        assert b['joints']['r_wrist']==pytest.approx(a['joints']['r_wrist'],abs=1e-9)


def test_keyframes_do_not_run_parametric_generator(project,monkeypatch):
    project.motion=convert_to_keyframes(project)
    def forbid(*args): raise AssertionError('Old template must not run')
    monkeypatch.setattr('lab.motion.template_frame',forbid)
    before=solve_project(project)
    project.motion.stride=.4
    after=solve_project(project)
    assert after['frames']==before['frames']


def test_edit_absolute_pose_changes_output_but_keeps_bones_and_grip(project):
    project.motion=convert_to_keyframes(project)
    base=pose_frame(project.rig,project.motion,.5)
    k=next(k for k in project.motion.pose_keys if k.phase==.5)
    k.angles['r_upper_arm']+=35
    new=pose_frame(project.rig,project.motion,.5)
    assert math.dist(new['joints']['r_wrist'],base['joints']['r_wrist'])>.05
    assert new['joints']['l_wrist']==pytest.approx(base['joints']['l_wrist'])
    assert new['bone_error']<1e-9
    assert math.dist(new['joints']['r_wrist'],new['joints']['weapon_tip'])==pytest.approx(project.rig.weapon_length)
    assert new['reach_errors']['r_arm']>.05
    assert project.motion.pose_keys[0].angles['r_upper_arm'] != k.angles['r_upper_arm']


@pytest.mark.parametrize('easing,fraction',[('linear',.25),('smooth',.15625),('step',0)])
def test_outgoing_interpolation_and_exact_key_boundary(project,easing,fraction):
    project.motion=convert_to_keyframes(project)
    a=project.motion.pose_keys[0].model_copy(deep=True);b=a.model_copy(deep=True)
    a.interpolation=easing;b.phase=1;b.angles['head']+=40
    project.motion.pose_keys=[a,b]
    assert interpolate_pose(project.motion,.25).angles['head']==pytest.approx(a.angles['head']+40*fraction)
    assert interpolate_pose(project.motion,1).angles['head']==b.angles['head']


def test_unwrap_does_not_spin_across_180(project):
    project.motion=Motion(kind='attack',frames=64)
    converted=convert_to_keyframes(project)
    for name in BONES:
        assert max(abs(b.angles[name]-a.angles[name]) for a,b in zip(converted.pose_keys,converted.pose_keys[1:]))<=180+1e-9


def test_fk_edit_reports_contact_loss(project):
    project.motion=Motion(kind='idle',frames=8)
    project.motion=convert_to_keyframes(project)
    project.motion.pose_keys[2].angles['l_thigh']+=50
    clip=solve_project(project)
    assert clip['diagnostics']['max_contact_error']>.05
    assert clip['diagnostics']['max_stance_step_slip']>.05
    assert any('不自动锁脚' in w for w in clip['diagnostics']['warnings'])


@pytest.mark.parametrize('mutation', ['missing_bone','nan_angle','duplicate_time','missing_start','missing_end','reverse_time','old_offsets','nested_backup'])
def test_invalid_keyframe_payloads_are_rejected(project,mutation):
    data=convert_to_keyframes(project).model_dump()
    if mutation=='missing_bone': data['pose_keys'][0]['angles'].pop('head')
    elif mutation=='nan_angle': data['pose_keys'][0]['angles']['head']=float('nan')
    elif mutation=='duplicate_time': data['pose_keys'][1]['phase']=0
    elif mutation=='missing_start': data['pose_keys']=data['pose_keys'][1:]
    elif mutation=='missing_end': data['pose_keys']=data['pose_keys'][:-1]
    elif mutation=='reverse_time': data['pose_keys'].reverse()
    elif mutation=='old_offsets': data['keys']=[Key(phase=0,target='weapon').model_dump()]
    else: data['source_motion']['source_motion']={}
    with pytest.raises(ValidationError): Motion.model_validate(data)


def test_old_project_defaults_to_template_and_is_loadable(project):
    data=project.model_dump()
    for k in ['driver','pose_keys','source_motion','link_loop_ends']:data['motion'].pop(k)
    restored=Project.model_validate(data)
    assert restored.motion.driver=='template' and restored.motion.pose_keys==[]


def test_convert_restore_http_revision_and_library(client,project):
    pid=project.id;rev=project.revision;original=project.motion.model_dump()
    r=client.post(f'/api/projects/{pid}/motion/convert',json={'expected_revision':rev})
    assert r.status_code==200;data=r.json()
    assert data['motion']['driver']=='keyframes' and data['revision']==rev+1
    assert client.post(f'/api/projects/{pid}/motion/restore',json={'expected_revision':rev}).status_code==409
    data.pop('asset_prefix')
    data['motion']['pose_keys'][2]['angles']['head']+=20
    r=client.put(f'/api/projects/{pid}',json={'expected_revision':data['revision'],'project':data})
    assert r.status_code==200
    reopened=storage.load(pid)
    assert reopened.motion_library['walk'].driver=='keyframes'
    assert reopened.motion_library['walk'].pose_keys[2].angles['head']==data['motion']['pose_keys'][2]['angles']['head']
    r=client.post(f'/api/projects/{pid}/motion/restore',json={'expected_revision':reopened.revision})
    assert r.status_code==200 and r.json()['motion']==original


def test_pose_edit_appears_in_png_and_exported_motion(project):
    project.motion=convert_to_keyframes(project)
    imgs=assets(project);before=render_frame(project,solve_project(project)['frames'][0],128,imgs)[0]
    project.motion.pose_keys[0].angles['r_upper_arm']+=40
    clip=solve_project(project)
    after=render_frame(project,clip['frames'][0],128,imgs)[0]
    assert before.tobytes()!=after.tobytes()
    z=zipfile.ZipFile(io.BytesIO(bake(project,clip,64,allow_clipping=True)))
    dumped=json.loads(z.read('motion.json'))
    assert dumped['motion']['driver']=='keyframes'
    assert dumped['motion']['pose_keys'][0]['angles']==project.motion.pose_keys[0].angles
    assert 'highlight' not in dumped['motion']


def test_per_action_layer_overrides_survive_conversion_restore(client,project):
    project.motion.layer_keys=[LayerKey(phase=.5,part_id=project.parts[0].id,z=70,visible=False)]
    p=storage.save(project,project.revision)
    data=client.post(f'/api/projects/{p.id}/motion/convert',json={'expected_revision':p.revision}).json()
    assert data['motion']['layer_keys']==p.motion.model_dump()['layer_keys']
    data.pop('asset_prefix');data['motion']['layer_keys'][0]['z']=65
    response=client.put(f'/api/projects/{p.id}',json={'expected_revision':data['revision'],'project':data}).json()
    restored=client.post(f'/api/projects/{p.id}/motion/restore',json={'expected_revision':response['revision']}).json()
    assert restored['motion']['layer_keys'][0]['z']==65


def test_importing_reference_preserves_keyed_walk_in_library(client,project):
    p=client.post(f'/api/projects/{project.id}/motion/convert',json={'expected_revision':project.revision}).json()
    r=client.post(f'/api/projects/{project.id}/reference-example',data={'expected_revision':p['revision']})
    assert r.status_code==200
    assert r.json()['motion']['kind']=='reference' and r.json()['motion']['driver']=='template'
    assert r.json()['motion_library']['walk']['driver']=='keyframes'


def test_new_reference_does_not_overwrite_already_keyed_reference(client,project):
    p=client.post(f'/api/projects/{project.id}/reference-example',data={'expected_revision':project.revision}).json()
    p=client.post(f'/api/projects/{project.id}/motion/convert',json={'expected_revision':p['revision']}).json()
    r=client.post(f'/api/projects/{project.id}/reference-example',data={'expected_revision':p['revision']})
    assert r.status_code==422
    assert storage.load(project.id).motion.driver=='keyframes'
