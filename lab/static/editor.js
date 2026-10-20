/* Rig Motion Lab 0.2 — explicit bind-pose, motion-track and draw-order editor.
 * The biped topology stays fixed. These controls never call an image model.
 */
(() => {
'use strict';
const E={bone:'r_forearm',selected:null,history:[],index:-1,project:null,suppress:false,busy:false,
    gesture:null,layerMode:'base',lastFrame:-1,restMode:'move',dragLayer:null};
const labelBone={spine:'躯干',neck:'颈部',head:'头部',l_clavicle:'左肩带',r_clavicle:'右肩带',
 l_upper_arm:'左上臂',r_upper_arm:'右上臂',l_forearm:'左前臂',r_forearm:'右前臂',
 l_pelvis:'左髋连接',r_pelvis:'右髋连接',l_thigh:'左大腿',r_thigh:'右大腿',
 l_shin:'左小腿',r_shin:'右小腿',l_foot:'左脚',r_foot:'右脚'};
const positional=['pelvis','l_wrist','r_wrist','l_ankle','r_ankle'];
const phase=()=>S.previewPhase??S.clip?.frames[S.frame]?.phase??0;
const rnd=x=>Number(x.toFixed(6));
const phaseEqual=(a,b)=>Math.abs(a-b)<1e-6;
const wrap=x=>Math.atan2(Math.sin(x),Math.cos(x));
const trackLabel=t=>t.startsWith('bone:')?'FK · '+(labelBone[t.slice(5)]||t):t==='weapon'?'武器角度':S.cfg?.labels[t]||t;
function descendants(j){const names=[j];for(let i=0;i<names.length;i++)for(const [a,b] of Object.values(S.cfg.bones))if(a===names[i])names.push(b);return names;}
function rotate(p,o,a){const c=Math.cos(a),s=Math.sin(a),x=p[0]-o[0],y=p[1]-o[1];return [o[0]+c*x-s*y,o[1]+s*x+c*y];}
function moveJoint(rig,j,to,cascade){const old=rig.joints[j],d=[to[0]-old[0],to[1]-old[1]];for(const n of cascade?descendants(j):[j])rig.joints[n]=rig.joints[n].map((v,i)=>v+d[i]);rig.approved=false;}
function boneTransform(rig,bone,length,degrees,cascade){const [a,b]=S.cfg.bones[bone],origin=rig.joints[a],old=rig.joints[b],theta=degrees*Math.PI/180;
 const end=[origin[0]+length*Math.cos(theta),origin[1]+length*Math.sin(theta)],delta=theta-Math.atan2(old[1]-origin[1],old[0]-origin[0]);
 for(const n of cascade?descendants(b):[b]){const q=rotate(rig.joints[n],old,delta);rig.joints[n]=[q[0]+end[0]-old[0],q[1]+end[1]-old[1]];}rig.approved=false;}
function evaluated(target,u,m=S.p.motion){const keys=m.keys.filter(k=>k.target===target).sort((a,b)=>a.phase-b.phase).map(k=>({...k}));
 if(!keys.length)return [0,0,0];if(keys[0].phase>0)keys.unshift({phase:0,dx:0,dy:0,angle:0,interpolation:'smooth'});if(keys.at(-1).phase<1)keys.push({phase:1,dx:0,dy:0,angle:0});
 if(u<=keys[0].phase)return [keys[0].dx,keys[0].dy,keys[0].angle];
 for(let i=0;i<keys.length-1;i++){const a=keys[i],b=keys[i+1];if(u<=b.phase){let f=(u-a.phase)/(b.phase-a.phase);if(a.interpolation==='step')f=u===b.phase?1:0;else if(!a.interpolation||a.interpolation==='smooth')f=f*f*(3-2*f);return ['dx','dy','angle'].map(k=>(a[k]||0)+((b[k]||0)-(a[k]||0))*f);}}
 return [keys.at(-1).dx,keys.at(-1).dy,keys.at(-1).angle];}
function effectiveLayers(u=phase()){const map=new Map();for(const k of [...(S.p.motion.layer_keys||[])].sort((a,b)=>a.phase-b.phase))if(k.phase<=u+1e-9)map.set(k.part_id,k);
 return S.p.parts.map((p,i)=>({...p,_index:i,z:map.get(p.id)?.z??p.z,visible:map.get(p.id)?.visible??p.visible})).sort((a,b)=>b.z-a.z||b._index-a._index);}
function snapshot(p){const x=structuredClone(p);delete x.revision;delete x.asset_prefix;x.motion_library=x.motion_library||{};x.motion_library[x.motion.kind]=structuredClone(x.motion);return x;}
function record(p){if(E.suppress)return;const snap=snapshot(p),text=JSON.stringify(snap);if(E.history[E.index]?.text===text)return;
 E.history=E.history.slice(0,E.index+1);E.history.push({text,snap});if(E.history.length>24)E.history.shift();E.index=E.history.length-1;buttons();}
function buttons(){if(!$('edit-undo'))return;$('edit-undo').disabled=E.busy||!!S.savePromise||E.index<=0;$('edit-redo').disabled=E.busy||!!S.savePromise||E.index>=E.history.length-1;$('edit-history').textContent=E.index<0?'本地编辑':`${E.index} 次可撤销`;
 $('edit-delete-key').disabled=!E.selected;$('edit-copy-key').disabled=!E.selected;}
async function mutate(fn){if(E.busy||S.savePromise)return toast('正在保存，请稍候再编辑。',true);const before=cleanProject();E.busy=true;document.body.classList.add('editor-busy');
 try{await fn();dirty();await commit();syncUI();render();}catch(e){
   // Reload the actual revision after a failed write/solve; never force-overwrite.
   try{const p=await json('/api/projects/'+before.id);S.p=p;S.dirty=false;await loadImages();S.clip=await json('/api/projects/'+p.id+'/solve',{method:'POST'});if(/工程已更新|工程版本/.test(e.message)){E.history=[];E.index=-1;const previous=E.suppress;E.suppress=false;record(p);E.suppress=previous;}syncUI();render();}catch{S.p=before;S.dirty=true;}
   throw e;
 }finally{E.busy=false;document.body.classList.remove('editor-busy');buttons();}}
async function historyMove(delta){if(E.busy||S.savePromise)return;const to=E.index+delta;if(to<0||to>=E.history.length)return;
 E.suppress=true;try{await mutate(()=>{const rev=S.p.revision;S.p={...structuredClone(E.history[to].snap),revision:rev,asset_prefix:S.p.asset_prefix};E.selected=null;});E.index=to;toast(delta<0?'已撤销并保存':'已重做并保存');}finally{E.suppress=false;buttons();}}
function opened(p){if(E.project!==p.id){E.project=p.id;E.history=[];E.index=-1;E.selected=null;hitCache.clear();}record(p);sync();}
function saved(p){record(p);drawKeys();syncRig();syncPart();}
async function changeAction(kind){if(E.busy||S.savePromise)return;
 if(kind==='reference'&&!S.p.reference_motion){$('motion-kind').value=S.p.motion.kind;throw Error('请先导入参考轨迹；当前动作不会被覆盖。');}
 if(kind===S.p.motion.kind)return;
 await mutate(()=>{S.p.motion_library=S.p.motion_library||{};S.p.motion_library[S.p.motion.kind]=structuredClone(S.p.motion);
 S.p.motion=structuredClone(S.p.motion_library[kind]||{...S.cfg.motion_default,kind});S.frame=0;S.previewPhase=null;S.clock=0;E.selected=null;});
 toast(`已切换到${actionNames[kind]}，各动作参数与关键帧独立保存。`);}

// UI additions use the same persisted project/lease as the existing workbench.
$('save-button').insertAdjacentHTML('beforebegin',`<button id="edit-undo" title="撤销 Ctrl+Z">↶ 撤销</button><button id="edit-redo" title="重做 Ctrl+Shift+Z">↷</button>`);
$('panel-rig').querySelector('#approve-rig').insertAdjacentHTML('beforebegin',`
 <div class="editor-box"><h3>骨骼结构编辑</h3><label>选中骨骼<select id="edit-bone"></select></label><p id="edit-parent" class="help"></p>
 <div class="two"><label>骨长 / 身高单位<input id="edit-length" type="number" min=".008" max="2" step=".005"></label><label>世界角度 / °<input id="edit-bind-angle" type="number" min="-360" max="360" step="1"></label></div>
 <label class="check"><input id="edit-cascade" type="checkbox" checked> 联动后代，保持下游连接和骨长</label>
 <label>画布操作<select id="edit-rest-mode"><option value="move">移动关节</option><option value="rotate">旋转选中骨骼（拖动末端）</option></select></label>
 <button id="edit-apply-bone" class="full">应用骨长与角度</button>
 <label>武器长度<input id="edit-weapon-length" type="number" min=".03" max="1.2" step=".01"></label><button id="edit-apply-weapon" class="full">应用武器长度</button>
 <p class="help">修改的是初始结构，不是某一帧。模板仍使用固定双足拓扑，暂不增删／重挂语义关节；修改后须重新确认骨架。</p></div>`);
$('panel-motion').querySelector('details').open=true;
$('panel-motion').querySelector('details summary').textContent='关键帧编辑 · IK / FK';
$('panel-motion').querySelector('details .help').textContent='选择时间与轨道，修改已有关键帧或新增。FK 角度在 IK 后应用，可能改变脚部接触；具体误差会重新计算。';
$('key-target').closest('label').insertAdjacentHTML('beforebegin',`<div class="two"><label>时间 / %<input id="edit-key-phase" type="number" min="0" max="100" step=".1" value="0"></label><label>到下一关键帧<select id="edit-easing"><option value="smooth">平滑</option><option value="linear">线性</option><option value="step">保持 / 阶跃</option></select></label></div>`);
$('add-key').textContent='新增 / 更新关键帧';
$('add-key').insertAdjacentHTML('afterend',`<div class="two editor-key-actions"><button id="edit-copy-key">复制到当前帧</button><button id="edit-delete-key" class="danger">删除选中</button></div><button id="edit-new-key" class="text-button">取消选择，编辑当前时间 →</button>`);
$('panel-motion').insertAdjacentHTML('afterbegin',`<div class="editor-box"><strong>参数模板 · 可选叠加校正</strong><p class="help">切换动作不清除关键帧。暂停后打开「画布调姿」，拖动手脚目标，或选择 FK 骨骼旋转。</p><label>命中时刻 / %（斩击）<input id="edit-hit-phase" type="number" min="20" max="90" step="1"></label><button id="edit-apply-hit" class="full">调整挥击时刻</button></div>`);
$('part-select').closest('label').insertAdjacentHTML('afterend',`<label>部件名称<input id="edit-part-name" maxlength="60" aria-label="部件名称"></label>`);
$('panel-parts').insertAdjacentHTML('afterbegin',`<div class="editor-box"><h3>部件前后层级</h3><p class="help">左侧从前到后排列。拖动条目或用上下按钮调整；绑定骨骼与绘制层级是两个独立设置。</p><label>层级编辑范围<select id="edit-layer-mode"><option value="base">初始层级（全动作基准）</option><option value="key">当前动作 / 当前时刻</option></select></label>
 <div class="two"><button id="edit-front">置于最前</button><button id="edit-back">置于最后</button></div>
 <button id="edit-layer-record" class="full">在当前时间记录全部层级</button><button id="edit-layer-clear" class="text-button danger">删除当前时间的层级关键帧</button><p id="edit-layer-state" class="help"></p><div id="edit-layer-keys"></div></div>`);
$('timeline').closest('.playback').insertAdjacentHTML('afterend',`
 <section class="editor-timeline" aria-label="关键帧时间轴"><div class="editor-toolbar"><div><strong>关键帧轨道</strong> <span id="edit-time" class="mono">0.00s</span> <span id="edit-history"></span></div>
 <div class="editor-tools"><label class="check"><input id="edit-autokey" type="checkbox">画布调姿 / 松开写入关键帧</label><select id="edit-pose-mode" aria-label="画布调姿模式"><option value="ik">IK 手脚目标</option><option value="fk">FK 骨骼角度</option></select></div></div>
 <div class="editor-track-head"><select id="edit-track-filter" aria-label="筛选关键帧轨道"><option value="all">全部轨道</option></select><button id="edit-prev-key">‹ 上个关键帧</button><button id="edit-next-key">下个关键帧 ›</button></div>
 <div id="edit-lanes"><div class="edit-lane"><span>IK 位置</span><div data-lane="ik" class="edit-strip"></div></div><div class="edit-lane"><span>FK 角度</span><div data-lane="fk" class="edit-strip"></div></div><div class="edit-lane"><span>遮挡层级</span><div data-lane="layer" class="edit-strip"></div></div></div>
 <p class="help">点击菱形选中，拖动调整时间；在右侧编辑数值、插值或删除。帧间渲染只采样曲线，不产生图片 API 请求。</p></section>`);
function sync(){if(!S.p||!S.cfg)return;
 const boneOptions=Object.keys(S.cfg.bones).map(b=>`<option value="${b}">${esc(labelBone[b]||b)}</option>`).join('');
 if(!$('edit-bone').options.length){$('edit-bone').innerHTML=boneOptions;$('key-target').insertAdjacentHTML('beforeend',Object.keys(S.cfg.bones).map(b=>`<option value="bone:${b}">FK · ${esc(labelBone[b]||b)}</option>`).join(''));
 $('edit-track-filter').insertAdjacentHTML('beforeend',[...positional,'weapon',...Object.keys(S.cfg.bones).map(b=>'bone:'+b)].map(t=>`<option value="${t}">${esc(trackLabel(t))}</option>`).join(''));}
 $('edit-hit-phase').value=rnd(S.p.motion.hit_phase*100);$('edit-hit-phase').disabled=S.p.motion.kind!=='attack';$('edit-apply-hit').disabled=S.p.motion.kind!=='attack';
 syncRig();syncPart();drawKeys();updateFields();buttons();}
function syncRig(){if(!S.p||!$('edit-bone'))return;const incoming=Object.entries(S.cfg.bones).find(([,ab])=>ab[1]===S.selectedJoint);
 if(incoming)E.bone=incoming[0];$('edit-bone').value=E.bone;const [a,b]=S.cfg.bones[E.bone],p=S.p.rig.joints[a],q=S.p.rig.joints[b];
 $('edit-length').value=Math.hypot(q[0]-p[0],q[1]-p[1]).toFixed(5);$('edit-bind-angle').value=(Math.atan2(q[1]-p[1],q[0]-p[0])*180/Math.PI).toFixed(2);
 $('edit-parent').textContent=`${S.cfg.labels[a]} → ${S.cfg.labels[b]} · ${E.bone}`;$('edit-weapon-length').value=S.p.rig.weapon_length;}
function syncPart(){const p=getPart();if(!p||!$('edit-part-name'))return;$('edit-part-name').value=p.name;
 const effective=E.layerMode==='key'?effectiveLayers().find(v=>v.id===p.id):p;$('part-z').value=effective.z;$('part-visible').checked=effective.visible;layerKeyList();}
function updateFields(){const angular=$('key-target').value.startsWith('bone:')||$('key-target').value==='weapon';$('key-x').disabled=angular;$('key-y').disabled=angular;$('key-angle').disabled=!angular;}
function selectKey(index){const k=S.p.motion.keys[index];if(!k)return;E.selected={phase:k.phase,target:k.target};S.playing=false;S.clock=0;S.frame=nearestFrame(k.phase);
 $('key-target').value=k.target;$('edit-key-phase').value=rnd(k.phase*100);$('key-x').value=k.dx;$('key-y').value=k.dy;$('key-angle').value=k.angle;$('edit-easing').value=k.interpolation||'smooth';
 if(k.target.startsWith('bone:')){E.bone=k.target.slice(5);S.selectedJoint=S.cfg.bones[E.bone][1];}
 $('panel-motion').querySelector('details').open=true;updateFields();drawKeys();render();}
function nearestFrame(u){return S.clip.frames.reduce((best,f,i)=>Math.abs(f.phase-u)<Math.abs(S.clip.frames[best].phase-u)?i:best,0);}
function keyFromFields(){const t=$('key-target').value,angular=t.startsWith('bone:')||t==='weapon';return {phase:rnd(num('edit-key-phase')/100),target:t,dx:angular?0:num('key-x'),dy:angular?0:num('key-y'),angle:angular?num('key-angle'):0,interpolation:$('edit-easing').value};}
function upsert(k,old=null){if(k.phase<0||k.phase>1)throw Error('关键帧时间必须在 0–100%。');
 if(Math.abs(k.dx)>.6||Math.abs(k.dy)>.6||Math.abs(k.angle)>180)throw Error('偏移须在 ±0.6、角度在 ±180° 内。');
 let keys=S.p.motion.keys;const oldIndex=old?keys.findIndex(v=>v.target===old.target&&phaseEqual(v.phase,old.phase)):-1;
 const conflict=keys.findIndex(v=>v.target===k.target&&phaseEqual(v.phase,k.phase));
 if(conflict>=0&&oldIndex>=0&&conflict!==oldIndex)throw Error('目标时间已有同轨道关键帧，请先删除或换个时间。');
 if(oldIndex>=0)keys.splice(oldIndex,1);else if(conflict>=0)keys.splice(conflict,1);
 keys.push(k);keys.sort((a,b)=>a.phase-b.phase||a.target.localeCompare(b.target));E.selected={phase:k.phase,target:k.target};}
function drawKeys(){if(!S.p||!$('edit-lanes'))return;const filter=$('edit-track-filter').value;
 $('keys-list').innerHTML=S.p.motion.keys.map((k,i)=>`<div class="editor-key-row ${E.selected?.target===k.target&&phaseEqual(E.selected.phase,k.phase)?'active':''}"><button data-edit-key="${i}">${esc(trackLabel(k.target))}<small>${rnd(k.phase*100)}% · ${esc(k.interpolation||'smooth')}</small></button><button data-edit-remove="${i}" aria-label="删除关键帧">×</button></div>`).join('')||'<p class="help">无校正关键帧，正在使用动作模板。</p>';
 for(const lane of $('edit-lanes').querySelectorAll('[data-lane]')){let html='<i class="edit-playhead"></i>';
 if(lane.dataset.lane!=='layer')S.p.motion.keys.forEach((k,i)=>{const group=k.target.startsWith('bone:')||k.target==='weapon'?'fk':'ik';if(group!==lane.dataset.lane||(filter!=='all'&&filter!==k.target))return;
 html+=`<button class="edit-diamond ${E.selected?.target===k.target&&phaseEqual(E.selected.phase,k.phase)?'active':''}" data-diamond="${i}" style="left:${k.phase*100}%" title="${esc(trackLabel(k.target))} · ${rnd(k.phase*100)}%" aria-label="${esc(trackLabel(k.target))} ${rnd(k.phase*100)}%">◆</button>`;});
 else for(const u of [...new Set((S.p.motion.layer_keys||[]).map(k=>k.phase))])html+=`<button class="edit-diamond layer" data-layer-phase="${u}" style="left:${u*100}%" title="遮挡层级 ${rnd(u*100)}%">◆</button>`;
 lane.innerHTML=html;}
 buttons();updateCursor();layerKeyList();}
function updateCursor(){if(!S.clip||!$('edit-time'))return;$('edit-time').textContent=`${(phase()*S.p.motion.duration).toFixed(2)}s · ${rnd(phase()*100)}%`;
 for(const el of document.querySelectorAll('.edit-playhead'))el.style.left=(phase()*100)+'%';
 if(E.lastFrame!==S.frame){E.lastFrame=S.frame;if(!E.selected)$('edit-key-phase').value=rnd(phase()*100);if(S.tab==='parts')afterList();}}
function layerKeyList(){if(!$('edit-layer-state')||!S.p)return;const keys=S.p.motion.layer_keys||[];
 $('edit-layer-state').textContent=`当前 ${rnd(phase()*100)}% · ${E.layerMode==='base'?'编辑全局基准（可能被动作关键帧覆盖）':'编辑本动作的遮挡关键帧'} · ${keys.length} 条部件记录`;
 const phases=[...new Set(keys.map(k=>k.phase))].sort((a,b)=>a-b);
 $('edit-layer-keys').innerHTML=phases.map(u=>`<div class="layer-key-row"><button data-layer-seek="${u}">${rnd(u*100)}% · ${keys.filter(k=>k.phase===u).length} 件</button><button data-layer-delete="${u}" aria-label="删除这一时刻的层级记录">×</button></div>`).join('');}
function afterList(){if(!S.p)return;
 if(S.tab==='rig'){const parent=Object.fromEntries(Object.values(S.cfg.bones).map(([a,b])=>[b,a]));const depth=j=>parent[j]?1+depth(parent[j]):0;
 $('list-title').textContent='骨骼结构 · 固定拓扑';$('side-list').innerHTML=descendants('pelvis').map(j=>`<button class="side-item rig-tree-item ${S.selectedJoint===j?'active':''}" data-joint="${j}" style="padding-left:${5+depth(j)*8}px"><span>${depth(j)?'└ ':''}${esc(S.cfg.labels[j])}</span><small>${depth(j)?'子关节':'根'}</small></button>`).join('');return;}
 if(S.tab!=='parts')return;$('list-title').textContent='部件层级 · 前 → 后';
 const rows=E.layerMode==='key'?effectiveLayers():S.p.parts.map((p,i)=>({...p,_index:i})).sort((a,b)=>b.z-a.z||b._index-a._index);
 $('side-list').innerHTML=rows.map((p,i)=>`<div class="layer-row ${p.id===S.selectedPart?'active':''}" data-layer-id="${esc(p.id)}" draggable="true"><button data-layer-toggle="${esc(p.id)}" class="layer-eye" aria-label="${p.visible?'隐藏':'显示'} ${esc(p.name)}">${p.visible?'●':'○'}</button><button data-part="${esc(p.id)}" class="layer-name"><span>${esc(p.name)}</span><small>${esc(p.bone==='weapon'?'右腕 → 武器':labelBone[p.bone]||p.bone)} · z ${p.z}</small></button><div><button data-layer-up="${esc(p.id)}" aria-label="上移 ${esc(p.name)}" ${i===0?'disabled':''}>↑</button><button data-layer-down="${esc(p.id)}" aria-label="下移 ${esc(p.name)}" ${i===rows.length-1?'disabled':''}>↓</button></div></div>`).join('')||'<p class="help">先上传或拆分角色部件。</p>';}
function layerOrder(){return (E.layerMode==='key'?effectiveLayers():S.p.parts.map((p,i)=>({...p,_index:i})).sort((a,b)=>b.z-a.z||b._index-a._index)).map(p=>p.id);}
function setLayerState(id,z,visible,u=phase()){S.p.motion.layer_keys=S.p.motion.layer_keys||[];S.p.motion.layer_keys=S.p.motion.layer_keys.filter(k=>!(k.part_id===id&&phaseEqual(k.phase,u)));S.p.motion.layer_keys.push({part_id:id,phase:rnd(u),z,visible});}
function applyOrder(ids){const values=new Map(effectiveLayers().map(p=>[p.id,p]));ids.forEach((id,i)=>{const p=S.p.parts.find(p=>p.id===id),z=ids.length-1-i;
 if(E.layerMode==='key')setLayerState(id,z,values.get(id).visible);else p.z=z;});}
async function reorder(id,where){await mutate(()=>{const ids=layerOrder(),i=ids.indexOf(id);if(i<0)return;const dest=where==='front'?0:where==='back'?ids.length-1:Math.max(0,Math.min(ids.length-1,i+where));ids.splice(i,1);ids.splice(dest,0,id);applyOrder(ids);});}
function tabChanged(){if(!S.p)return;document.body.dataset.editorTab=S.tab;sync();if(S.tab==='rig')$('canvas-hint').textContent='初始结构：拖动关节，或切换骨骼旋转；联动选项在右侧。';else if(S.tab==='motion')$('canvas-hint').textContent=$('edit-autokey').checked?'暂停调姿：IK 拖动手脚，FK 拖动选中骨骼。松开写入关键帧。':'打开「画布调姿」后可拖动修改动作。';}
function afterRender(f){updateCursor();if(!S.cfg)return;const ctx=$('skeleton').getContext('2d');
 if((S.tab==='rig'||$('edit-autokey').checked)&&S.cfg.bones[E.bone]){const [a,b]=S.cfg.bones[E.bone],p=point(f.joints[a]),q=point(f.joints[b]);ctx.save();ctx.strokeStyle='#e5b979';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(...p);ctx.lineTo(...q);ctx.stroke();ctx.beginPath();ctx.arc(...q,12,0,2*Math.PI);ctx.lineWidth=2;ctx.stroke();ctx.restore();}
 if(E.gesture?.cursor){const q=point(E.gesture.cursor);ctx.save();ctx.strokeStyle='#f0be78';ctx.setLineDash([5,4]);ctx.lineWidth=2;ctx.beginPath();ctx.arc(...q,12,0,Math.PI*2);ctx.stroke();ctx.font='14px sans-serif';ctx.fillStyle='#f0be78';ctx.fillText('松开后求解',q[0]+16,q[1]);ctx.restore();}}

$('edit-undo').onclick=safe(()=>historyMove(-1));$('edit-redo').onclick=safe(()=>historyMove(1));
$('edit-bone').onchange=()=>{E.bone=$('edit-bone').value;S.selectedJoint=S.cfg.bones[E.bone][1];$('joint-select').value=S.selectedJoint;syncJoint();list();render();};
$('edit-rest-mode').onchange=()=>{E.restMode=$('edit-rest-mode').value;};
$('edit-apply-bone').onclick=safe(()=>mutate(()=>boneTransform(S.p.rig,E.bone,num('edit-length'),num('edit-bind-angle'),$('edit-cascade').checked)));
$('apply-joint').onclick=safe(()=>mutate(()=>moveJoint(S.p.rig,S.selectedJoint,[num('joint-x'),num('joint-y')],$('edit-cascade').checked)));
$('edit-apply-weapon').onclick=safe(()=>mutate(()=>{S.p.rig.weapon_length=num('edit-weapon-length');S.p.rig.approved=false;}));
$('edit-apply-hit').onclick=safe(()=>mutate(()=>{S.p.motion.hit_phase=num('edit-hit-phase')/100;}));
$('key-target').onchange=()=>{E.selected=null;const v=evaluated($('key-target').value,phase());$('edit-key-phase').value=rnd(phase()*100);$('key-x').value=rnd(v[0]);$('key-y').value=rnd(v[1]);$('key-angle').value=rnd(v[2]);updateFields();buttons();};
$('add-key').onclick=safe(()=>mutate(()=>upsert(keyFromFields(),E.selected)));
$('edit-delete-key').onclick=safe(()=>mutate(()=>{const old=E.selected;S.p.motion.keys=S.p.motion.keys.filter(k=>!(k.target===old?.target&&phaseEqual(k.phase,old.phase)));E.selected=null;}));
$('edit-copy-key').onclick=safe(()=>mutate(()=>{const source=S.p.motion.keys.find(k=>k.target===E.selected?.target&&phaseEqual(k.phase,E.selected.phase));if(!source)return;const u=rnd(phase());if(S.p.motion.keys.some(k=>k.target===source.target&&phaseEqual(k.phase,u)))throw Error('当前帧已有同轨道关键帧；请先移动时间轴。');upsert({...source,phase:u});}));
$('edit-new-key').onclick=()=>{E.selected=null;$('key-target').onchange();drawKeys();};
$('keys-list').onclick=safe(async e=>{const selected=e.target.closest('[data-edit-key]'),remove=e.target.closest('[data-edit-remove]');if(selected)selectKey(Number(selected.dataset.editKey));if(remove)await mutate(()=>{S.p.motion.keys.splice(Number(remove.dataset.editRemove),1);E.selected=null;});});
$('edit-track-filter').onchange=drawKeys;
$('edit-autokey').onchange=()=>{S.playing=false;tabChanged();render();};$('edit-pose-mode').onchange=()=>{S.playing=false;render();};
for(const [id,sign] of [['edit-prev-key',-1],['edit-next-key',1]])$(id).onclick=()=>{const u=phase(),times=[...new Set([...S.p.motion.keys,...(S.p.motion.layer_keys||[])].map(k=>k.phase))].sort((a,b)=>a-b),t=sign<0?times.filter(t=>t<u-1e-6).at(-1):times.find(t=>t>u+1e-6);if(t!==undefined){S.playing=false;S.frame=nearestFrame(t);E.selected=null;render();}};
$('edit-layer-mode').onchange=()=>{E.layerMode=$('edit-layer-mode').value;S.playing=false;afterList();syncPart();};
$('edit-front').onclick=safe(()=>reorder(S.selectedPart,'front'));$('edit-back').onclick=safe(()=>reorder(S.selectedPart,'back'));
$('edit-layer-record').onclick=safe(()=>mutate(()=>{for(const p of effectiveLayers())setLayerState(p.id,p.z,p.visible);E.layerMode='key';$('edit-layer-mode').value='key';}));
$('edit-layer-clear').onclick=safe(()=>mutate(()=>{S.p.motion.layer_keys=(S.p.motion.layer_keys||[]).filter(k=>!phaseEqual(k.phase,phase()));}));
$('edit-layer-keys').onclick=safe(async e=>{const a=e.target.closest('[data-layer-seek]'),d=e.target.closest('[data-layer-delete]');if(a){S.playing=false;S.frame=nearestFrame(Number(a.dataset.layerSeek));render();syncPart();}if(d)await mutate(()=>{S.p.motion.layer_keys=S.p.motion.layer_keys.filter(k=>!phaseEqual(k.phase,Number(d.dataset.layerDelete)));});});
$('apply-part').onclick=safe(()=>mutate(()=>{const p=getPart();if(!p)return;p.name=$('edit-part-name').value;p.bone=$('part-bone').value;p.scale=num('part-scale');p.rotation=num('part-rotation');p.offset=[num('part-x'),num('part-y')];
 if(E.layerMode==='key')setLayerState(p.id,num('part-z'),$('part-visible').checked);else{p.z=num('part-z');p.visible=$('part-visible').checked;}}));
$('side-list').addEventListener('click',safe(async e=>{for(const [attr,delta] of [['layerUp',-1],['layerDown',1]]){const b=e.target.closest(`[data-${attr.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())}]`);if(b){await reorder(b.dataset[attr],delta);return;}}
 const b=e.target.closest('[data-layer-toggle]');if(b)await mutate(()=>{const id=b.dataset.layerToggle,p=S.p.parts.find(p=>p.id===id);if(E.layerMode==='key'){const q=effectiveLayers().find(p=>p.id===id);setLayerState(id,q.z,!q.visible);}else p.visible=!p.visible;});}));
$('side-list').addEventListener('dragstart',e=>{const r=e.target.closest('[data-layer-id]');if(!r||E.busy||S.savePromise){e.preventDefault();return;}E.dragLayer=r.dataset.layerId;e.dataTransfer.setData('text/plain',E.dragLayer);e.dataTransfer.effectAllowed='move';});
$('side-list').addEventListener('dragover',e=>{if(E.dragLayer&&e.target.closest('[data-layer-id]')){e.preventDefault();e.dataTransfer.dropEffect='move';}});
$('side-list').addEventListener('drop',safe(async e=>{e.preventDefault();const r=e.target.closest('[data-layer-id]'),id=E.dragLayer;E.dragLayer=null;if(!r||!id||r.dataset.layerId===id)return;await mutate(()=>{const order=layerOrder(),i=order.indexOf(id),j=order.indexOf(r.dataset.layerId);order.splice(i,1);order.splice(j,0,id);applyOrder(order);});}));
$('side-list').addEventListener('dragend',()=>E.dragLayer=null);

// Timeline markers use pointer capture for mouse and touch; updating time never
// silently overwrites another key on the same track.
let keyDrag=null;
$('edit-lanes').onpointerdown=e=>{const marker=e.target.closest('[data-diamond]'),layer=e.target.closest('[data-layer-phase]');if(layer){S.playing=false;S.frame=nearestFrame(Number(layer.dataset.layerPhase));render();return;}
 if(!marker||E.busy||S.savePromise)return;const i=Number(marker.dataset.diamond);selectKey(i);
 const live=$('edit-lanes').querySelector(`[data-diamond="${i}"]`);const lane=live.parentElement;
 keyDrag={key:structuredClone(S.p.motion.keys[i]),rect:lane.getBoundingClientRect(),start:e.clientX,moved:false,marker:live,phase:S.p.motion.keys[i].phase};$('edit-lanes').setPointerCapture(e.pointerId);e.preventDefault();};
$('edit-lanes').onpointermove=e=>{if(!keyDrag)return;const g=keyDrag;if(Math.abs(e.clientX-g.start)>3)g.moved=true;if(!g.moved)return;g.phase=rnd(Math.max(0,Math.min(1,(e.clientX-g.rect.left)/g.rect.width)));g.marker.style.left=(g.phase*100)+'%';$('edit-key-phase').value=rnd(g.phase*100);};
$('edit-lanes').onpointerup=safe(async e=>{const g=keyDrag;keyDrag=null;if(!g)return;if($('edit-lanes').hasPointerCapture(e.pointerId))$('edit-lanes').releasePointerCapture(e.pointerId);if(g.moved)await mutate(()=>upsert({...g.key,phase:g.phase},{phase:g.key.phase,target:g.key.target}));else drawKeys();});
$('edit-lanes').onpointercancel=()=>{keyDrag=null;drawKeys();};

const oldPointerDown=$('skeleton').onpointerdown;
function closestJoint(pos,names,frame){let best=null,dist=24;for(const name of names){const q=point(frame.joints[name]),d=Math.hypot(pos[0]-q[0],pos[1]-q[1]);if(d<dist){best=name;dist=d;}}return best;}
function closestBone(pos,frame){let best=null,dist=18;for(const [name,[a,b]] of Object.entries(S.cfg.bones)){const p=point(frame.joints[a]),q=point(frame.joints[b]),dx=q[0]-p[0],dy=q[1]-p[1],v=Math.max(0,Math.min(1,((pos[0]-p[0])*dx+(pos[1]-p[1])*dy)/(dx*dx+dy*dy)));const d=Math.hypot(pos[0]-p[0]-v*dx,pos[1]-p[1]-v*dy);if(d<dist){best=name;dist=d;}}return best;}
$('skeleton').onpointerdown=e=>{if(!S.p||E.busy||S.savePromise)return;if(S.crop){oldPointerDown(e);return;}const pos=mouse(e,$('skeleton')),frame=currentFrame();
 if(S.tab==='rig'){
   let joint=closestJoint(pos,S.cfg.joints,frame);const bone=closestBone(pos,frame);if(E.restMode==='rotate'&&bone){E.bone=bone;joint=S.cfg.bones[bone][1];}
   if(!joint){if(bone){E.bone=bone;S.selectedJoint=S.cfg.bones[bone][1];syncJoint();render();}return;}
   S.selectedJoint=joint;syncJoint();list();E.gesture={kind:E.restMode==='rotate'?'bind-rotate':'bind-move',joint,bone:E.bone,start:world(pos),rig:structuredClone(S.p.rig),dirty:S.dirty};
 }else if((S.tab==='motion'||S.tab==='reference')&&$('edit-autokey').checked){
   S.playing=false;S.clock=0;
   if($('edit-pose-mode').value==='ik'){const joint=closestJoint(pos,positional,frame);if(!joint)return;const u=phase();E.gesture={kind:'ik',joint,phase:u,base:evaluated(joint,u),target:frame.targets?.[joint]||frame.joints[joint],cursor:world(pos),start:world(pos)};
   }else{const bone=closestBone(pos,frame);if(!bone)return;E.bone=bone;S.selectedJoint=S.cfg.bones[bone][1];const [a,b]=S.cfg.bones[bone],pivot=frame.joints[a],wp=world(pos);E.gesture={kind:'fk',bone,phase:phase(),base:evaluated('bone:'+bone,phase())[2],pivot,startAngle:Math.atan2(wp[1]-pivot[1],wp[0]-pivot[0]),cursor:wp};}
 }else return;
 E.gesture.moved=false;$('skeleton').setPointerCapture(e.pointerId);e.preventDefault();render();};
$('skeleton').onpointermove=e=>{const g=E.gesture;if(!g)return;const w=world(mouse(e,$('skeleton')));g.cursor=w;g.moved=true;
 if(g.kind==='bind-move'){S.p.rig=structuredClone(g.rig);moveJoint(S.p.rig,g.joint,[g.rig.joints[g.joint][0]+w[0]-g.start[0],g.rig.joints[g.joint][1]+w[1]-g.start[1]],$('edit-cascade').checked);syncJoint();}
 if(g.kind==='bind-rotate'){const [a,b]=S.cfg.bones[g.bone],p=g.rig.joints[a],q=g.rig.joints[b];S.p.rig=structuredClone(g.rig);boneTransform(S.p.rig,g.bone,Math.hypot(q[0]-p[0],q[1]-p[1]),Math.atan2(w[1]-p[1],w[0]-p[0])*180/Math.PI,$('edit-cascade').checked);syncJoint();}
 render();};
$('skeleton').onpointerup=safe(async e=>{const g=E.gesture;E.gesture=null;if(!g)return;if($('skeleton').hasPointerCapture(e.pointerId))$('skeleton').releasePointerCapture(e.pointerId);
 if(!g.moved){render();return;}
 if(g.kind.startsWith('bind')){const changed=S.p.rig;S.p.rig=g.rig;await mutate(()=>{S.p.rig=changed;});return;}
 await mutate(()=>{let k={phase:rnd(g.phase),target:g.joint||'bone:'+g.bone,dx:0,dy:0,angle:0,interpolation:$('edit-easing').value};
 if(g.kind==='ik'){k.dx=rnd(g.base[0]+g.cursor[0]-g.target[0]);k.dy=rnd(g.base[1]+g.cursor[1]-g.target[1]);}
 else{k.angle=rnd(g.base+wrap(Math.atan2(g.cursor[1]-g.pivot[1],g.cursor[0]-g.pivot[0])-g.startAngle)*180/Math.PI);}
 upsert(k);$('key-target').value=k.target;$('edit-key-phase').value=k.phase*100;$('key-x').value=k.dx;$('key-y').value=k.dy;$('key-angle').value=k.angle;});});
$('skeleton').onpointercancel=()=>{const g=E.gesture;E.gesture=null;if(g?.rig){S.p.rig=g.rig;S.dirty=g.dirty;syncJoint();}render();};
// Click a rendered part to select its binding. Alpha-aware hit testing prevents
// a large transparent source rectangle from stealing all selections.
const hitCache=new Map();
$('character').onpointerdown=e=>{if(S.tab!=='parts'||E.busy||!S.clip)return;const p=mouse(e,$('character')),commands=currentFrame().draws||[];
 for(const cmd of [...commands].reverse()){const im=image(cmd.image);if(!im)continue;const [a,b,c,d,x,y]=cmd.matrix,det=a*d-b*c;if(Math.abs(det)<1e-9)continue;const px=Math.floor((d*(p[0]-x)-c*(p[1]-y))/det),py=Math.floor((-b*(p[0]-x)+a*(p[1]-y))/det);if(px<0||py<0||px>=im.width||py>=im.height)continue;
 let data=hitCache.get(im);if(!data){const canvas=document.createElement('canvas');canvas.width=im.width;canvas.height=im.height;const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(im,0,0);data=ctx.getImageData(0,0,im.width,im.height).data;hitCache.set(im,data);}
 if(data[(py*im.width+px)*4+3]<16)continue;S.selectedPart=cmd.id;$('part-select').value=cmd.id;syncPart();list();return;}};
document.addEventListener('keydown',safe(async e=>{if(e.target.closest('input,select,textarea,[contenteditable]')||document.querySelector('dialog[open]'))return;
 if((e.ctrlKey||e.metaKey)&&['z','y'].includes(e.key.toLowerCase())){e.preventDefault();await historyMove(e.key.toLowerCase()==='y'||e.shiftKey?1:-1);return;}
 if(e.code==='Space'){e.preventDefault();$('play').click();}
 if(S.tab==='rig'&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)&&!e.repeat){e.preventDefault();const step=e.shiftKey?.025:.005,d={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,step],ArrowDown:[0,-step]}[e.key];await mutate(()=>moveJoint(S.p.rig,S.selectedJoint,S.p.rig.joints[S.selectedJoint].map((v,i)=>v+d[i]),$('edit-cascade').checked));}}));
window.rigEditor={opened,saved,buttons,afterList,afterRender,tabChanged,sync,syncRig,syncPart,drawKeys,changeAction,
 // Pure transforms and state are exposed for reproducible editor regression tests.
 state:E,mutate,record,labelBone,closestBone,closestJoint,nearestFrame,descendants,moveJoint,boneTransform,evaluated,effectiveLayers,selectKey,historyMove};
if(S.p)opened(S.p);
})();
