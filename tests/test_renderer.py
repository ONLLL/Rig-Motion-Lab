import io,json,math,zipfile
import pytest
from PIL import Image
from lab.renderer import part_matrix,render_frame,bake,assets
from lab.motion import solve_project
from lab import storage


def test_material_grip_follows_hand_not_bbox(project):
    part=next(p for p in project.parts if p.bone=='weapon');im=storage.image(project.id,part.image)
    grip=(part.anchor_a[0]*im.width,part.anchor_a[1]*im.height)
    for f in solve_project(project)['frames']:
        m=part_matrix(project,part,f,im.size,768);w=f['joints']['r_wrist'];c=project.camera
        assert m.apply(grip)==pytest.approx((c.root_x*768+w[0]*c.pixels_per_unit,c.ground_y*768-w[1]*c.pixels_per_unit))


def test_fixed_render_deterministic_and_original_assets_unchanged(project):
    c=solve_project(project);part=project.parts[0];before=storage.asset_file(project.id,part.image).read_bytes()
    a,_=render_frame(project,c['frames'][4],128);b,_=render_frame(project,c['frames'][4],128)
    assert a.tobytes()==b.tobytes();assert a.size==(128,128)
    assert before==storage.asset_file(project.id,part.image).read_bytes()


def test_unreachable_large_weapon_clipping_detected_no_autofit(project):
    part=next(v for v in project.parts if v.bone=='weapon');part.scale=4
    c=solve_project(project)
    with pytest.raises(ValueError,match='裁切'):bake(project,c,128)
    z=zipfile.ZipFile(io.BytesIO(bake(project,c,128,allow_clipping=True)))
    info=json.loads(z.read('motion.json'))
    assert info['export']['clipped_parts'] and info['export']['camera']==project.camera.model_dump()

@pytest.mark.parametrize('kind',['idle','walk','attack','jump'])
def test_export_png_grid_timing_and_alpha(project,kind):
    project.motion.kind=kind;project.motion.frames=8;c=solve_project(project)
    data=bake(project,c,64)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        atlas=json.loads(z.read('atlas.json'));m=json.loads(z.read('motion.json'))
        sheet=Image.open(io.BytesIO(z.read('spritesheet.png'))).convert('RGBA')
        assert len(atlas['frames'])==8
        for item in atlas['frames']:
            im=Image.open(io.BytesIO(z.read(item['file']))).convert('RGBA');assert im.size==(64,64)
            assert im.getchannel('A').getextrema()==(0,255)
            crop=sheet.crop((item['x'],item['y'],item['x']+64,item['y']+64))
            assert crop.tobytes()==im.tobytes()
        assert sum(x['duration_ms'] for x in atlas['frames'])==m['duration_ms']
        assert m['loop']==(kind in ('idle','walk'))
        assert 'api_key' not in z.read('motion.json').decode().lower()


def test_no_materials_cannot_masquerade_as_character_export(project):
    project.parts=[]
    with pytest.raises(ValueError,match='没有绑定'):bake(project,solve_project(project),64)


def test_unconfirmed_rig_refuses_export(project):
    project.rig.approved=False
    with pytest.raises(ValueError,match='确认骨架'):bake(project,solve_project(project),64)
