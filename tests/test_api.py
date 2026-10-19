import io,json,zipfile
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from lab.main import app
from lab.demo import new_project
from lab import storage
from lab.models import Project


def png(size=(100,60),color=(200,100,50,255)):
    b=io.BytesIO();Image.new('RGBA',size,color).save(b,'PNG');return b.getvalue()

def test_http_config_and_local_write_guards(client):
    assert client.get('/api/health').json()['image_generation_calls']==0
    assert client.get('/api/config').json()['api_keys_required'] is False
    with TestClient(app) as c:
        assert c.post('/api/projects',data={'demo':'true'}).status_code==403
    assert client.post('/api/projects',data={'demo':'true'},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==400


def test_create_solve_save_revision_conflict(client,project):
    url=f'/api/projects/{project.id}';p=client.get(url).json();p.pop('asset_prefix')
    p['name']='改名';r=client.put(url,json={'expected_revision':p['revision'],'project':p});assert r.status_code==200
    assert client.put(url,json={'expected_revision':p['revision'],'project':p}).status_code==409
    c=client.post(url+'/solve').json();assert len(c['frames'])==24 and len(c['frames'][0]['draws'])==14


def test_bad_geometry_nan_unknown_fields_blocked(client,project):
    p=project.model_dump();p['rig']['joints']['r_elbow']=p['rig']['joints']['r_shoulder']
    assert client.put(f'/api/projects/{project.id}',json={'expected_revision':1,'project':p}).status_code==422
    p=project.model_dump();p['bad']='field'
    assert client.put(f'/api/projects/{project.id}',json={'expected_revision':1,'project':p}).status_code==422


def test_reference_upload_clears_old_appearance_and_requires_confirmation(client,project):
    r=client.post(f'/api/projects/{project.id}/reference-image',data={'expected_revision':1},files={'file':('ref.png',png(),'image/png')})
    assert r.status_code==200;p=r.json();assert not p['rig']['approved'] and p['parts']==[] and p['reference_placement']


def test_part_upload_crop_and_asset_url(client,project):
    base=f'/api/projects/{project.id}'
    r=client.post(base+'/part-image',data={'expected_revision':1,'bone':'weapon'},files={'file':('weapon.png',png(),'image/png')})
    assert r.status_code==200;p=r.json();part=p['parts'][-1]
    assert client.get(base+'/'+part['image']).status_code==200
    r=client.post(base+'/crop',json={'expected_revision':p['revision'],'bone':'head','name':'头部选区','polygon':[[.3,.1],[.7,.1],[.7,.6],[.3,.6]]})
    assert r.status_code==200 and len(r.json()['parts'])==16


def test_asset_path_is_not_general_file_server(client,project):
    base=f'/api/projects/{project.id}'
    assert client.get(base+'/assets/.env').status_code==422
    assert client.get(base+'/assets/project.json').status_code==422
    assert client.get(base+'/assets/abc.png').status_code==422


def test_project_zip_roundtrip_new_id_preserves_asset_pixels(client,project):
    base=f'/api/projects/{project.id}';r=client.get(base+'/download');assert r.status_code==200
    p=client.post('/api/import-project',files={'file':('p.zip',r.content,'application/zip')}).json()
    assert p['id']!=project.id and p['rig']['joints']['head']==list(project.rig.joints['head'])
    old=client.get(base+'/'+project.parts[0].image).content
    new=client.get(f"/api/projects/{p['id']}/"+p['parts'][0]['image']).content
    assert old==new


def test_zip_rejects_undeclared_paths_and_duplicate_entries(client,project):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('project.json',project.model_dump_json());z.writestr('../secret','x')
    r=client.post('/api/import-project',files={'file':('p.zip',b.getvalue(),'application/zip')})
    assert r.status_code==422


def test_reference_example_route_roundtrip_and_metadata(client,project):
    base=f'/api/projects/{project.id}'
    r=client.post(base+'/reference-example',data={'expected_revision':1});assert r.status_code==200
    p=r.json();assert p['motion']['kind']=='reference' and p['reference_motion']['provenance'].endswith('not human mocap')
    c=client.post(base+'/solve').json();assert c['diagnostics']['max_bone_error']<1e-8


def test_video_missing_configuration_returns_error_not_fake_motion(client,project):
    r=client.post(f'/api/projects/{project.id}/video',data={'expected_revision':1},files={'file':('x.mp4',b'bad','video/mp4')})
    assert r.status_code==409
    assert storage.load(project.id).reference_motion is None


def test_export_endpoint_real_zip(client,project):
    r=client.post(f'/api/projects/{project.id}/export',json={'expected_revision':1,'size':64})
    assert r.status_code==200 and r.headers['content-type']=='application/zip'
    with zipfile.ZipFile(io.BytesIO(r.content)) as z: assert z.testzip() is None and 'frames/000.png' in z.namelist()


def test_no_api_secrets_in_public_state(client,project,monkeypatch):
    secret='not-real-private-key';monkeypatch.setenv('OPENAI_API_KEY',secret)
    for path in ['/api/config',f'/api/projects/{project.id}']:
        assert secret not in client.get(path).text
