"""Chromium editor interaction tests via the local HTTP bridge.

Native browser navigation is blocked by this environment. This is not a native
browser-network E2E test; the bridge makes real local HTTP requests via Python.
"""
from __future__ import annotations
import argparse,base64,json,math,re,sys
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from browser_smoke import BRIDGE
ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',default='http://127.0.0.1:8020');args=ap.parse_args()
    client=httpx.Client(base_url=args.base,trust_env=False,timeout=35)
    def backend(payload):
        assert payload['url'].startswith('/api/')
        kw={'headers':payload.get('headers',{})}
        if 'form' in payload:
            data={};files=[]
            for item in payload['form']:
                if 'b64' in item:files.append((item['key'],(item['name'],base64.b64decode(item['b64']),item['type'])))
                else:data[item['key']]=item['value']
            kw['data']=data
            if files:kw['files']=files
        elif 'body' in payload:kw['content']=payload['body'].encode()
        response=client.request(payload.get('method','GET'),payload['url'],**kw)
        return {'status':response.status_code,'headers':{k:v for k,v in response.headers.items() if k in ('content-type','content-disposition')},'body':base64.b64encode(response.content).decode()}
    results=[];errors=[]
    def check(label,condition):
        assert condition,label
        results.append({'check':label,'passed':True})
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1480,'height':1080},device_scale_factor=1,accept_downloads=True)
        page.expose_function('backendHTTP',backend);page.on('pageerror',lambda e:errors.append(str(e)))
        html=(ROOT/'lab/static/index.html').read_text();html=re.sub(r'<link[^>]+>','',html);html=re.sub(r'<script.*?</script>','',html,flags=re.S)
        page.set_content(html)
        for f in ('style.css','editor.css'):page.add_style_tag(content=(ROOT/'lab/static'/f).read_text())
        page.add_script_tag(content=BRIDGE)
        for f in ('app.js','editor.js'):page.add_script_tag(content=(ROOT/'lab/static'/f).read_text())
        page.wait_for_function('window.rigEditor&&rigLabTest.state.clip?.frames?.length>0')
        def ev(code):return page.evaluate(code)
        def revision():return ev('rigLabTest.state.p.revision')
        def saved(old):page.wait_for_function(f'rigLabTest.state.p.revision>{old} && !rigLabTest.state.savePromise && !rigEditor.state.busy && !rigLabTest.state.dirty',timeout=15000)
        def at(frame):ev(f'rigLabTest.state.playing=false;rigLabTest.state.frame={frame};rigLabTest.state.clock=0;rigLabTest.render()')
        def canvaspoint(joint,other=None):
            coords=ev(f'({{p:rigLabTest.state.clip.frames[rigLabTest.state.frame].joints.{joint},q:{"rigLabTest.state.clip.frames[rigLabTest.state.frame].joints."+other if other else "null"},c:rigLabTest.state.p.camera}})')
            box=page.locator('#skeleton').bounding_box();p=coords['p'];c=coords['c']
            if coords['q']:p=[(a+b)/2 for a,b in zip(p,coords['q'])]
            return (box['x']+(c['root_x']*768+p[0]*c['pixels_per_unit'])*box['width']/768,
                    box['y']+(c['ground_y']*768-p[1]*c['pixels_per_unit'])*box['height']/768)
        try:
            before=ev('rigLabTest.state.p.id');page.locator('#demo-reset').click();page.wait_for_function(f'rigLabTest.state.p.id!=="{before}"&&rigLabTest.state.clip.project_revision===rigLabTest.state.p.revision');at(0)
            check('editor loads without JS errors and no desktop overflow',not errors and ev('document.documentElement.scrollWidth<=innerWidth'))
            page.locator('[data-tab="rig"]').click();page.locator('#joint-select').select_option('r_shoulder')
            old=ev('structuredClone(rigLabTest.state.p.rig.joints)');rev=revision()
            page.locator('#joint-x').fill(str(old['r_shoulder'][0]+.025));page.locator('#apply-joint').click();saved(rev)
            after=ev('rigLabTest.state.p.rig.joints')
            check('joint edit translates shoulder/elbow/wrist together',all(abs(after[n][0]-old[n][0]-.025)<1e-8 for n in ('r_shoulder','r_elbow','r_wrist')))
            rev=revision();page.locator('#edit-undo').click();saved(rev)
            check('undo restores persisted bind geometry',ev('rigLabTest.state.p.rig.joints.r_wrist')==old['r_wrist'])
            rev=revision();page.locator('#edit-redo').click();saved(rev)
            check('redo reapplies persisted geometry',abs(ev('rigLabTest.state.p.rig.joints.r_wrist[0]')-old['r_wrist'][0]-.025)<1e-8)
            page.locator('#edit-bone').select_option('r_upper_arm');old=ev('structuredClone(rigLabTest.state.p.rig.joints)');rev=revision()
            page.locator('#edit-length').fill('.16');page.locator('#edit-bind-angle').fill('-50');page.locator('#edit-apply-bone').click();saved(rev)
            pts=ev('rigLabTest.state.p.rig.joints')
            check('bone length/angle changes keep descendant forearm length',abs(math.dist(pts['r_shoulder'],pts['r_elbow'])-.16)<1e-8 and abs(math.dist(pts['r_elbow'],pts['r_wrist'])-math.dist(old['r_elbow'],old['r_wrist']))<1e-8)
            rev=revision();page.locator('#approve-rig').click();saved(rev)
            page.locator('#edit-bone').select_option('r_upper_arm');page.locator('#edit-apply-bone').scroll_into_view_if_needed();page.evaluate("document.getElementById('toast').className=''");page.screenshot(path=str(ROOT/'docs/editor-rig.png'),full_page=True)
            page.locator('[data-tab="motion"]').click();rev=revision();page.locator('[data-action="idle"]').click();saved(rev);at(0)
            page.locator('#key-target').select_option('bone:head');page.locator('#edit-key-phase').fill('50');page.locator('#key-angle').fill('25');rev=revision();page.locator('#add-key').click();saved(rev)
            check('FK angle key is saved and solved without changing bone lengths',ev('rigLabTest.state.p.motion.keys[0].target==="bone:head"&&rigLabTest.state.clip.diagnostics.max_bone_error<1e-7'))
            page.locator('[data-edit-key="0"]').click();page.locator('#edit-key-phase').fill('40');page.locator('#key-angle').fill('35');page.locator('#edit-easing').select_option('linear');rev=revision();page.locator('#add-key').click();saved(rev)
            check('existing key can change time value and interpolation without duplication',ev('rigLabTest.state.p.motion.keys.length===1&&rigLabTest.state.p.motion.keys[0].phase===.4&&rigLabTest.state.p.motion.keys[0].angle===35&&rigLabTest.state.p.motion.keys[0].interpolation==="linear"'))
            marker=page.locator('[data-diamond="0"]');marker.scroll_into_view_if_needed();box=marker.bounding_box();lane=marker.locator('..').bounding_box();rev=revision()
            page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down();page.mouse.move(lane['x']+.6*lane['width'],box['y']+box['height']/2,steps=6);page.mouse.up();saved(rev)
            check('dragging a timeline diamond moves the key',abs(ev('rigLabTest.state.p.motion.keys[0].phase')-.6)<.002)
            at(6);rev=revision();page.locator('#edit-copy-key').click();saved(rev)
            check('copy key to another sampled frame',ev('rigLabTest.state.p.motion.keys.length===2'))
            rev=revision();page.locator('#edit-delete-key').click();saved(rev)
            check('delete only the selected key',ev('rigLabTest.state.p.motion.keys.length===1'))
            rev=revision();page.locator('[data-action="walk"]').click();saved(rev)
            check('walk has its own independent tracks',ev('rigLabTest.state.p.motion.keys.length===0'))
            rev=revision();page.locator('[data-action="idle"]').click();saved(rev);at(6)
            check('switching back restores idle edits',ev('rigLabTest.state.p.motion.keys.length===1&&rigLabTest.state.p.motion.keys[0].angle===35'))
            page.locator('#edit-autokey').check();page.locator('#edit-pose-mode').select_option('ik');page.locator('#skeleton').scroll_into_view_if_needed();at(6)
            x,y=canvaspoint('r_wrist');rev=revision();page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+7,y-5,steps=5);page.mouse.up();saved(rev)
            check('canvas IK handle writes a hand target key',ev('rigLabTest.state.p.motion.keys.some(k=>k.target==="r_wrist"&&Math.abs(k.dx)>0)'))
            page.locator('#edit-pose-mode').select_option('fk');at(8);page.locator('#skeleton').scroll_into_view_if_needed()
            x,y=canvaspoint('r_shoulder','r_elbow');sx,sy=canvaspoint('r_shoulder');dx,dy=x-sx,y-sy;angle=.35
            end=(sx+dx*math.cos(angle)-dy*math.sin(angle),sy+dx*math.sin(angle)+dy*math.cos(angle));rev=revision()
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(*end,steps=5);page.mouse.up();saved(rev)
            check('canvas FK drag writes bone rotation track',ev('rigLabTest.state.p.motion.keys.some(k=>k.target==="bone:r_upper_arm"&&Math.abs(k.angle)>5)'))
            page.locator('#key-target').scroll_into_view_if_needed();page.evaluate("document.getElementById('toast').className=''");page.screenshot(path=str(ROOT/'docs/editor-motion.png'),full_page=True)
            page.locator('[data-tab="parts"]').click();part=ev('rigLabTest.state.p.parts.find(p=>p.bone==="weapon").id');page.locator('#part-select').select_option(part)
            rev=revision();page.locator('#edit-back').click();saved(rev)
            check('send selected part to back changes draw commands',ev(f'rigLabTest.state.clip.frames[0].draws[0].id==="{part}"'))
            rev=revision();page.locator('#edit-front').click();saved(rev)
            check('bring selected part forward changes draw commands',ev(f'rigLabTest.state.clip.frames[0].draws.at(-1).id==="{part}"'))
            rev=revision();page.locator(f'[data-layer-toggle="{part}"]').click();saved(rev)
            check('layer visibility affects renderer',ev(f'!rigLabTest.state.clip.frames[0].draws.some(d=>d.id==="{part}")'))
            rev=revision();page.locator(f'[data-layer-toggle="{part}"]').click();saved(rev)
            page.locator('#edit-part-name').fill('法杖 · 编辑验证');page.locator('#part-bone').select_option('l_forearm');rev=revision();page.locator('#apply-part').click();saved(rev)
            check('rename and rebind part while retaining its identity',ev(f'rigLabTest.state.p.parts.find(p=>p.id==="{part}").bone==="l_forearm"&&rigLabTest.state.p.parts.find(p=>p.id==="{part}").name==="法杖 · 编辑验证"'))
            page.locator('#part-bone').select_option('weapon');rev=revision();page.locator('#apply-part').click();saved(rev)
            at(3);rev=revision();page.locator('#edit-layer-record').click();saved(rev)
            at(12);rev=revision();page.locator('#edit-back').click();saved(rev)
            check('layer animation uses step changes at the authored phase',ev(f'rigLabTest.state.clip.frames[0].draws.at(-1).id==="{part}"&&rigLabTest.state.clip.frames[15].draws[0].id==="{part}"&&rigLabTest.state.p.motion.layer_keys.length===28'))
            page.locator('#edit-layer-mode').select_option('base');rows=page.locator('[data-layer-id]');first=rows.nth(0).get_attribute('data-layer-id');second=rows.nth(1).get_attribute('data-layer-id');rev=revision();rows.nth(0).drag_to(rows.nth(1));saved(rev)
            check('drag-and-drop reorders the base layer list',page.locator('[data-layer-id]').nth(0).get_attribute('data-layer-id')==second)
            at(15);page.locator('#edit-layer-mode').select_option('key');page.locator('#edit-layer-mode').scroll_into_view_if_needed();page.evaluate("document.getElementById('toast').className=''");page.screenshot(path=str(ROOT/'docs/editor-layers.png'),full_page=True)
            original_id=ev('rigLabTest.state.p.id');key_count=ev('rigLabTest.state.p.motion.keys.length');layer_count=ev('rigLabTest.state.p.motion.layer_keys.length')
            with page.expect_download(timeout=15000) as down:page.locator('#download-project').click()
            bundle=ROOT/'docs/editor-project.riglab.zip';down.value.save_as(str(bundle))
            page.locator('#load-project').click();page.locator('#file-input').set_input_files(str(bundle));page.wait_for_function(f'rigLabTest.state.p.id!=="{original_id}"&&rigLabTest.state.clip?.project_revision===rigLabTest.state.p.revision')
            check('saved project reopens with keys layers and bindings',ev(f'rigLabTest.state.p.motion.keys.length==={key_count}&&rigLabTest.state.p.motion.layer_keys.length==={layer_count}&&rigLabTest.state.p.parts.some(p=>p.name==="法杖 · 编辑验证")'))
            page.locator('#export-open').click();page.locator('#allow-clipping').check();page.locator('#export-size').select_option('128')
            with page.expect_download(timeout=25000) as down:page.locator('#export-confirm').click()
            target=ROOT/'docs/editor-export.zip';down.value.save_as(str(target))
            import zipfile
            with zipfile.ZipFile(target) as z:
                clip=json.loads(z.read('motion.json'))
                check('actual PNG export includes edited motion/layer metadata',len(clip['motion']['keys'])==key_count and len(clip['motion']['layer_keys'])==layer_count and 'frames/000.png' in z.namelist())
            page.set_viewport_size({'width':390,'height':844});page.locator('[data-tab="parts"]').click();page.evaluate('window.scrollTo(0,0)');page.wait_for_timeout(200)
            check('mobile layer ordering remains visible without horizontal overflow',page.locator('[data-layer-id]').count()==14 and ev('document.documentElement.scrollWidth<=innerWidth') and page.locator('.rail-section').is_visible())
            page.evaluate("document.getElementById('toast').className=''");page.screenshot(path=str(ROOT/'docs/editor-mobile.png'),full_page=True)
            check('no browser runtime errors',not errors)
        finally:
            (ROOT/'docs/editor-browser-results.json').write_text(json.dumps({'mode':'Chromium DOM + real local HTTP bridge (not native browser networking)','checks':results,'page_errors':errors},ensure_ascii=False,indent=2))
            if errors:print('PAGE ERRORS',errors)
            page.evaluate("document.getElementById('toast').className=''");page.screenshot(path=str(ROOT/'docs/editor-test-last.png'),full_page=True)
            browser.close()
    print(json.dumps({'checks':len(results),'passed':len(results),'errors':errors},ensure_ascii=False))

if __name__=='__main__':main()
