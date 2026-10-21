/* DOM/event/data smoke only. Canvas mocked: not browser or visual QA. */
const fs=require('fs'),path=require('path'),vm=require('vm'),cp=require('child_process'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom');
const py=source=>JSON.parse(cp.execFileSync(path.join(root,'.venv/bin/python'),['-c',source],{cwd:root,encoding:'utf8'}));
const fixture=py(`import json\nfrom lab.main import config\nfrom lab.demo import default_rig\nfrom lab.models import Project,Motion\nfrom lab.poseclip import convert_to_keyframes\nfrom lab.motion import solve_project\np=Project(id='d'*32,name='DOM synthetic',rig=default_rig(),motion=Motion(kind='walk',frames=8))\np.motion=convert_to_keyframes(p)\nprint(json.dumps({'config':config(),'project':p.model_dump(),'clip':solve_project(p)}))`);
let project=fixture.project,clip=fixture.clip;const requests=[],errors=[],checks=[];
const html=fs.readFileSync(path.join(root,'lab/static/index.html'),'utf8');
const scripts=[...html.matchAll(/<script src="\/static\/([^?\"]+)/g)].map(m=>m[1]);
const dom=new JSDOM(html.replace(/<script.*?<\/script>/gs,''),{url:'http://localhost:8020',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,context=dom.getInternalVMContext();
w.structuredClone=structuredClone;w.confirm=()=>true;w.alert=()=>{};w.requestAnimationFrame=()=>1;w.cancelAnimationFrame=()=>{};w.scrollTo=()=>{};
w.ResizeObserver=class{observe(){} disconnect(){}};
w.HTMLCanvasElement.prototype.getContext=function(){return new Proxy({canvas:this,measureText:s=>({width:String(s).length*8}),getImageData:()=>({data:new Uint8ClampedArray(4)}),createLinearGradient:()=>({addColorStop(){}})},{get(t,k){return k in t?t[k]:()=>{};}});};
w.HTMLElement.prototype.setPointerCapture=()=>{};w.HTMLElement.prototype.releasePointerCapture=()=>{};
w.addEventListener('error',e=>errors.push(String(e.error||e.message)));
w.console.error=e=>errors.push(String(e));
function solve(p){const result=cp.spawnSync(path.join(root,'.venv/bin/python'),['-c',`import json,sys\nfrom lab.models import Project\nfrom lab.motion import solve_project\np=Project.model_validate(json.load(sys.stdin));print(json.dumps({'project':p.model_dump(),'clip':solve_project(p)}))`],{cwd:root,input:JSON.stringify(p),encoding:'utf8'});if(result.status)throw Error(result.stderr);return JSON.parse(result.stdout);}
w.fetch=async(url,opt={})=>{requests.push([opt.method||'GET',url]);let payload;
 if(url==='/api/config')payload=fixture.config;
 else if(url==='/api/projects')payload=[{id:project.id,name:project.name}];
 else if(url.endsWith('/solve')){const data=solve(project);clip=data.clip;payload=clip;}
 else if((opt.method||'GET')==='PUT'){const incoming=JSON.parse(opt.body);assert.equal(incoming.expected_revision,project.revision);const data=solve(incoming.project);project=data.project;project.revision++;clip=data.clip;payload=project;}
 else if(url==='/api/projects/'+project.id)payload=project;
 else throw Error('Unexpected mock route '+url);
 return {ok:true,status:200,json:async()=>structuredClone(payload)};
};
for(const s of scripts)vm.runInContext(fs.readFileSync(path.join(root,'lab/static',s),'utf8'),context,{filename:s});
const ev=s=>vm.runInContext(s,context),wait=ms=>new Promise(r=>setTimeout(r,ms));
async function settle(){for(let n=0;n<100;n++){await wait(10);if(ev('!!S.p && !S.savePromise && !rigEditor.state.busy && !S.dirty'))return;}throw Error('DOM did not settle: '+w.document.getElementById('toast').textContent);}
function check(name,condition){assert(condition,name);checks.push(name);}
(async()=>{await settle();ev('S.playing=false;setTab("rig")');check('all scripts boot',errors.length===0);
 w.document.getElementById('rig-style-cartoon').click();w.document.getElementById('rig-template-apply').click();await settle();
 check('cartoon click applies single arms',ev('S.p.rig.limb_modes.r_arm==="single"&&S.p.rig.limb_modes.l_arm==="single"'));
 check('elbows absent from active joint list',!w.document.querySelector('[data-joint="r_elbow"]')&&!w.document.querySelector('[data-joint="l_elbow"]'));
 check('existing baked keys retained without alias conversion',ev('S.p.motion.pose_keys.every(k=>!Object.hasOwn(k.angles,"r_arm"))'));
 ev('setTab("motion");templateEditor.seek(0)');const target=w.document.getElementById('pose-target');target.value='bone:r_arm';target.dispatchEvent(new w.Event('change'));
 check('alias field loads legacy angle',Number.isFinite(Number(w.document.getElementById('pose-angle').value)));
 w.document.getElementById('pose-angle').value=22;w.document.getElementById('pose-apply').click();await settle();
 check('alias numeric update saved',ev('Number.isFinite(S.p.motion.pose_keys[0].angles.r_arm)'));
 check('linked loop aliases equal',ev('Math.abs(S.p.motion.pose_keys[0].angles.r_arm-S.p.motion.pose_keys.at(-1).angles.r_arm)<1e-10'));
 check('all serialized key angles finite',ev('S.p.motion.pose_keys.every(k=>Object.values(k.angles).every(Number.isFinite))'));
 check('backend validation and solve succeeded',requests.filter(r=>r[0]==='PUT').length>=2);
 const legacyBefore=ev('JSON.stringify(S.p.motion.pose_keys.map(k=>Object.fromEntries(Object.entries(k.angles).filter(([n])=>!rigTopology.limbs[n]))))');
 ev('setTab("rig")');w.document.getElementById('rig-style-standard').click();w.document.getElementById('rig-template-apply').click();await settle();
 check('switch back restores standard topology without deleting archived angles',ev('Object.values(S.p.rig.limb_modes).every(v=>v==="two")')&&legacyBefore===ev('JSON.stringify(S.p.motion.pose_keys.map(k=>Object.fromEntries(Object.entries(k.angles).filter(([n])=>!rigTopology.limbs[n]))))'));
 check('no script runtime errors',errors.length===0);
 const report={scope:'jsdom event/data logic; mocked Canvas; Python schema + solver validated each save. Not actual browser visual QA.',checks,requests,errors};fs.writeFileSync(path.join(root,'docs/cartoon-dom-smoke.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));dom.window.close();
})().catch(e=>{console.error(e);console.error('Captured errors:',errors);fs.writeFileSync(path.join(root,'docs/cartoon-dom-smoke.json'),JSON.stringify({scope:'jsdom event/data only; mocked Canvas; not rendered browser QA',checks,requests,errors,failure:String(e)},null,2)+'\n');dom.window.close();process.exitCode=1;});
