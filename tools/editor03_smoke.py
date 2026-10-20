"""Editor 03 Chromium checks over a Python local-HTTP bridge.

The sandbox blocks native browser localhost navigation. This harness does not
alter that policy and is not claimed to be native browser-network E2E testing.
"""
from __future__ import annotations
import argparse,base64,io,json,math,re,sys,zipfile
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from browser_smoke import BRIDGE
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lab.models import Project
from lab.poseclip import pose_frame


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',default='http://127.0.0.1:8020');args=ap.parse_args()
    client=httpx.Client(base_url=args.base,trust_env=False,timeout=35)
    def backend(payload):
        if not payload['url'].startswith('/api/'): raise ValueError('Local API paths only')
        kw={'headers':payload.get('headers',{})}
        if 'form' in payload:
            kw['data']={v['key']:v['value'] for v in payload['form'] if 'b64' not in v}
            files=[(v['key'],(v['name'],base64.b64decode(v['b64']),v['type'])) for v in payload['form'] if 'b64'in v]
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
        page.set_default_timeout(10000);page.expose_function('backendHTTP',backend);page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda d:d.accept())
        html=(ROOT/'lab/static/index.html').read_text();html=re.sub(r'<link[^>]+>','',html);html=re.sub(r'<script.*?</script>','',html,flags=re.S)
        page.set_content(html)
        for f in ('style.css','editor.css','editor03.css','influence-editor.css'):page.add_style_tag(content=(ROOT/'lab/static'/f).read_text())
        page.add_script_tag(content=BRIDGE)
        for f in ('app.js','editor.js','selection.js','template-editor.js','motion-influence.js','influence-editor.js'):page.add_script_tag(content=(ROOT/'lab/static'/f).read_text())
        def ev(code):return page.evaluate(code)
        def rev():return ev('S.p.revision')
        def saved(old):page.wait_for_function(f'S.p.revision>{old}&&!S.savePromise&&!rigEditor.state.busy&&!S.dirty',timeout=20000)
        def goto(u):ev(f'templateEditor.seek({u})')
        def screenshot(name):
            ev("document.getElementById('toast').className='';window.scrollTo(0,0)")
            page.screenshot(path=str(ROOT/'docs'/name),full_page=True)
        def screen(pos,canvas='character'):
            box=page.locator('#'+canvas).bounding_box();scale=min(box['width']/768,box['height']/768)
            return (box['x']+(box['width']-768*scale)/2+pos[0]*scale,box['y']+(box['height']-768*scale)/2+pos[1]*scale)
        findhit=r'''(id)=>{const cmd=drawCommands().find(c=>c.id===id),im=image(cmd.image);const [a,b,c,d,tx,ty]=cmd.matrix;
          for(let y=0;y<im.height;y+=3)for(let x=0;x<im.width;x+=3){const p=[a*(x+.5)+c*(y+.5)+tx,b*(x+.5)+d*(y+.5)+ty];if(p[0]<5||p[1]<5||p[0]>763||p[1]>763)continue;if(partSelection.hitTest(p)[0]===id)return p;}throw Error('No visible target '+id)}'''
        try:
            page.wait_for_function('window.templateEditor&&S.clip?.frames?.length>0')
            before=ev('S.p.id');page.locator('#demo-reset').click();page.wait_for_function(f'S.p.id!=="{before}"&&S.clip?.project_revision===S.p.revision');ev('S.playing=false;S.frame=0;render()')
            check('editor03 starts without errors or horizontal overflow',not errors and ev('document.documentElement.scrollWidth<=innerWidth'))
            orig=ev('structuredClone(S.clip.frames)');old=rev();page.locator('#template-convert').click();saved(old)
            # Legacy regression intentionally selects precision single-pose mode.
            page.locator('#influence-scope').select_option('single')
            page.locator('#influence-scope').select_option('single')
            check('conversion creates editable source poses, not offset tracks',ev('S.p.motion.driver==="keyframes"&&S.p.motion.pose_keys.length===25&&S.p.motion.keys.length===0'))
            new=ev('S.clip.frames')
            check('conversion preserves original rendered sample geometry',all(math.dist(f['joints'][n],g['joints'][n])<1e-9 for f,g in zip(orig,new) for n in f['joints']))
            check('template parameters freeze while playback timing remains editable',page.locator('#stride').is_disabled() and page.locator('#motion-duration').is_enabled())
            page.locator('[data-pose-index="6"]').click();check('clicking source key seeks exact phase',abs(ev('S.previewPhase')-.25)<1e-9)
            old=rev();angle=ev('S.p.motion.pose_keys[6].angles.head');page.locator('#pose-target').select_option('bone:head');page.locator('#pose-angle').fill(str(angle+25));page.locator('#pose-apply').click();saved(old)
            check('absolute local head angle replaces template pose',abs(ev('S.p.motion.pose_keys[6].angles.head')-angle-25)<1e-7 and ev('S.clip.diagnostics.max_bone_error<1e-8'))
            old=rev();page.locator('#pose-easing').select_option('step');page.locator('#pose-save-easing').click();saved(old)
            check('outgoing interpolation edits persist',ev('S.p.motion.pose_keys[6].interpolation==="step"'))
            old=rev();page.locator('#pose-destination').fill('27');page.locator('#pose-move').click();saved(old)
            check('key can move to non-sampled exact time without snapping',abs(ev('S.previewPhase')-.27)<1e-9 and ev('S.p.motion.pose_keys.some(k=>k.phase===.27)'))
            marker=page.locator('[data-pose-index="6"]');marker.scroll_into_view_if_needed();bb=marker.bounding_box();lane=page.locator('#pose-strip').bounding_box();old=rev()
            page.mouse.move(bb['x']+bb['width']/2,bb['y']+bb['height']/2);page.mouse.down();page.mouse.move(lane['x']+lane['width']*.28,bb['y']+bb['height']/2,steps=6);page.mouse.up();saved(old)
            check('dragging a primary-pose diamond moves its actual key',abs(ev('templateEditor.state.selected')-.28)<.002)
            original_keys=ev('JSON.stringify(S.p.motion.pose_keys)');old=rev();page.locator('#pose-destination').fill('0');page.locator('#pose-copy').click();page.wait_for_function('!rigEditor.state.busy')
            check('duplicate destination refuses overwrite and preserves every key',rev()==old and ev('JSON.stringify(S.p.motion.pose_keys)')==original_keys)
            old=rev();page.locator('#pose-destination').fill('30');page.locator('#pose-copy').click();saved(old)
            check('copy preserves complete pose and adds one key',ev('S.p.motion.pose_keys.length===26&&S.p.motion.pose_keys.some(k=>k.phase===.3)'))
            old=rev();page.locator('#pose-delete').click();saved(old);check('delete removes only selected non-boundary pose',ev('S.p.motion.pose_keys.length===25&&!S.p.motion.pose_keys.some(k=>k.phase===.3)'))
            page.locator('#pose-time').fill('33');page.locator('#pose-time').press('Tab');old=rev();page.locator('#pose-insert').click();saved(old)
            check('insert snapshots interpolated pose at arbitrary time',ev('S.p.motion.pose_keys.some(k=>k.phase===.33)'))
            # Compare browser's live FK and interpolation to backend at unbaked times.
            data=ev('cleanProject()');p=Project.model_validate(data)
            consistent=True
            for u in (.137,.271,.333,.777,1.):
                jf=ev(f'templateEditor.frameFromKey(templateEditor.sample({u})).joints')
                pf=pose_frame(p.rig,p.motion,u)['joints']
                consistent &= all(math.dist(jf[n],pf[n])<1e-8 for n in jf)
            check('live browser interpolation matches backend FK including exact closure',consistent)
            # Actual drag on the rendered weapon, not a direct test function edit.
            goto(.5);page.locator('#character').scroll_into_view_if_needed()
            weapon=ev('S.p.parts.find(p=>p.bone==="weapon").id');pos=page.evaluate(findhit,weapon)
            pivot=ev('point(currentFrame().joints.r_wrist)');dx,dy=pos[0]-pivot[0],pos[1]-pivot[1];theta=.24
            to=[pivot[0]+dx*math.cos(theta)-dy*math.sin(theta),pivot[1]+dx*math.sin(theta)+dy*math.cos(theta)]
            a=screen(pos);b=screen(to);old=rev();prior=ev('templateEditor.sample(.5).weapon')
            page.mouse.move(*a);page.mouse.down();page.mouse.move(*b,steps=6)
            check('rendered-part drag previews locally before any save',rev()==old and ev('templateEditor.state.gesture?.moved===true&&Math.abs(templateEditor.state.gesture.key.weapon-templateEditor.state.gesture.original.weapon)>5'))
            page.mouse.up();saved(old)
            check('releasing character FK drag persists only current source pose',abs(ev('templateEditor.sample(.5).weapon')-prior)>5)
            old=rev();page.locator('#edit-undo').click();saved(old);check('undo restores pose content on server',abs(ev('templateEditor.sample(.5).weapon')-prior)<1e-7)
            old=rev();page.locator('#edit-redo').click();saved(old);check('redo reapplies pose edit',abs(ev('templateEditor.sample(.5).weapon')-prior)>5)
            goto(.375);page.locator('#pose-drag-mode').select_option('ik');page.locator('#skeleton').scroll_into_view_if_needed()
            pos=ev('point(currentFrame().joints.r_wrist)');a=screen(pos,'skeleton');old=rev()
            page.mouse.move(*a);page.mouse.down();page.mouse.move(a[0]+8,a[1]-5,steps=4);page.mouse.up();saved(old)
            check('skeleton IK dragging writes full pose and preserves bone lengths',ev('S.clip.diagnostics.max_bone_error<1e-8&&S.p.motion.pose_keys.some(k=>k.phase===.375)'))
            page.locator('[data-pose-index="0"]').click();check('boundary key cannot be deleted or moved',page.locator('#pose-delete').is_disabled() and page.locator('#pose-move').is_disabled())
            page.locator('#pose-target').select_option('bone:head');old=rev();page.locator('#pose-angle').fill('12');page.locator('#pose-apply').click();saved(old)
            check('linked loop endpoints update matching local pose angles',ev('Math.abs(S.p.motion.pose_keys[0].angles.head-S.p.motion.pose_keys.at(-1).angles.head)<1e-8'))
            goto(.5);screenshot('editor03-template.png')
            # Parts panel: list selection, image selection and alpha/overlap behavior.
            page.locator('[data-tab="parts"]').click();page.locator('#character').scroll_into_view_if_needed()
            head=ev('S.p.parts.find(p=>p.bone==="head").id')
            ev('partSelection.select(null)');none=ev('document.getElementById("character").toDataURL()');old=rev()
            page.locator(f'[data-part="{head}"]').click();selected=ev('document.getElementById("character").toDataURL()')
            check('list selection highlights actual rendered silhouette without saving',none!=selected and rev()==old and ev(f'S.selectedPart==="{head}"'))
            page.locator('#selection-highlight').uncheck();check('highlight toggle restores unmodified preview pixels',ev('document.getElementById("character").toDataURL()')==none)
            page.locator('#selection-highlight').check();page.locator('#character').scroll_into_view_if_needed();pos=page.evaluate(findhit,weapon)
            page.mouse.click(*screen(pos));check('clicking rendered alpha selects matching part and list row',ev(f'S.selectedPart==="{weapon}"') and page.locator(f'[data-layer-id="{weapon}"]').get_attribute('aria-selected')=='true')
            page.locator('#view-character').click();page.locator('#character').scroll_into_view_if_needed();large=page.evaluate(findhit,head);page.mouse.click(*screen(large))
            check('large character-only preview uses the same accurate picking',ev(f'S.selectedPart==="{head}"'))
            page.locator('#view-split').click();page.locator('#part-select').select_option(weapon);page.locator('#character').scroll_into_view_if_needed()
            # A sparse sample within a transparent part rectangle must not intercept clicks.
            transparent=ev(r'''(()=>{const cmd=drawCommands().find(c=>c.id===S.selectedPart),im=image(cmd.image),[a,b,c,d,tx,ty]=cmd.matrix;for(const [x,y] of [[0,0],[im.width-1,0],[0,im.height-1],[im.width-1,im.height-1]]){let p=[a*x+c*y+tx,b*x+d*y+ty];if(!partSelection.hitTest(p).includes(cmd.id))return true;}return false})()''')
            check('transparent padding does not steal selection',transparent)
            overlap=ev(r'''(()=>{for(let y=100;y<690;y+=3)for(let x=170;x<650;x+=3){const ids=partSelection.hitTest([x,y]);if(ids.length>1)return {p:[x,y],ids};}return null})()''')
            check('fixture has a genuinely overlapping pair for alpha picking',overlap is not None)
            page.mouse.click(*screen(overlap['p']));first=ev('S.selectedPart');page.keyboard.down('Alt');page.mouse.click(*screen(overlap['p']));page.keyboard.up('Alt')
            check('Alt-click cycles actual overlapping visible parts',first==overlap['ids'][0] and ev('S.selectedPart')==overlap['ids'][1])
            page.locator('#part-select').select_option(head);old=rev();page.locator(f'[data-layer-toggle="{head}"]').click();saved(old)
            check('hidden part remains locatable but is excluded from image hit tests',ev(f'!drawCommands().some(c=>c.id==="{head}")') and '隐藏' in page.locator('#selection-detail').text_content())
            old=rev();page.locator(f'[data-layer-toggle="{head}"]').click();saved(old)
            page.locator('#part-select').select_option(weapon);old=rev();page.locator('#edit-front').click();saved(old)
            check('reordering updates actual frontmost draw command',ev(f'drawCommands().at(-1).id==="{weapon}"'))
            ev('partSelection.state.hover=null;render()');screenshot('editor03-selected.png')
            # Selection is visual-only; exports from the exact same revision match.
            pid=ev('S.p.id');revision=rev();kwargs={'headers':{'X-Rig-Request':'1'},'json':{'expected_revision':revision,'size':64,'allow_clipping':True}}
            data_a=client.post(f'/api/projects/{pid}/export',**kwargs).content
            ev('partSelection.select(null)');data_b=client.post(f'/api/projects/{pid}/export',**kwargs).content
            za=zipfile.ZipFile(io.BytesIO(data_a));zb=zipfile.ZipFile(io.BytesIO(data_b))
            check('selection outline never contaminates exported PNG pixels',za.read('frames/000.png')==zb.read('frames/000.png') and za.read('motion.json')==zb.read('motion.json'))
            (ROOT/'docs/editor03-export.zip').write_bytes(data_a)
            count=ev('S.p.motion.pose_keys.length')
            with page.expect_download(timeout=20000) as download:page.locator('#download-project').click()
            bundle=ROOT/'docs/editor03-project.riglab.zip';download.value.save_as(str(bundle))
            old_id=ev('S.p.id');page.locator('#load-project').click();page.locator('#file-input').set_input_files(str(bundle));page.wait_for_function(f'S.p.id!=="{old_id}"&&S.clip?.project_revision===S.p.revision')
            check('saved project reopens with source keyframes and template backup',ev(f'S.p.motion.driver==="keyframes"&&S.p.motion.pose_keys.length==={count}&&S.p.motion.source_motion.driver==="template"'))
            page.locator('[data-tab="motion"]').click();old=rev();page.locator('[data-action="attack"]').click();saved(old)
            check('other action templates remain independent',ev('S.p.motion.kind==="attack"&&S.p.motion.driver==="template"'))
            old=rev();page.locator('[data-action="walk"]').click();saved(old)
            check('returning to edited action restores its primary keyframes',ev(f'S.p.motion.driver==="keyframes"&&S.p.motion.pose_keys.length==={count}'))
            old=rev();page.locator('#template-restore').click();saved(old)
            check('restore returns to captured parameter template',ev('S.p.motion.driver==="template"&&S.p.motion.pose_keys.length===0'))
            old=rev();page.locator('#edit-undo').click();saved(old)
            check('template restore is undoable',ev('S.p.motion.driver==="keyframes"'))
            page.set_viewport_size({'width':390,'height':844});page.locator('[data-tab="parts"]').click();ev('window.scrollTo(0,0)')
            check('mobile parts list stays accessible with no horizontal overflow',page.locator('[data-layer-id]').count()==14 and ev('document.documentElement.scrollWidth<=innerWidth') and page.locator('.rail-section').is_visible())
            page.locator('#character').scroll_into_view_if_needed();pos=page.evaluate(findhit,head);page.mouse.click(*screen(pos))
            check('scaled mobile canvas picking selects actual pixels',ev(f'S.selectedPart==="{head}"'))
            screenshot('editor03-mobile.png');check('no browser runtime errors',not errors)
        finally:
            (ROOT/'docs/editor03-browser-results.json').write_text(json.dumps({'mode':'Chromium DOM + Python real local HTTP bridge (not native browser networking)','checks':results,'page_errors':errors},ensure_ascii=False,indent=2))
            if errors: print('PAGE ERRORS',errors)
            page.screenshot(path=str(ROOT/'docs/editor03-test-last.png'),full_page=True);browser.close()
    print(json.dumps({'checks':len(results),'passed':len(results),'page_errors':errors},ensure_ascii=False))

if __name__=='__main__':main()
