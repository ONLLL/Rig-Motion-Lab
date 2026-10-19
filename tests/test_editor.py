"""Editor regressions: structure edits, FK/IK curves, draw order and persistence.

No model calls or video detection. Actual HTTP tests use local FastAPI TestClient.
"""
import io
import json
import math
import zipfile
import pytest
import numpy as np
from PIL import Image
from pydantic import ValidationError
from lab.demo import default_rig
from lab.models import Rig, Motion, Key, LayerKey, Part, Project, BONES
from lab.editing import descendants, edit_rig, RigEdit, ordered_parts
from lab.motion import key_offset, template_frame, solve_project
from lab.renderer import render_frame, prepare_preview, assets, bake
from lab import storage


def test_joint_cascade_translates_subtree_only():
    rig=default_rig();x,y=rig.joints['r_shoulder']
    result=edit_rig(rig,RigEdit(expected_revision=1,kind='joint',target='r_shoulder',x=x+.04,y=y+.05))
    for name in descendants('r_shoulder'):
        assert result.joints[name]==pytest.approx((rig.joints[name][0]+.04,rig.joints[name][1]+.05))
    for name in ('l_wrist','pelvis','chest','r_ankle'):
        assert result.joints[name]==rig.joints[name]
    assert not result.approved
    assert rig.joints['r_shoulder']==(x,y)


@pytest.mark.parametrize('degrees',[-150,-45,0,65,180])
def test_bone_rotation_length_preserves_descendant_lengths(degrees):
    rig=default_rig();a,b=BONES['r_upper_arm'];length=.17
    result=edit_rig(rig,RigEdit(expected_revision=1,kind='bone',target='r_upper_arm',length=length,angle=degrees))
    assert math.dist(result.joints[a],result.joints[b])==pytest.approx(length)
    assert math.dist(result.joints['r_elbow'],result.joints['r_wrist'])==pytest.approx(math.dist(rig.joints['r_elbow'],rig.joints['r_wrist']))
    end=(rig.joints[a][0]+length*math.cos(math.radians(degrees)),rig.joints[a][1]+length*math.sin(math.radians(degrees)))
    assert result.joints[b]==pytest.approx(end)
    assert result.joints['l_wrist']==rig.joints['l_wrist']


def test_joint_edit_without_cascade_changes_only_one_joint():
    rig=default_rig();x,y=rig.joints['r_elbow']
    result=edit_rig(rig,RigEdit(expected_revision=0,kind='joint',target='r_elbow',x=x+.03,y=y,cascade=False))
    assert result.joints['r_wrist']==rig.joints['r_wrist']


def test_collapse_rejected_without_mutating_original():
    rig=default_rig();original=rig.model_dump();x,y=rig.joints['r_shoulder']
    with pytest.raises(ValidationError):
        edit_rig(rig,RigEdit(expected_revision=0,kind='joint',target='r_elbow',x=x,y=y))
    assert rig.model_dump()==original


@pytest.mark.parametrize('kwargs',[
 {'kind':'joint','target':'new_tail','x':0,'y':0},
 {'kind':'bone','target':'head','length':.1},
 {'kind':'bone','target':'head','length':0,'angle':2},
 {'kind':'joint','target':'head','x':0,'y':0,'length':.1},
])
def test_structure_edit_rejects_unsupported_operations(kwargs):
    with pytest.raises(ValidationError):RigEdit(expected_revision=0,**kwargs)


@pytest.mark.parametrize('interp,expected',[('linear',.25),('smooth',.15625),('step',0)])
def test_keyframe_interpolation_contract(interp,expected):
    m=Motion(keys=[Key(phase=0,target='r_wrist',interpolation=interp),Key(phase=1,target='r_wrist',dx=.4)])
    assert key_offset(m,'r_wrist',.25)[0]==pytest.approx(.4*expected)
    assert key_offset(m,'r_wrist',1)[0]==pytest.approx(.4)


def test_fk_angles_rotate_descendants_keep_lengths_and_weapon_grip():
    rig=default_rig();base=Motion(kind='idle',frames=8)
    original=template_frame(rig,base,0)
    keyed=Motion(kind='idle',frames=8,keys=[Key(phase=0,target='bone:r_upper_arm',angle=30)])
    result=template_frame(rig,keyed,0)
    assert result['bone_error']<1e-9
    assert result['joints']['r_wrist']!=original['joints']['r_wrist']
    assert result['joints']['l_wrist']==original['joints']['l_wrist']
    assert math.dist(result['joints']['r_wrist'],result['joints']['weapon_tip'])==pytest.approx(rig.weapon_length)
    assert result['reach_errors']['r_arm']>0.01


def test_fk_leg_is_not_falsely_reported_as_contact_lock(project):
    project.motion=Motion(kind='idle',keys=[Key(phase=0,target='bone:r_thigh',angle=20)])
    result=solve_project(project)
    assert result['diagnostics']['max_bone_error']<1e-9
    assert result['diagnostics']['max_contact_error']>.01
    assert any('FK' in x for x in result['diagnostics']['warnings'])


def test_attack_hit_moves_authored_trajectory_and_event(project):
    project.motion=Motion(kind='attack',frames=25,hit_phase=.65)
    result=solve_project(project)
    assert result['events'][0]['phase']==.65
    event_frame=result['events'][0]['frame']
    assert event_frame==min(range(25),key=lambda i:abs(result['frames'][i]['phase']-.65))
    moved=template_frame(project.rig,project.motion,.65)
    base=template_frame(project.rig,Motion(kind='attack'),.65)
    assert moved['joints']['r_wrist']!=base['joints']['r_wrist']


@pytest.mark.parametrize('key',[
 {'target':'bone:unknown','phase':0},
 {'target':'bone:head','phase':0,'dx':.1},
 {'target':'r_wrist','phase':0,'angle':20},
 {'target':'weapon','phase':0,'dy':.1},
 {'target':'weapon','phase':0,'angle':181},
 {'target':'weapon','phase':0,'interpolation':'mystery'},
])
def test_invalid_animation_tracks_rejected(key):
    with pytest.raises(ValidationError):Key(**key)


def test_duplicate_keys_and_bad_attack_timing_rejected():
    with pytest.raises(ValidationError):Motion(keys=[Key(phase=.5,target='pelvis')]*2)
    with pytest.raises(ValidationError):Motion(anticipation=.4,hit_phase=.41)


def test_layer_override_is_step_hold_and_base_is_not_mutated(project):
    first,last=project.parts[0],project.parts[-1]
    baseline=[p.id for p in ordered_parts(project,0)]
    project.motion.layer_keys=[LayerKey(phase=.5,part_id=first.id,z=100,visible=True),LayerKey(phase=.8,part_id=last.id,z=-100,visible=False)]
    assert [p.id for p in ordered_parts(project,.49)]==baseline
    assert ordered_parts(project,.5)[-1].id==first.id
    assert last.id not in [p.id for p in ordered_parts(project,.8)]
    assert [p.id for p in ordered_parts(project,0)]==baseline
    assert last.visible


def test_hidden_part_can_be_shown_by_animation_key(project):
    part=project.parts[0];part.visible=False
    project.motion.layer_keys=[LayerKey(phase=.5,part_id=part.id,z=100,visible=True)]
    assert part.image in assets(project)
    clip=prepare_preview(project,solve_project(project))
    assert part.id not in [p['id'] for p in clip['frames'][0]['draws']]
    assert part.id in [p['id'] for p in clip['frames'][-1]['draws']]


def test_same_z_uses_original_index_for_deterministic_render_order(project):
    for p in project.parts:p.z=0
    assert [p.id for p in ordered_parts(project,0)]==[p.id for p in project.parts]


def test_layer_order_changes_actual_pixels_and_bake_matches_preview(project):
    a=storage.put_image(project.id,Image.new('RGBA',(32,16),(255,0,0,255)))
    b=storage.put_image(project.id,Image.new('RGBA',(32,16),(0,0,255,255)))
    project.parts=[Part(id='red',name='red',bone='head',image=a,z=0),Part(id='blue',name='blue',bone='head',image=b,z=1)]
    project.motion=Motion(kind='idle',frames=4,layer_keys=[LayerKey(phase=.5,part_id='red',z=3,visible=True)])
    clip=solve_project(project);images=assets(project)
    before,_=render_frame(project,clip['frames'][0],128,images);after,_=render_frame(project,clip['frames'][2],128,images)
    assert (0,0,255,255) in set(map(tuple,np.asarray(before).reshape(-1,4)))
    assert (255,0,0,255) not in set(map(tuple,np.asarray(before).reshape(-1,4)))
    assert (255,0,0,255) in set(map(tuple,np.asarray(after).reshape(-1,4)))
    preview=prepare_preview(project,clip)
    assert [x['id'] for x in preview['frames'][0]['draws']]==['red','blue']
    assert [x['id'] for x in preview['frames'][2]['draws']]==['blue','red']
    data=bake(project,clip,128,True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        exported=Image.open(io.BytesIO(z.read('frames/002.png'))).convert('RGBA')
        assert exported.tobytes()==after.tobytes()
        motion=json.loads(z.read('motion.json'))
        assert motion['motion']['layer_keys'][0]['part_id']=='red'


def test_rest_api_changes_and_revision_conflict(client,project):
    url=f'/api/projects/{project.id}/rig/edit'
    body={'expected_revision':project.revision,'kind':'bone','target':'r_forearm','length':.2,'angle':-20}
    response=client.post(url,json=body);assert response.status_code==200,response.text
    result=response.json();assert not result['rig']['approved']
    assert result['revision']==project.revision+1
    assert client.post(url,json=body).status_code==409
    assert storage.load(project.id).revision==result['revision']


def test_invalid_rest_edit_does_not_save(client,project):
    url=f'/api/projects/{project.id}/rig/edit'
    x,y=project.rig.joints['r_shoulder']
    response=client.post(url,json={'expected_revision':project.revision,'kind':'joint','target':'r_elbow','x':x,'y':y})
    assert response.status_code==422
    assert storage.load(project.id).revision==project.revision


def test_motion_library_and_keys_zip_roundtrip(client,project):
    base=f'/api/projects/{project.id}'
    project.motion=Motion(kind='attack',keys=[Key(phase=.42,target='bone:head',angle=15,interpolation='linear')],layer_keys=[LayerKey(phase=.5,part_id=project.parts[0].id,z=40,visible=False)])
    project.motion_library={'walk':Motion(kind='walk',stride=.11,keys=[Key(phase=.25,target='pelvis',dy=.01)])}
    p=storage.save(project,project.revision)
    result=client.get(base+'/download')
    response=client.post('/api/import-project',files={'file':('edit.riglab.zip',result.content,'application/zip')})
    assert response.status_code==200,response.text
    new=Project.model_validate({k:v for k,v in response.json().items() if k!='asset_prefix'})
    assert new.motion.keys==p.motion.keys
    assert new.motion.layer_keys==p.motion.layer_keys
    assert new.motion_library['walk'].stride==.11
    new.motion=new.motion_library['walk'].model_copy(deep=True)
    new=storage.save(new,new.revision)
    assert new.motion.kind=='walk' and new.motion_library['attack'].keys[0].target=='bone:head'


def test_dangling_layer_keys_rejected_and_valid_part_delete_requires_cleanup(project):
    project.motion.layer_keys=[LayerKey(phase=.5,part_id='does_not_exist',z=0,visible=True)]
    with pytest.raises(ValidationError):Project.model_validate(project.model_dump())


def test_reference_replacement_clears_all_motion_layer_references(client,project):
    project.motion.layer_keys=[LayerKey(phase=.5,part_id=project.parts[0].id,z=1,visible=True)]
    p=storage.save(project,project.revision)
    b=io.BytesIO();Image.new('RGBA',(64,64),(40,80,120,255)).save(b,'PNG')
    resp=client.post(f'/api/projects/{p.id}/reference-image',data={'expected_revision':p.revision},files={'file':('new.png',b.getvalue(),'image/png')})
    assert resp.status_code==200,resp.text
    result=resp.json();assert result['parts']==[]
    assert all(not m['layer_keys'] for m in result['motion_library'].values())
