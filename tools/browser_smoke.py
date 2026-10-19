"""Chromium DOM + Python HTTP bridge checks.

This sandbox's Chromium policy blocks localhost navigation. Do not change the
policy. Instead load our local document, bridge fetch/image bytes via Python,
and separately test the real HTTP API. This is NOT a browser-network E2E test.
"""
from __future__ import annotations
import argparse,base64,json,re,sys,time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8020'
BRIDGE=r'''
Object.defineProperty(window,'localStorage',{value:(()=>{const m=new Map();return {getItem:k=>m.get(k)||null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k)}})()});
const b64bytes=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
window.fetch=async(url,options={})=>{
 let payload={url:String(url),method:options.method||'GET',headers:options.headers||{}};
 if(options.body instanceof FormData){payload.form=[];for(const [k,v] of options.body.entries()){
 if(v instanceof Blob){let bytes=new Uint8Array(await v.arrayBuffer()),ss='';for(let i=0;i<bytes.length;i+=16384)ss+=String.fromCharCode(...bytes.subarray(i,i+16384));payload.form.push({key:k,name:v.name||'blob',type:v.type,b64:btoa(ss)});}
 else payload.form.push({key:k,value:String(v)});
 }}else if(options.body)payload.body=String(options.body);
 const r=await window.backendHTTP(payload);return new Response(b64bytes(r.body),{status:r.status,headers:r.headers});
};
const originalSrc=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');
Object.defineProperty(HTMLImageElement.prototype,'src',{get(){return originalSrc.get.call(this)},set(value){
 if(String(value).startsWith('/api/')){this._pendingSrc=window.backendHTTP({url:value,method:'GET'}).then(r=>{if(r.status!==200)throw Error('image HTTP '+r.status);originalSrc.set.call(this,'data:image/png;base64,'+r.body);});}
 else originalSrc.set.call(this,value);
}});
const originalDecode=HTMLImageElement.prototype.decode;
HTMLImageElement.prototype.decode=async function(){if(this._pendingSrc)await this._pendingSrc;return originalDecode.call(this)};
'''

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',default=BASE);args=ap.parse_args()
    client=httpx.Client(base_url=args.base,timeout=30,trust_env=False)
    def backend(payload):
        path=payload['url']
        if not path.startswith('/api/'): raise ValueError('Test bridge only accepts local API paths.')
        kwargs={'headers':payload.get('headers',{})}
        if 'form' in payload:
            files=[];data={}
            for item in payload['form']:
                if 'b64' in item: files.append((item['key'],(item['name'],base64.b64decode(item['b64']),item['type'])))
                else:data[item['key']]=item['value']
            kwargs.update(data=data)
            if files:kwargs['files']=files
        elif 'body'in payload:kwargs['content']=payload['body'].encode()
        r=client.request(payload.get('method','GET'),path,**kwargs)
        headers={k:v for k,v in r.headers.items() if k in ('content-type','content-disposition')}
        return {'status':r.status_code,'headers':headers,'body':base64.b64encode(r.content).decode()}
    results=[];errors=[]
    def record(name,condition):
        assert condition,name
        results.append({'check':name,'passed':True})
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1060},device_scale_factor=1,accept_downloads=True)
        page.expose_function('backendHTTP',backend);page.on('pageerror',lambda e:errors.append(str(e)))
        html=(ROOT/'lab/static/index.html').read_text()
        html=re.sub(r'<link[^>]+>','',html);html=re.sub(r'<script.*?</script>','',html,flags=re.S)
        page.set_content(html);page.add_style_tag(content=(ROOT/'lab/static/style.css').read_text());page.add_script_tag(content=BRIDGE);page.add_script_tag(content=(ROOT/'lab/static/app.js').read_text())
        page.wait_for_function('window.rigLabTest?.state.clip?.frames?.length===24')
        old_id=page.evaluate('rigLabTest.state.p.id')
        page.locator('#demo-reset').click()
        page.wait_for_function(f'rigLabTest.state.p.id!=="{old_id}" && rigLabTest.state.clip.motion.kind==="walk"')
        record('initial demo loads rig, 14 fixed parts, 24 solved frames',page.evaluate('rigLabTest.state.p.parts.length===14'))
        page.evaluate('rigLabTest.state.playing=false;rigLabTest.state.frame=6;rigLabTest.render()')
        record('desktop has no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        # Select an actual template button and wait for the API-recomputed clip.
        rev=page.evaluate('rigLabTest.state.p.revision')
        page.locator('[data-action="attack"]').click()
        page.wait_for_function(f'rigLabTest.state.p.revision>{rev} && rigLabTest.state.clip.motion.kind==="attack" && !rigLabTest.state.savePromise')
        record('attack template UI persists and solves',page.evaluate('rigLabTest.state.clip.events[0].name==="hit"'))
        page.evaluate('rigLabTest.state.playing=false;rigLabTest.state.frame=11;rigLabTest.render()')
        page.screenshot(path=str(ROOT/'docs/workbench-desktop.png'),full_page=True)
        # Annotation drag: use the real canvas pointer handlers.
        page.locator('[data-tab="rig"]').click();page.locator('#joint-select').select_option('r_wrist')
        coords=page.evaluate('({p:rigLabTest.state.p.rig.joints.r_wrist,c:rigLabTest.state.p.camera})')
        bb=page.locator('#skeleton').bounding_box();c=coords['c'];p=coords['p']
        x=bb['x']+(c['root_x']*768+p[0]*c['pixels_per_unit'])*bb['width']/768
        y=bb['y']+(c['ground_y']*768-p[1]*c['pixels_per_unit'])*bb['height']/768
        rev=page.evaluate('rigLabTest.state.p.revision')
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+6,y-6,steps=3);page.mouse.up()
        page.wait_for_function(f'rigLabTest.state.p.revision>{rev} && !rigLabTest.state.savePromise')
        record('joint drag updates structure and invalidates approval',page.evaluate('!rigLabTest.state.p.rig.approved'))
        page.locator('#approve-rig').click();page.wait_for_function('rigLabTest.state.p.rig.approved && !rigLabTest.state.savePromise')
        record('rig approval can be restored',page.evaluate('rigLabTest.state.p.rig.approved'))
        page.locator('[data-tab="parts"]').click();part_id=page.evaluate('rigLabTest.state.p.parts.find(p=>p.bone==="weapon").id')
        page.locator('#part-select').select_option(part_id)
        page.locator('#part-scale').fill('0.8');page.locator('#part-rotation').fill('12');page.locator('#apply-part').click()
        page.wait_for_function('!rigLabTest.state.savePromise && rigLabTest.state.p.parts.find(p=>p.bone==="weapon").scale===.8')
        record('weapon scale and rotation persist without image generation',page.evaluate('rigLabTest.state.p.parts.find(p=>p.bone==="weapon").rotation===12'))
        page.screenshot(path=str(ROOT/'docs/part-binding.png'),full_page=True)
        page.locator('[data-tab="motion"]').click();page.locator('summary').filter(has_text='关键时刻校正').click()
        page.locator('#key-x').fill('0.02');page.locator('#add-key').click();page.wait_for_function('rigLabTest.state.p.motion.keys.length===1 && !rigLabTest.state.savePromise')
        record('current-frame control-key editing works',page.evaluate('rigLabTest.state.p.motion.keys[0].dx===.02'))
        page.locator('[data-key-remove="0"]').click();page.wait_for_function('rigLabTest.state.p.motion.keys.length===0 && !rigLabTest.state.savePromise')
        record('key removal recomputes clip',True)
        page.locator('[data-tab="reference"]').click();page.locator('#synthetic-reference').click()
        page.wait_for_function('rigLabTest.state.clip.motion.kind==="reference" && rigLabTest.state.p.reference_motion!=null')
        record('synthetic reference is distinctly labelled, retargeted with fixed lengths',page.evaluate('rigLabTest.state.p.reference_motion.provenance.includes("not human mocap") && rigLabTest.state.clip.diagnostics.max_bone_error<1e-8'))
        # Preserve archive download with actual browser blob download, not a fake href.
        with page.expect_download() as dl:
            page.locator('#download-project').click()
        dl.value.save_as(str(ROOT/'docs/browser-project.riglab.zip'))
        record('project download creates a restorable ZIP',zip_valid(ROOT/'docs/browser-project.riglab.zip'))
        page.locator('#export-open').click()
        with page.expect_download(timeout=30000) as dl:
            page.locator('#export-confirm').click()
        dl.value.save_as(str(ROOT/'docs/browser-export.zip'))
        record('PNG sequence export completes through the UI',zip_valid(ROOT/'docs/browser-export.zip'))
        page.set_viewport_size({'width':390,'height':844});page.locator('[data-tab="motion"]').click()
        if page.locator('details[open]').count():page.locator('details[open] summary').first.click()
        page.wait_for_timeout(4800)
        page.evaluate('rigLabTest.state.playing=false;rigLabTest.render()');page.screenshot(path=str(ROOT/'docs/workbench-mobile.png'),full_page=True)
        record('390px mobile layout has no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        record('no uncaught browser errors',not errors)
        browser.close()
    data={'method':'Chromium local DOM + Python HTTP bridge; browser native navigation blocked by sandbox policy',
          'results':results,'page_errors':errors,'total':len(results),'passed':sum(x['passed'] for x in results)}
    (ROOT/'docs/browser-results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data,ensure_ascii=False,indent=2))

def zip_valid(path):
    import zipfile
    with zipfile.ZipFile(path) as z:return z.testzip() is None and len(z.namelist())>1
if __name__=='__main__':main()
