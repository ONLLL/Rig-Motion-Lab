"""EDITOR 04 checks: real Chromium pointer/numeric edits over local HTTP bridge.

Chromium cannot navigate localhost in this environment. This harness uses actual
local HTTP via Python, not a claim of native browser-network end-to-end testing.
"""
from __future__ import annotations
import argparse,base64,json,re,zipfile,io,math
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from browser_smoke import BRIDGE
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:8020');args=parser.parse_args()
    client=httpx.Client(base_url=args.base,trust_env=False,timeout=35)
    requests=[];checks=[];errors=[]
    def backend(payload):
        path=payload['url']
        if not path.startswith('/api/'):raise ValueError('Local test paths only')
        requests.append((payload.get('method','GET'),path))
        kw={'headers':payload.get('headers',{})}
        if 'body' in payload:kw['content']=payload['body'].encode()
        if 'form' in payload:
            kw['data']={v['key']:v['value'] for v in payload['form'] if 'b64' not in v}
            files=[(v['key'],(v['name'],base64.b64decode(v['b64']),v['type'])) for v in payload['form'] if 'b64'in v]
            if files:kw['files']=files
        r=client.request(payload.get('method','GET'),path,**kw)
        return {'status':r.status_code,'headers':{k:v for k,v in r.headers.items() if k in ('content-type','content-disposition')},'body':base64.b64encode(r.content).decode()}
    def check(label,condition):
        assert condition,label
        checks.append({'check':label,'passed':True});print('PASS',label)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1512,'height':1040},device_scale_factor=1,accept_downloads=True)
        page.set_default_timeout(15000);page.expose_function('backendHTTP',backend)
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
        html=(ROOT/'lab/static/index.html').read_text()
        scripts=re.findall(r'<script src="/static/([^?\"]+)',html)
        css=re.findall(r'<link[^>]+href="/static/([^?\"]+)',html)
        page.set_content(re.sub(r'<script.*?</script>','',re.sub(r'<link[^>]+>','',html),flags=re.S))
        for f in css:page.add_style_tag(content=(ROOT/'lab/static'/f).read_text())
        page.add_script_tag(content=BRIDGE)
        for f in scripts:page.add_script_tag(content=(ROOT/'lab/static'/f).read_text())
        def ev(s):return page.evaluate(s)
        def rev():return ev('S.p.revision')
        def saved(v):page.wait_for_function(f'S.p.revision>{v}&&!S.savePromise&&!rigEditor.state.busy&&!S.dirty',timeout=20000)
        def put_count():return sum(m=='PUT' for m,_ in requests)
        def seek(t):ev(f'templateEditor.seek({t})')
        def values():return ev('S.p.motion.pose_keys.map(k=>k.angles.head)')
        def close(a,b,tol=1e-7):return len(a)==len(b) and max([abs(x-y) for x,y in zip(a,b)]+[0])<tol
        def screenshot(name):
            ev("S.playing=false;document.getElementById('toast').className='';render();window.scrollTo(0,0)")
            page.wait_for_timeout(300);ev("document.getElementById('toast').style.visibility='hidden'");page.screenshot(path=str(ROOT/'docs'/name),full_page=True);ev("document.getElementById('toast').style.visibility=''")
        def screen(p,canvas='character'):
            r=page.locator('#'+canvas).bounding_box();s=min(r['width']/768,r['height']/768)
            return (r['x']+(r['width']-768*s)/2+p[0]*s,r['y']+(r['height']-768*s)/2+p[1]*s)
        find_hit=r'''id=>{for(const cmd of drawCommands().filter(c=>c.id===id)){const im=image(cmd.image),[a,b,c,d,x0,y0]=cmd.matrix;for(let y=2;y<im.height;y+=3)for(let x=2;x<im.width;x+=3){const q=[a*x+c*y+x0,b*x+d*y+y0];if(q[0]>10&&q[1]>10&&q[0]<758&&q[1]<758&&partSelection.hitTest(q)[0]===id)return q;}}throw Error('No visible hit');}'''
        try:
            page.wait_for_function('window.influenceEditor&&S.clip?.frames?.length>0')
            check('v04 modules and all existing editors load without JS error',not errors and ev('S.cfg.editor_version===4'))
            old_id=ev('S.p.id');page.locator('#demo-reset').click();page.wait_for_function(f'S.p.id!=="{old_id}"&&!S.savePromise&&S.clip?.frames?.length===24')
            page.locator('[data-tab="motion"]').click();ev('S.playing=false')
            old=rev();page.locator('#template-convert').click();saved(old);seek(.5)
            check('default editing scope links nearby poses',page.locator('#influence-scope').input_value()=='nearby')
            before=values();rig=ev('JSON.stringify(S.p.rig)');parts=ev('JSON.stringify(S.p.parts)');camera=ev('JSON.stringify(S.p.camera)')
            page.locator('#pose-target').select_option('bone:head');page.locator('#pose-angle').fill(str(before[12]+20));old=rev();puts=put_count();page.locator('#pose-apply').click();saved(old)
            nearby=values();changed=[i for i,(a,b) in enumerate(zip(before,nearby)) if abs(a-b)>1e-7]
            check('one numeric change affects nine poses instead of just one',len(changed)==9 and close([nearby[12]],[before[12]+20]))
            check('nearby falloff leaves distant keyframes exactly unchanged',changed==list(range(8,17)))
            check('one bulk adjustment performs exactly one project write',put_count()==puts+1)
            check('temporal weight band is drawn behind affected diamonds',page.locator('.influence-band path').count()==1 and page.locator('.pose-diamond.influence-affected').count()==9)
            old=rev();page.locator('#influence-scope').select_option('all')
            check('changing influence controls does not change saved project',rev()==old)
            page.locator('#influence-reapply').click();saved(old);all_values=values()
            check('reapply broadens last edit to the whole action without stacking',close(all_values,[a+20 for a in before]))
            old=rev();page.locator('#influence-strength').fill('50');page.locator('#influence-reapply').click();saved(old)
            check('reapply strength uses pre-edit snapshot, not previous result',close(values(),[a+10 for a in before]))
            old=rev();page.locator('#influence-strength').fill('0');page.locator('#influence-reapply').click();saved(old)
            check('zero-strength reapply restores original poses',close(values(),before))
            old=rev();page.locator('#edit-undo').click();saved(old)
            check('one undo restores the whole preceding batch',close(values(),[a+10 for a in before]))
            old=rev();page.locator('#edit-redo').click();saved(old)
            check('one redo restores the whole batch result',close(values(),before))
            check('scope edits preserve bind rig, textures, camera and layer properties',ev('JSON.stringify(S.p.rig)')==rig and ev('JSON.stringify(S.p.parts)')==parts and ev('JSON.stringify(S.p.camera)')==camera)
            page.locator('#influence-strength').fill('100');page.locator('#influence-scope').select_option('range');page.locator('#influence-start').fill('25');page.locator('#influence-end').fill('75');page.locator('#influence-falloff').select_option('constant')
            page.locator('#pose-angle').fill(str(before[12]+12));old=rev();page.locator('#pose-apply').click();saved(old)
            check('explicit 25–75 percent range changes only keys in that interval',close(values(),[a+(12 if 6<=i<=18 else 0) for i,a in enumerate(before)]))
            page.locator('#influence-start').fill('70')
            check('invalid interval disables apply and displays actionable warning',page.locator('#pose-apply').is_disabled() and '包含当前' in page.locator('#influence-summary').inner_text())
            page.locator('#influence-scope').select_option('nearby');page.locator('#influence-falloff').select_option('smooth')
            # Real character pointer drag: the same requested rotation over multiple pointer moves.
            weapon=ev('S.p.parts.find(p=>p.bone==="weapon").id');page.locator('#pose-drag-mode').select_option('fk')
            page.locator('#character').scroll_into_view_if_needed();q=page.evaluate(find_hit,weapon);pt=screen(q)
            original_motion=ev('JSON.stringify(S.p.motion)');old=rev();puts=put_count()
            page.mouse.move(*pt);page.mouse.down()
            g=ev('({p:templateEditor.state.gesture.pivot,a:templateEditor.state.gesture.startAngle})')
            end=ev(f'point([{g["p"][0]}+Math.cos({g["a"]}+.28)*.16,{g["p"][1]}+Math.sin({g["a"]}+.28)*.16])')
            end=screen(end);page.mouse.move(*end,steps=8)
            check('drag previews locally without saving or cumulatively corrupting poses',rev()==old and ev('JSON.stringify(S.p.motion)')==original_motion)
            expected=ev('templateEditor.state.gesture.influenceResult.motion.pose_keys.map(k=>k.weapon)')
            check('drag plans nearby rather than all motion poses',ev('templateEditor.state.gesture.influenceResult.summary.affected')==9)
            page.mouse.up();saved(old)
            check('character drag commits exact pre-drag delta result once',close(ev('S.p.motion.pose_keys.map(k=>k.weapon)'),expected) and put_count()==puts+1)
            check('character selection and silhouette highlight remain linked',ev(f'S.selectedPart==="{weapon}"') and page.locator('#selection-highlight').is_checked())
            # Real IK drag on the skeleton, no stretching.
            page.locator('#pose-drag-mode').select_option('ik');page.locator('#influence-scope').select_option('all');page.locator('#skeleton').scroll_into_view_if_needed()
            q=ev('point(currentFrame().joints.r_wrist)');pt=screen(q,'skeleton');old=rev();original=ev('JSON.stringify(S.p.motion)')
            page.mouse.move(*pt);page.mouse.down();page.mouse.move(pt[0]+4,pt[1]-3,steps=6)
            expected=ev('templateEditor.state.gesture.influenceResult.motion.pose_keys')
            page.mouse.up();saved(old)
            check('IK drag applies per-pose endpoint delta across full sequence',ev('S.p.motion.pose_keys')==expected)
            check('bulk IK keeps bone lengths and fixed weapon binding',ev('S.clip.diagnostics.max_bone_error<1e-8'))
            # Cancelled pointer gestures never submit.
            page.locator('#skeleton').scroll_into_view_if_needed();pt=screen(ev('point(currentFrame().joints.r_wrist)'),'skeleton')
            old=rev();original=ev('JSON.stringify(S.p.motion)');page.mouse.move(*pt);page.mouse.down();page.mouse.move(pt[0]+7,pt[1]-4,steps=4)
            page.locator('#skeleton').dispatch_event('pointercancel',{'pointerId':1});page.mouse.up()
            check('cancelled proportional drag leaves motion and revision intact',rev()==old and ev('JSON.stringify(S.p.motion)')==original)
            # Fine edit remains opt-in, one mid-cycle pose.
            page.locator('#influence-scope').select_option('single');page.locator('#pose-target').select_option('bone:head')
            prior=values();page.locator('#pose-angle').fill(str(prior[12]+8));old=rev();page.locator('#pose-apply').click();saved(old)
            check('single-pose precision mode still changes only one key',sum(abs(a-b)>1e-7 for a,b in zip(prior,values()))==1)
            # Endpoint temporal wrap keeps travel intact.
            page.locator('#influence-scope').select_option('nearby');seek(0);prior=values();travel=ev('S.p.motion.pose_keys.map(k=>k.travel_x)')
            page.locator('#pose-angle').fill(str(prior[0]+6));old=rev();page.locator('#pose-apply').click();saved(old)
            check('loop influence crosses the end seam with equal endpoint delta',abs(values()[0]-prior[0]-6)<1e-7 and abs(values()[-1]-prior[-1]-6)<1e-7 and abs(values()[-2]-prior[-2])>1e-4)
            check('loop handling preserves root locomotion for all keys',close(ev('S.p.motion.pose_keys.map(k=>k.travel_x)'),travel))
            # Switching actions is not permitted to overwrite earlier action edits.
            walk=ev('JSON.stringify(S.p.motion)');old=rev();page.locator('[data-action="attack"]').click();saved(old)
            check('switching action keeps independent editable walk in library',ev('JSON.stringify(S.p.motion_library.walk)')==walk and not ev('templateEditor.active()'))
            old=rev();page.locator('[data-action="walk"]').click();saved(old)
            check('edited walk reopens with all temporal edits intact',ev('JSON.stringify(S.p.motion)')==walk)
            check('reapply guard refuses after intervening project changes',page.locator('#influence-reapply').is_disabled())
            seek(.5);page.locator('#influence-scope').select_option('nearby');page.locator('#influence-radius').fill('30');page.locator('#pose-target').select_option('bone:r_upper_arm')
            ev("document.querySelector('.inspector').scrollTop=document.querySelector('.influence-box').offsetTop-35")
            screenshot('editor04-influence.png')
            # Save/export is still normal project data, no new format or magic UI state.
            with page.expect_download() as dl:page.locator('#download-project').click()
            archive=ROOT/'docs/editor04-project.riglab.zip';dl.value.save_as(str(archive))
            z=zipfile.ZipFile(archive);data=json.loads(z.read('project.json'));expected=ev('S.p.motion')
            check('saved project archive stores all modified pose keys',data['motion']==expected)
            page.locator('#export-open').click();page.locator('#export-size').select_option('128');page.locator('#allow-clipping').check()
            with page.expect_download(timeout=30000) as dl:page.locator('#export-confirm').click()
            export=ROOT/'docs/editor04-export.zip';dl.value.save_as(str(export));z=zipfile.ZipFile(export)
            check('export contains usable PNG frames and motion after batch editing',z.testzip() is None and 'frames/000.png' in z.namelist() and 'motion.json' in z.namelist())
            page.set_viewport_size({'width':390,'height':844});page.locator('[data-tab="motion"]').click();page.locator('#influence-scope').scroll_into_view_if_needed()
            check('390px editor has no horizontal overflow',ev('document.documentElement.scrollWidth<=innerWidth'))
            page.locator('#influence-scope').select_option('all');page.locator('#pose-target').select_option('bone:head');seek(.5);a=values();old=rev();page.locator('#pose-angle').fill(str(a[12]+3));page.locator('#pose-apply').click();saved(old)
            check('mobile numeric all-motion editing changes every key',close(values(),[v+3 for v in a]))
            screenshot('editor04-mobile.png');check('no unhandled browser runtime exceptions',not errors)
        except Exception:
            print('BROWSER ERRORS',errors);print('TOAST',page.locator('#toast').inner_text());page.screenshot(path=str(ROOT/'docs/editor04-test-last.png'),full_page=True);raise
        finally:browser.close()
    report={'method':'Chromium local DOM + Python actual localhost HTTP bridge (native localhost navigation blocked)',
            'passed':len(checks),'results':checks,'errors':errors,'image_api_calls':0}
    (ROOT/'docs/editor04-browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(len(checks),'browser checks passed')

if __name__=='__main__':main()
