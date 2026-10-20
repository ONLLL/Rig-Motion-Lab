"""Real browser arithmetic tested in Node, with Python model/solver/export checks.

No image models, online APIs or learned motion are invoked. One bulk edit changes
pose data transactionally; all unaffected keys, bind data and textures stay fixed.
"""
from __future__ import annotations
import copy
import json
import math
import shutil
import subprocess
import io
import zipfile
from pathlib import Path

import pytest
from lab.models import BONES, Motion, Project, LayerKey
from lab.poseclip import convert_to_keyframes, interpolate_pose, pose_frame
from lab.motion import solve_project
from lab import storage
from lab.renderer import bake

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def keyed(project):
    project.motion=convert_to_keyframes(project)
    return project


def node(project, request=None, *, action='apply', phase=.5, motion=None):
    if shutil.which('node') is None:
        pytest.skip('Browser arithmetic tests need Node.js (not required to run the app)')
    payload={'rig':project.rig.model_dump(),'bones':BONES,
             'motion':motion or project.motion.model_dump(), 'action':action,'phase':phase,
             'request':{'center':.5,'scope':'nearby','radius':.2,'falloff':'smooth',
                        'strength':1,'wrap':True,'target':'bone:head','delta':20,**(request or {})}}
    raw=subprocess.run(['node',str(ROOT/'tools/influence_runner.cjs')],input=json.dumps(payload),
                       text=True,capture_output=True,timeout=10,check=True)
    return json.loads(raw.stdout)


def apply(project, req):
    out=node(project,req)
    assert out['ok'],out
    assert out['source_unchanged']
    result=out['result']
    result['validated']=Motion.model_validate(result['motion'])
    return result


@pytest.mark.parametrize('scope',['nearby','range','all','single'])
@pytest.mark.parametrize('falloff',['smooth','linear','constant'])
def test_temporal_weights_apply_delta_without_copying_poses(keyed,scope,falloff):
    before=keyed.model_dump()
    result=apply(keyed,{'scope':scope,'start':.25,'end':.75,'falloff':falloff})
    a=keyed.motion.pose_keys;b=result['validated'].pose_keys
    weights=result['summary']['weights']
    for old,new,w in zip(a,b,weights):
        assert new.angles['head']==pytest.approx(old.angles['head']+20*w['weight'])
        assert {k:v for k,v in new.angles.items() if k!='head'}=={k:v for k,v in old.angles.items() if k!='head'}
        for field in ['phase','travel_x','root','weapon','targets','contacts','contact_ids','interpolation']:
            assert getattr(old,field)==getattr(new,field)
        if w['weight']==0:assert old==new
    assert keyed.model_dump()==before
    assert result['summary']['affected']==sum(w['weight']>1e-10 for w in weights)


def test_all_bone_angles_retain_original_phase_to_phase_changes(keyed):
    out=apply(keyed,{'scope':'all','target':'bone:r_upper_arm','delta':27})
    old=keyed.motion.pose_keys;new=out['validated'].pose_keys
    assert len(new)==len(old)==25
    for a,b,c,d in zip(old,old[1:],new,new[1:]):
        assert d.angles['r_upper_arm']-c.angles['r_upper_arm']==pytest.approx(b.angles['r_upper_arm']-a.angles['r_upper_arm'])
    # Not a copied static pose: the animation still changes over time.
    assert len({round(k.angles['r_upper_arm'],3) for k in new})>5


def test_known_smooth_and_linear_weights(keyed):
    # At .375 with radius .25 and center .5, linear and smooth are both .5.
    for falloff in ['linear','smooth']:
        out=apply(keyed,{'radius':.25,'falloff':falloff})
        w={row['phase']:row['weight'] for row in out['summary']['weights']}
        assert w[.5]==1 and w[.375]==.5 and w[.25]==0 and w[.75]==0
    out=apply(keyed,{'scope':'range','start':.25,'end':.75,'falloff':'constant'})
    w={row['phase']:row['weight'] for row in out['summary']['weights']}
    assert w[.25]==w[.75]==1 and w[0]==0


def test_nearby_defaults_do_not_change_distant_keys(keyed):
    out=apply(keyed,{})
    assert out['summary']['affected']==9
    assert out['validated'].pose_keys[0]==keyed.motion.pose_keys[0]
    assert out['validated'].pose_keys[-1]==keyed.motion.pose_keys[-1]
    assert out['validated'].pose_keys[12].angles['head']==pytest.approx(keyed.motion.pose_keys[12].angles['head']+20)


@pytest.mark.parametrize('root_mode',['in_place','world'])
def test_all_pelvis_delta_moves_each_original_root_without_losing_travel(keyed,root_mode):
    keyed.motion.root_mode=root_mode
    out=apply(keyed,{'scope':'all','target':'pelvis','delta':[.07,.03]})
    for old,new in zip(keyed.motion.pose_keys,out['validated'].pose_keys):
        assert new.root==pytest.approx((old.root[0]+.07,old.root[1]+.03))
        assert new.travel_x==old.travel_x and new.targets==old.targets
        assert new.angles==old.angles
    for u in [0,.1,.5,.8,1]:
        old=pose_frame(keyed.rig,keyed.motion,u)
        new=pose_frame(keyed.rig,out['validated'],u)
        for name,p in old['joints'].items():assert new['joints'][name]==pytest.approx([p[0]+.07,p[1]+.03])


@pytest.mark.parametrize('target',['l_wrist','r_wrist','l_ankle','r_ankle'])
def test_ik_bulk_uses_each_pose_endpoint_and_never_stretches(keyed,target):
    out=apply(keyed,{'scope':'all','target':target,'delta':[.004,.008]})
    maximum=0
    for k in out['validated'].pose_keys:
        f=pose_frame(keyed.rig,out['validated'],k.phase)
        original=pose_frame(keyed.rig,keyed.motion,k.phase)
        wanted=[original['world_joints'][target][0]+.004,original['world_joints'][target][1]+.008]
        error=math.dist(f['world_joints'][target],wanted);maximum=max(error,maximum)
        assert f['bone_error']<1e-9
        assert math.dist(f['joints']['weapon_tip'],f['joints']['r_wrist'])==pytest.approx(keyed.rig.weapon_length)
        for name in ['l_wrist','r_wrist','l_ankle','r_ankle']:
            if name!=target:assert f['world_joints'][name]==pytest.approx(original['world_joints'][name])
    assert maximum==pytest.approx(out['summary']['max_ik_error'],abs=1e-9)


def test_unreachable_ik_reports_failure_to_reach_without_changing_other_keys(keyed):
    out=apply(keyed,{'target':'r_wrist','delta':[4,4]})
    assert out['summary']['max_ik_error']>4 and any('不可达' in w or '可达范围' in w for w in out['summary']['warnings'])
    assert out['validated'].pose_keys[0]==keyed.motion.pose_keys[0]


def test_planted_feet_keep_original_contact_diagnostics(keyed):
    out=apply(keyed,{'scope':'all','target':'r_ankle','delta':[.01,.03]})
    for old,new in zip(keyed.motion.pose_keys,out['validated'].pose_keys):
        assert new.contacts==old.contacts and new.contact_ids==old.contact_ids
        if old.contacts.get('r'): assert new.targets['r_ankle']==old.targets['r_ankle']
    keyed.motion=out['validated'];clip=solve_project(keyed)
    assert clip['diagnostics']['max_contact_error']>.01


def test_existing_elbow_branch_is_preserved_per_pose(keyed):
    for k in keyed.motion.pose_keys:k.angles['r_forearm']=-k.angles['r_forearm']
    out=apply(keyed,{'scope':'all','target':'r_wrist','delta':[.001,.001]})
    for old,new in zip(keyed.motion.pose_keys,out['validated'].pose_keys):
        def cross(m):
            p=pose_frame(keyed.rig,m,old.phase)['world_joints'];a=p['r_shoulder'];b=p['r_elbow'];c=p['r_wrist']
            return (c[0]-a[0])*(b[1]-a[1])-(c[1]-a[1])*(b[0]-a[0])
        if abs(cross(keyed.motion))>1e-7 and abs(cross(out['validated']))>1e-7:
            assert math.copysign(1,cross(keyed.motion))==math.copysign(1,cross(out['validated']))


@pytest.mark.parametrize('scope',['single','nearby','range','all'])
def test_loop_boundary_applies_delta_once_keeps_endpoint_travel_and_other_bones(keyed,scope):
    out=apply(keyed,{'scope':scope,'center':0,'start':0,'end':.3})
    old=keyed.motion.pose_keys;new=out['validated'].pose_keys
    for a,b in [(old[0],new[0]),(old[-1],new[-1])]:
        assert b.angles['head']==pytest.approx(a.angles['head']+20)
        assert b.travel_x==a.travel_x and b.contact_ids==a.contact_ids and b.root==a.root
        assert b.angles['r_thigh']==a.angles['r_thigh']
    assert new[0].travel_x!=new[-1].travel_x


def test_wrapped_nearby_modifies_both_ends_but_not_middle(keyed):
    out=apply(keyed,{'center':0,'radius':.15})
    w=out['summary']['weights']
    assert w[1]['weight']>0 and w[-2]['weight']>0 and w[12]['weight']==0


def test_nonloop_or_unlinked_does_not_expand_to_far_end(keyed):
    keyed.motion.link_loop_ends=False
    out=apply(keyed,{'center':0})
    assert out['validated'].pose_keys[-1]==keyed.motion.pose_keys[-1]
    keyed.motion=Motion(kind='attack');keyed.motion=convert_to_keyframes(keyed)
    out=apply(keyed,{'center':0})
    assert out['validated'].pose_keys[-1]==keyed.motion.pose_keys[-1]


def test_non_key_time_inserts_one_current_pose_not_every_frame(keyed):
    out=apply(keyed,{'center':.33123,'scope':'all'})
    assert len(out['validated'].pose_keys)==26 and out['summary']['inserted']
    k=next(k for k in out['validated'].pose_keys if k.phase==.33123)
    old=interpolate_pose(keyed.motion,.33123)
    assert k.angles['head']==pytest.approx(old.angles['head']+20)
    assert k.targets==old.targets


@pytest.mark.parametrize('extra',[{'delta':0},{'strength':0}])
def test_zero_change_is_exact_noop_no_insertions(keyed,extra):
    out=apply(keyed,{'scope':'all','center':.33123,**extra})
    assert out['motion']==keyed.motion.model_dump(mode='json')
    assert not out['summary']['changed']


@pytest.mark.parametrize('bad',[
    {'scope':'unknown'},{'center':-1},{'center':2},{'strength':1.2},{'radius':0},
    {'radius':.9},{'falloff':'bad'},{'target':'bone:fake'},
    {'scope':'range','start':.7,'end':.8},{'scope':'range','start':.5,'end':.5},
    {'target':'r_wrist','delta':[1]},{'target':'r_wrist','delta':1},
    {'target':'pelvis','delta':[20,0]},{'target':'bone:head','delta':15000},
])
def test_invalid_edits_fail_atomically(keyed,bad):
    out=node(keyed,bad)
    assert not out['ok'] and out['source_unchanged']


def test_cannot_edit_nonconverted_template(project):
    out=node(project,{})
    assert not out['ok'] and out['source_unchanged']


def test_pose_capacity_cannot_be_silently_exceeded(keyed):
    keyed.motion.pose_keys=[interpolate_pose(keyed.motion,i/128) for i in range(129)]
    out=node(keyed,{'center':.33123})
    assert not out['ok'] and out['source_unchanged']
    assert '129' in out['error']
    out=apply(keyed,{'center':.5,'scope':'all'})
    assert len(out['validated'].pose_keys)==129


@pytest.mark.parametrize('easing',['linear','smooth','step'])
def test_influence_sampling_matches_python_runtime(keyed,easing):
    for k in keyed.motion.pose_keys:k.interpolation=easing
    for phase in [.123,.56789]:
        out=node(keyed,action='sample',phase=phase)['result']
        expected=interpolate_pose(keyed.motion,phase)
        assert out['root']==pytest.approx(expected.root)
        assert out['angles']==pytest.approx(expected.angles)
        assert out['weapon']==pytest.approx(expected.weapon)
        for n in expected.targets:assert out['targets'][n]==pytest.approx(expected.targets[n])


def test_reapplying_different_scope_from_snapshot_is_not_cumulative(keyed):
    first=apply(keyed,{'scope':'all','delta':30})
    second=apply(keyed,{'scope':'all','delta':30,'strength':.5})
    for a,b,c in zip(keyed.motion.pose_keys,first['validated'].pose_keys,second['validated'].pose_keys):
        assert b.angles['head']==pytest.approx(a.angles['head']+30)
        assert c.angles['head']==pytest.approx(a.angles['head']+15) # not +45


def test_bulk_save_export_restore_and_revision_lease(client,project):
    pid=project.id
    r=client.post(f'/api/projects/{pid}/motion/convert',json={'expected_revision':project.revision})
    assert r.status_code==200
    saved=storage.load(pid);before=saved.model_dump()
    saved.motion_library['idle']=Motion(kind='idle')
    saved.motion.layer_keys=[LayerKey(phase=.5,part_id=saved.parts[0].id,z=10,visible=True)]
    delta=apply(saved,{'scope':'all','target':'bone:r_upper_arm','delta':8})
    saved.motion=delta['validated'];revision=saved.revision
    r=client.put(f'/api/projects/{pid}',json={'expected_revision':revision,'project':saved.model_dump(mode='json')})
    assert r.status_code==200 and r.json()['revision']==revision+1
    assert client.put(f'/api/projects/{pid}',json={'expected_revision':revision,'project':saved.model_dump(mode='json')}).status_code==409
    reopened=storage.load(pid)
    assert reopened.rig.model_dump()==before['rig']
    assert [p.model_dump() for p in reopened.parts]==before['parts']
    assert reopened.motion_library['idle']==Motion(kind='idle')
    assert len(reopened.motion.layer_keys)==1
    export=client.post(f'/api/projects/{pid}/export',json={'expected_revision':reopened.revision,'size':64,'allow_clipping':True})
    assert export.status_code==200
    z=zipfile.ZipFile(io.BytesIO(export.content))
    motion=json.loads(z.read('motion.json'))
    assert 'pose_keys' in json.dumps(motion)
    archive=client.get(f'/api/projects/{pid}/download')
    imported=client.post('/api/import-project',files={'file':('roundtrip.riglab.zip',archive.content,'application/zip')})
    assert imported.status_code==200
    assert imported.json()['motion']==reopened.motion.model_dump(mode='json')


def test_entry_loads_temporal_editor_modules(client):
    html=client.get('/').text
    assert 'influence-editor.js' in html and 'motion-influence.js' in html
    for name in ['motion-influence.js','influence-editor.js','influence-editor.css']:
        assert client.get('/static/'+name).status_code==200
    assert client.get('/api/config').json()['editor_version']==4
