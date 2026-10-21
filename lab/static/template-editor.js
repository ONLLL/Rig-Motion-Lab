/* Independent pose-keyframe editor. Keep this FK/interpolation contract in sync
 * with lab/poseclip.py; regression tests compare both implementations. */
(() => {
'use strict';
const T={project:null,kind:null,selected:null,gesture:null,keyDrag:null,target:'bone:r_forearm'};
const clone=x=>structuredClone(x), rad=x=>x*Math.PI/180, deg=x=>x*180/Math.PI;
const finite=(x,label)=>{if(!Number.isFinite(x))throw Error(label+'必须是有限数值');return x;};
const near=(a,b)=>Math.abs(a-b)<1e-6;
const round=x=>Number(x.toFixed(6));
const active=()=>S.p?.motion.driver==='keyframes';
const phase=()=>S.previewPhase??S.clip?.frames[S.frame]?.phase??0;
const parentBone=n=>Object.keys(activeBones()).find(b=>activeBones()[b][1]===activeBones()[n][0]);
const nearestAngle=(value,around)=>around+Math.atan2(Math.sin(rad(value-around)),Math.cos(rad(value-around)))*180/Math.PI;

$('panel-motion').insertAdjacentHTML('afterbegin',`<section class="editor-box pose-source-box">
 <div class="source-heading"><span class="source-mode">TEMPLATE → KEYFRAMES</span><strong id="pose-source-state">编辑模板动作</strong></div>
 <p class="help" id="pose-source-note">先调模板参数，再转换为完整姿势关键帧；直接编辑动作本身，不只是叠加偏移。</p>
 <button id="template-convert" class="primary">将当前模板转为可编辑关键帧</button><button id="template-restore" class="full" hidden>返回原参数模板</button>
 <div id="pose-controls" hidden>
  <label class="check"><input type="checkbox" id="pose-drag-enabled" checked>拖动画布直接调姿</label>
  <label>画布操作<select id="pose-drag-mode"><option value="fk">FK · 点击部件后旋转</option><option value="ik">IK · 拖动手脚目标</option></select></label>
  <label>编辑目标<select id="pose-target"></select></label>
  <div class="two"><label>目标 X<input id="pose-x" type="number" step=".005" min="-10" max="10"></label><label>目标 Y<input id="pose-y" type="number" step=".005" min="-10" max="10"></label></div>
  <label>局部角度 / °<input id="pose-angle" type="number" step="1" min="-7200" max="7200"></label>
  <button id="pose-apply" class="full">应用到当前姿势</button>
  <div class="two"><label>当前时间 / %<input id="pose-time" type="number" min="0" max="100" step=".1"></label><label>到下一姿势<select id="pose-easing"><option value="linear">线性</option><option value="smooth">平滑</option><option value="step">保持 / 阶跃</option></select></label></div>
  <button id="pose-insert" class="full">记录当前完整姿势</button><p id="pose-selected-info"></p>
  <label>移动 / 复制目标时间 / %<input id="pose-destination" type="number" value="50" min="0" max="100" step=".1"></label>
  <div class="pose-k-actions"><button id="pose-move">移动选中帧</button><button id="pose-copy">复制选中帧</button><button id="pose-save-easing">保存插值</button><button id="pose-delete" class="danger">删除选中帧</button></div>
  <label class="check"><input id="pose-link-ends" type="checkbox" checked>链接循环首尾姿势</label>
  <p class="pose-note">左右画布均可编辑。移动时本地预览，松开保存。0% / 100% 边界不可删除；链接首尾不等于自动锁脚。数值是当前姿势，不是叠加偏移量。</p>
 </div></section>`);
$('edit-lanes').insertAdjacentHTML('beforebegin',`<section id="pose-timeline" class="pose-timeline" hidden>
 <div class="pose-track-label"><strong>模板姿势关键帧</strong><small id="pose-count"></small><div><button id="pose-prev" aria-label="上一个姿势">‹</button><button id="pose-next" aria-label="下一个姿势">›</button></div></div>
 <div class="pose-strip" id="pose-strip" aria-label="模板完整姿势时间轴"></div><p class="help">金色菱形是实际动作姿势。点击精确定位，拖动移时；支持插入、复制、删除和局部旋转。</p></section>`);

function sample(u,m=S.p.motion){
 const keys=m.pose_keys;u=Math.min(1,Math.max(0,u));
 if(u<=keys[0].phase)return {...clone(keys[0]),phase:u};
 if(u>=keys.at(-1).phase)return {...clone(keys.at(-1)),phase:u};
 for(let i=0;i<keys.length-1;i++){
  const a=keys[i],b=keys[i+1];if(Math.abs(u-b.phase)<1e-12)return clone(b);
  if(a.phase<=u&&u<b.phase){let t=(u-a.phase)/(b.phase-a.phase);if(a.interpolation==='smooth')t=t*t*(3-2*t);else if(a.interpolation==='step')t=0;
   const lerp=(x,y)=>x+(y-x)*t, k=clone(a);k.phase=u;k.root=a.root.map((v,j)=>lerp(v,b.root[j]));k.travel_x=lerp(a.travel_x,b.travel_x);k.weapon=lerp(a.weapon,b.weapon);
   for(const n of new Set([...Object.keys(a.angles),...Object.keys(b.angles)]))k.angles[n]=lerp(rigTopology.local(a,S.p.rig,n),rigTopology.local(b,S.p.rig,n));
   k.targets={};for(const n of new Set([...Object.keys(a.targets),...Object.keys(b.targets)])){const p=a.targets[n]||b.targets[n],q=b.targets[n]||p;k.targets[n]=n.endsWith('_ankle')&&a.contacts[n[0]]?p.slice():p.map((v,j)=>lerp(v,q[j]));}return k;
  }
 }
 throw Error('没有可采样的姿势');
}
function frameFromKey(k,m=S.p.motion){
 const rig=S.p.rig,{points:pts,angles}=rigTopology.world(k,rig,S.cfg.bones);
 const w=angles.r_forearm+rad(k.weapon);pts.weapon_tip=[pts.r_wrist[0]+rig.weapon_length*Math.cos(w),pts.r_wrist[1]+rig.weapon_length*Math.sin(w)];
 const travel=m.root_mode==='in_place'?k.travel_x:0;
 return {phase:k.phase,time:k.phase*m.duration,joints:Object.fromEntries(Object.entries(pts).map(([n,q])=>[n,[q[0]-travel,q[1]]])),world_joints:pts,
  targets:Object.fromEntries(Object.entries(k.targets).map(([n,q])=>[n,[q[0]-travel,q[1]]])),contacts:clone(k.contacts),contact_ids:clone(k.contact_ids),root_motion:[k.travel_x,k.root[1]],weapon_angle:w,_angles:angles};
}
function previewFrame(){if(!active()||S.tab==='rig'||S.crop)return null;if(T.gesture?.key)return frameFromKey(T.gesture.key);if(S.previewPhase!=null&&!S.playing)return frameFromKey(sample(S.previewPhase));return null;}
function seek(u){finite(u,'时间');if(u<0||u>1)throw Error('时间必须在 0–100%。');S.playing=false;S.clock=0;S.previewPhase=u;S.frame=rigEditor.nearestFrame(u);render();fillFields(true);}
function selectKey(i){const k=S.p.motion.pose_keys[i];if(!k)return;T.selected=k.phase;seek(k.phase);drawTrack();}
function drawTrack(){const track=$('pose-strip');if(!active()||T.keyDrag)return;track.innerHTML=S.p.motion.pose_keys.map((k,i)=>`<button class="pose-diamond ${near(T.selected??-1,k.phase)?'active':''}" data-pose-index="${i}" title="姿势 ${round(k.phase*100)}%" aria-label="姿势 ${round(k.phase*100)}%" style="left:${k.phase*100}%">◆</button>`).join('')+'<i class="pose-playhead"></i>';}
function fillFields(force=false){if(!active())return;const f=currentFrame(),k=T.gesture?.key||sample(phase());const angular=T.target.startsWith('bone:')||T.target==='weapon';
 $('pose-x').disabled=angular;$('pose-y').disabled=angular;$('pose-angle').disabled=!angular;
 const put=(id,v)=>{if(force||document.activeElement!==$(id))$(id).value=v;};
 put('pose-time',round(phase()*100));
 if(angular)put('pose-angle',round(T.target==='weapon'?k.weapon:rigTopology.local(k,S.p.rig,T.target.slice(5))));
 else{const p=f.joints[T.target];if(p){put('pose-x',round(p[0]));put('pose-y',round(p[1]));}}
 const selected=S.p.motion.pose_keys.find(k=>near(k.phase,T.selected??-1));
 $('pose-selected-info').textContent=selected?`已选姿势：${round(selected.phase*100)}% · ${selected.interpolation} · ${S.p.motion.pose_keys.length} 个完整姿势`:`当前 ${round(phase()*100)}% 为插值姿势，可记录为新的关键帧。`;
 $('pose-move').disabled=!selected||selected.phase===0||selected.phase===1;$('pose-copy').disabled=!selected;$('pose-delete').disabled=!selected||selected.phase===0||selected.phase===1;$('pose-save-easing').disabled=!selected;
 if(force)put('pose-easing',selected?.interpolation||k.interpolation||'linear');
}
function sync(){if(!S.p)return;
 if(T.project!==S.p.id||T.kind!==S.p.motion.kind){T.project=S.p.id;T.kind=S.p.motion.kind;T.selected=null;S.previewPhase=null;T.gesture=null;}
 const yes=active();document.body.dataset.motionDriver=yes?'keyframes':'template';
 $('pose-controls').hidden=!yes;$('pose-timeline').hidden=!yes;$('template-restore').hidden=!yes;$('template-convert').hidden=yes;
 $('pose-source-state').textContent=yes?'可编辑关键帧':'编辑模板动作';
 $('pose-source-note').textContent=yes?'当前动作由完整姿势关键帧驱动，参数模板已冻结；时长、采样帧数与相机仍可调整。':'先调整参数，再转换当前模板；保留当前动作的姿势，不再只编辑附加校正点。';
 for(const id of ['stride','lift','stance','amplitude','anticipation','jump-height','reference-bind','reference-gain','smoothing','lock-contacts','apply-reference'])$(id).disabled=yes;
 {if(T.target.startsWith('bone:'))T.target='bone:'+rigTopology.activeBone(S.p.rig,T.target.slice(5));if(T.target.startsWith('bone:')&&!activeBones()[T.target.slice(5)])T.target='pelvis';$('pose-target').innerHTML=['pelvis','r_wrist','l_wrist','r_ankle','l_ankle'].map(n=>`<option value="${n}">IK · ${esc(S.cfg.labels[n])}</option>`).join('')+Object.keys(activeBones()).map(n=>`<option value="bone:${n}">${esc(rigEditor.labelBone[n])} · 局部角度</option>`).join('')+'<option value="weapon">武器 · 相对前臂角度</option>';}
 $('pose-target').value=T.target;
 $('pose-link-ends').checked=S.p.motion.link_loop_ends!==false;$('pose-link-ends').disabled=!['idle','walk'].includes(S.p.motion.kind);
 $('pose-count').textContent=(S.p.motion.pose_keys?.length||0)+' 个姿势 · 本地计算';
 if(yes){$('edit-autokey').checked=$('pose-drag-enabled').checked;drawTrack();fillFields(true);window.influenceEditor?.sync();}
}
function opened(){T.selected=null;T.gesture=null;sync();}
function updateKey(key){
 const m=S.p.motion,keys=m.pose_keys;key.phase=round(key.phase);const i=keys.findIndex(k=>near(k.phase,key.phase));
 if(i>=0)keys[i]=clone(key);else{if(keys.length>=129)throw Error('最多保存 129 个姿势。');keys.push(clone(key));keys.sort((a,b)=>a.phase-b.phase);}
 // Endpoint locomotion and contact metadata are deliberately not copied: a world
 // walking cycle has different travel offsets and ground contact IDs at 100%.
 if(m.link_loop_ends&&['idle','walk'].includes(m.kind)&&(key.phase===0||key.phase===1)){
  const other=keys.find(k=>k.phase===1-key.phase);other.root=key.root.slice();
  for(const n of Object.keys(key.angles))other.angles[n]=nearestAngle(key.angles[n],rigTopology.local(other,S.p.rig,n));other.weapon=nearestAngle(key.weapon,other.weapon);
 }
 T.selected=key.phase;
}
async function saveKey(key){await rigEditor.mutate(()=>updateKey(key));fillFields(true);drawTrack();}
function editKey(k,target,value){
 const f=frameFromKey(k),rig=S.p.rig;
 if(target==='weapon'){k.weapon=finite(value,'角度');return k;}
 if(target.startsWith('bone:')){k.angles[target.slice(5)]=finite(value,'角度');return k;}
 const travel=S.p.motion.root_mode==='in_place'?k.travel_x:0,goal=[finite(value[0],'X')+travel,finite(value[1],'Y')];
 if(target==='pelvis'){k.root[0]+=goal[0]-f.world_joints.pelvis[0];k.root[1]+=goal[1]-f.world_joints.pelvis[1];return k;}
 const limb=target[0]+(target.endsWith('ankle')?'_leg':'_arm');
 if(rigTopology.single(rig,limb)){
  const [root]=activeBones()[limb],a=f.world_joints[root],dx=goal[0]-a[0],dy=goal[1]-a[1],parent=parentBone(limb),theta=Math.hypot(dx,dy)>1e-10?Math.atan2(dy,dx):f._angles[limb];
  k.angles[limb]=nearestAngle(deg(theta-(parent?f._angles[parent]:0)),rigTopology.local(k,rig,limb));k.targets[target]=goal;return k;
 }
 const side=target[0],leg=target.endsWith('ankle'),upper=side+(leg?'_thigh':'_upper_arm'),lower=side+(leg?'_shin':'_forearm'),[root,middle]=S.cfg.bones[upper],end=S.cfg.bones[lower][1];
 const a=f.world_joints[root],L1=Math.hypot(...rig.joints[middle].map((v,i)=>v-rig.joints[root][i])),L2=Math.hypot(...rig.joints[end].map((v,i)=>v-rig.joints[middle][i]));
 let dx=goal[0]-a[0],dy=goal[1]-a[1],distance=Math.hypot(dx,dy);if(distance<1e-10){dx=f.world_joints[end][0]-a[0];dy=f.world_joints[end][1]-a[1];distance=Math.hypot(dx,dy)||1;}
 const ux=dx/distance,uy=dy/distance,d=Math.min(L1+L2-1e-9,Math.max(Math.abs(L1-L2)+1e-9,Math.hypot(goal[0]-a[0],goal[1]-a[1]))),along=(L1*L1-L2*L2+d*d)/(2*d),height=Math.sqrt(Math.max(0,L1*L1-along*along)),bend=rig.bend[side+(leg?'_leg':'_arm')];
 const b=[a[0]+along*ux-bend*height*uy,a[1]+along*uy+bend*height*ux],c=[a[0]+d*ux,a[1]+d*uy],up=Math.atan2(b[1]-a[1],b[0]-a[0]),lo=Math.atan2(c[1]-b[1],c[0]-b[0]),parent=parentBone(upper);
 k.angles[upper]=nearestAngle(deg(up-(parent?f._angles[parent]:0)),k.angles[upper]);k.angles[lower]=nearestAngle(deg(lo-up),k.angles[lower]);k.targets[target]=goal;
 return k;
}

$('template-convert').onclick=safe(async()=>{S.playing=false;await rigEditor.mutate(async()=>{S.p=await json('/api/projects/'+S.p.id+'/motion/convert',{method:'POST',body:{expected_revision:S.p.revision}});S.previewPhase=0;T.selected=0;});$('pose-drag-enabled').checked=true;$('edit-autokey').checked=true;sync();toast('模板已固化。点击金色关键帧后，可在角色上直接修改动作。');});
$('template-restore').onclick=safe(async()=>{if(!confirm('返回转换前的参数模板？当前姿势编辑会移除；层级编辑保留，可用撤销恢复。'))return;await rigEditor.mutate(async()=>{S.p=await json('/api/projects/'+S.p.id+'/motion/restore',{method:'POST',body:{expected_revision:S.p.revision}});S.previewPhase=null;T.selected=null;});sync();});
$('pose-target').onchange=()=>{T.target=$('pose-target').value;fillFields(true);if(T.target.startsWith('bone:')){rigEditor.state.bone=T.target.slice(5);S.selectedJoint=S.cfg.bones[T.target.slice(5)][1];}render();};
$('pose-time').onchange=safe(()=>{const u=num('pose-time')/100;T.selected=S.p.motion.pose_keys.find(k=>near(k.phase,u))?.phase??null;seek(u);drawTrack();});
$('pose-apply').onclick=safe(async()=>{const k=sample(phase()),value=T.target==='weapon'||T.target.startsWith('bone:')?num('pose-angle'):[num('pose-x'),num('pose-y')];if(window.influenceEditor)return influenceEditor.applyNumeric(T.target,value);k.interpolation=$('pose-easing').value;await saveKey(editKey(k,T.target,value));});
$('pose-insert').onclick=safe(()=>{const k=sample(phase());k.interpolation=$('pose-easing').value;return saveKey(k);});
$('pose-save-easing').onclick=safe(()=>rigEditor.mutate(()=>{const k=S.p.motion.pose_keys.find(k=>near(k.phase,T.selected??-1));if(k)k.interpolation=$('pose-easing').value;}));
$('pose-delete').onclick=safe(()=>rigEditor.mutate(()=>{if(T.selected===0||T.selected===1)throw Error('保留首尾边界姿势。');S.p.motion.pose_keys=S.p.motion.pose_keys.filter(k=>!near(k.phase,T.selected??-1));T.selected=null;}));
async function relocate(copy,to=num('pose-destination')/100){
 finite(to,'时间');if(to<0||to>1)throw Error('目标时间必须在 0–100%。');to=round(to);
 await rigEditor.mutate(()=>{const keys=S.p.motion.pose_keys,i=keys.findIndex(k=>near(k.phase,T.selected??-1));if(i<0)throw Error('请先选择一个姿势关键帧。');const src=keys[i];if(!copy&&(src.phase===0||src.phase===1))throw Error('首尾边界不可移动。');
 if(keys.some(k=>near(k.phase,to)))throw Error('目标时间已有姿势，未覆盖任何关键帧。');const dst={...clone(src),phase:to};if(!copy)keys.splice(i,1);updateKey(dst);S.previewPhase=to;S.frame=rigEditor.nearestFrame(to);});
}
$('pose-move').onclick=safe(()=>relocate(false));$('pose-copy').onclick=safe(()=>relocate(true));
$('pose-link-ends').onchange=safe(()=>rigEditor.mutate(()=>{S.p.motion.link_loop_ends=$('pose-link-ends').checked;if(S.p.motion.link_loop_ends)updateKey(clone(S.p.motion.pose_keys[0]));}));
$('pose-drag-enabled').onchange=()=>{$('edit-autokey').checked=$('pose-drag-enabled').checked;S.playing=false;};
$('pose-drag-mode').onchange=()=>{$('edit-pose-mode').value=$('pose-drag-mode').value;S.playing=false;};
for(const [id,sign] of [['pose-prev',-1],['pose-next',1]])$(id).onclick=()=>{const u=phase(),keys=S.p.motion.pose_keys;let i=sign<0?keys.findLastIndex(k=>k.phase<u-1e-6):keys.findIndex(k=>k.phase>u+1e-6);if(i>=0)selectKey(i);};
$('pose-strip').onpointerdown=e=>{const b=e.target.closest('[data-pose-index]');if(!b||rigEditor.state.busy||S.savePromise)return;const i=Number(b.dataset.poseIndex);selectKey(i);T.keyDrag={phase:T.selected,start:e.clientX,rect:$('pose-strip').getBoundingClientRect(),moved:false};$('pose-strip').setPointerCapture(e.pointerId);e.preventDefault();};
$('pose-strip').onpointermove=e=>{const d=T.keyDrag;if(!d||d.phase===0||d.phase===1)return;if(Math.abs(e.clientX-d.start)<4&&!d.moved)return;d.moved=true;d.to=round(Math.min(.999999,Math.max(.000001,(e.clientX-d.rect.left)/d.rect.width)));const i=S.p.motion.pose_keys.findIndex(k=>near(k.phase,d.phase));$('pose-strip').querySelector(`[data-pose-index="${i}"]`).style.left=d.to*100+'%';};
$('pose-strip').onpointerup=safe(async e=>{const d=T.keyDrag;T.keyDrag=null;if($('pose-strip').hasPointerCapture(e.pointerId))$('pose-strip').releasePointerCapture(e.pointerId);try{if(d?.moved)await relocate(false,d.to);}finally{drawTrack();}});
$('pose-strip').onpointercancel=()=>{T.keyDrag=null;drawTrack();};

for(const id of ['skeleton','character']){
 const canvas=$(id),old={down:canvas.onpointerdown,move:canvas.onpointermove,up:canvas.onpointerup,cancel:canvas.onpointercancel};
 canvas.onpointerdown=e=>{
  if(!active()||!['motion','reference'].includes(S.tab)||S.crop||!$('pose-drag-enabled').checked||rigEditor.state.busy||S.savePromise){old.down?.(e);return;}
  S.playing=false;S.clock=0;const pos=mouse(e,canvas),f=currentFrame(),u=phase(),k=sample(u);let part;
  if(id==='character'){const ids=partSelection.hitTest(pos,f),which=e.altKey&&ids.includes(S.selectedPart)?(ids.indexOf(S.selectedPart)+1)%ids.length:0;partSelection.select(ids[which]||null);part=getPart();if(!part)return;}
  let mode=$('pose-drag-mode').value,bone,target;
  if(mode==='fk'){
   bone=part?rigTopology.activeBone(S.p.rig,part.bone):rigEditor.closestBone(pos,f);if(!bone)return;target=bone==='weapon'?'weapon':'bone:'+bone;
  }else{
   target=rigEditor.closestJoint(pos,['r_wrist','l_wrist','r_ankle','l_ankle','pelvis'],f);
   if(!target&&part){const n=part.bone;if(n==='weapon'||n.includes('arm'))target=n==='weapon'?'r_wrist':n[0]+'_wrist';else if(n.includes('thigh')||n.includes('shin')||n.includes('foot')||n.includes('leg'))target=n[0]+'_ankle';else if(n==='spine')target='pelvis';}
   if(!target)return;
  }
  T.target=target;$('pose-target').value=target;const w=world(pos),pivot=mode==='fk'?(bone==='weapon'?f.joints.r_wrist:f.joints[S.cfg.bones[bone][0]]):null;
  T.gesture={canvas:id,mode,bone,target,key:k,original:clone(k),start:w,pivot,startAngle:pivot?Math.atan2(w[1]-pivot[1],w[0]-pivot[0]):0,position:mode==='ik'?f.joints[target].slice():null,moved:false};
  if(window.influenceEditor&&!influenceEditor.beginGesture(T.gesture)){T.gesture=null;return;}
  if(bone&&bone!=='weapon'){rigEditor.state.bone=bone;S.selectedJoint=S.cfg.bones[bone][1];}S.previewPhase=u;canvas.setPointerCapture(e.pointerId);e.preventDefault();render();fillFields(true);
 };
 canvas.onpointermove=e=>{
  const g=T.gesture;if(!g||g.canvas!==id){old.move?.(e);return;}const w=world(mouse(e,canvas));if(Math.hypot(w[0]-g.start[0],w[1]-g.start[1])<.002&&!g.moved)return;g.moved=true;g.key=clone(g.original);
  if(g.mode==='fk'){const a=Math.atan2(w[1]-g.pivot[1],w[0]-g.pivot[0]),delta=deg(Math.atan2(Math.sin(a-g.startAngle),Math.cos(a-g.startAngle)));editKey(g.key,g.target,(g.target==='weapon'?g.original.weapon:rigTopology.local(g.original,S.p.rig,g.bone))+delta);}
  else editKey(g.key,g.target,[g.position[0]+w[0]-g.start[0],g.position[1]+w[1]-g.start[1]]);
  window.influenceEditor?.previewGesture(g,w);render();fillFields(true);
 };
 canvas.onpointerup=safe(async e=>{const g=T.gesture;if(!g||g.canvas!==id){return old.up?.(e);}T.gesture=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);if(g.moved){if(window.influenceEditor)await influenceEditor.commitGesture(g);else{await saveKey(g.key);toast('已修改模板姿势并保存，未调用图片 API。');}}else{render();fillFields(true);}});
 canvas.onpointercancel=e=>{if(T.gesture?.canvas===id){T.gesture=null;render();fillFields(true);}else old.cancel?.(e);};
}
function afterRender(f){if(!active()||S.tab==='rig'||S.crop)return;const line=$('pose-strip').querySelector('.pose-playhead');if(line)line.style.left=f.phase*100+'%';
 $('edit-time').textContent=`${f.time.toFixed(3)}s · ${round(f.phase*100)}% [可编辑]`;
 if(T.gesture){const ctx=$('skeleton').getContext('2d');ctx.save();ctx.fillStyle='#ffd68e';ctx.font='14px sans-serif';ctx.fillText('本地姿势预览 · 松开保存',24,38);ctx.restore();}
 fillFields();window.influenceEditor?.afterRender(f);}
window.templateEditor={state:T,active,sync,opened,previewFrame,afterRender,sample,frameFromKey,selectKey,seek,editKey,saveKey,relocate};
if(S.p)opened();
})();
