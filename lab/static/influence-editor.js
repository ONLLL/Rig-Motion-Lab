/* Temporal influence controls for EDITOR 04. Geometry lives in the pure module.
 * Every drag operates on one immutable pre-drag motion; one mouse-up = one save
 * and one undo item. Changing influence never changes textures or the bind rig.
 */
(() => {
'use strict';
const M=window.motionInfluence;
const I={last:null,signature:null};
const clone=x=>structuredClone(x),near=(a,b)=>Math.abs(a-b)<1e-6;
const phase=()=>S.previewPhase??S.clip?.frames[S.frame]?.phase??0;
const busy=()=>rigEditor.state.busy||S.savePromise||templateEditor.state.gesture;
const label={single:'当前帧',nearby:'附近一段',range:'指定区间',all:'整个动作'};

$('pose-target').closest('label').insertAdjacentHTML('beforebegin',`
 <section class="influence-box" aria-label="动作编辑影响范围">
  <div class="influence-heading"><strong>编辑影响范围</strong><span>多帧联动</span></div>
  <label>本次修改作用于<select id="influence-scope">
   <option value="single">仅当前姿势 · 单帧精修</option>
   <option value="nearby" selected>附近一段 · 平滑联动（推荐）</option>
   <option value="range">指定时间区间</option>
   <option value="all">整个动作 · 保留原有变化</option>
  </select></label>
  <div id="influence-nearby"><label>向前 / 后影响 <output id="influence-radius-out">20%</output>
   <input id="influence-radius" type="range" min="1" max="50" step="1" value="20"></label></div>
  <div id="influence-range" class="two" hidden>
   <label>起点 / %<input id="influence-start" type="number" min="0" max="100" step=".1" value="20"></label>
   <label>终点 / %<input id="influence-end" type="number" min="0" max="100" step=".1" value="80"></label>
  </div>
  <div class="two influence-options">
   <label>范围内过渡<select id="influence-falloff"><option value="smooth">平滑衰减</option><option value="linear">线性衰减</option><option value="constant">等量 · 无衰减</option></select></label>
   <label>修改强度 / %<input id="influence-strength" type="number" min="0" max="100" step="5" value="100"></label>
  </div>
  <label class="check"><input id="influence-wrap" type="checkbox" checked>循环动作跨首尾平滑影响</label>
  <div id="influence-summary" class="influence-summary" role="status"></div>
  <p class="help">保持各帧原姿势，只叠加这次的位移／旋转差量，不把所有帧改成同一个姿势。范围以姿势关键帧为准，帧间仍按原插值衔接。</p>
  <button id="influence-reapply" class="full" disabled>重设上次修改的影响范围</button>
  <p id="influence-last" class="help">一次调姿，一次撤销。联动不会改初始骨架或其它动作。</p>
 </section>`);
$('pose-apply').textContent='按影响范围应用修改';
$('pose-source-note').textContent='转换为姿势后，支持附近联动或整段动作编辑，不必逐帧重复调整。';
$('pose-controls').querySelector('.pose-note').textContent='左右画布均可调姿。默认联动附近一段，松开后一次保存；0%/100% 边界保留。位置数值是当前姿势目标，系统把本次差量应用到所选范围。';
$('pose-timeline').querySelector('.help').textContent='金色菱形是姿势。背景色带显示本次时间影响：颜色越深影响越强。一次编辑可改变整段，不改各帧的原有运动时间。';

function options(center=phase()) {
 return M.settings({scope:$('influence-scope').value,center,radius:Number($('influence-radius').value)/100,
  start:Number($('influence-start').value)/100,end:Number($('influence-end').value)/100,
  falloff:$('influence-falloff').value,strength:Number($('influence-strength').value)/100,
  wrap:$('influence-wrap').checked});
}
function lastValid() {return I.last && S.p?.id===I.last.pid && S.p.motion.kind===I.last.kind &&
 S.p.revision===I.last.afterRevision && templateEditor.active();}
function context(settings=options()) {
 return {base:clone(S.p.motion),rig:clone(S.p.rig),bones:clone(S.cfg.bones),settings,
  pid:S.p.id,kind:S.p.motion.kind,revision:S.p.revision};
}
function operation(ctx,target,delta) {
 return M.apply(ctx.base,ctx.rig,ctx.bones,{...ctx.settings,target,delta});
}
function renderBand(p) {
 const strip=$('pose-strip');let band=strip.querySelector('.influence-band');
 if(!band){band=document.createElementNS('http://www.w3.org/2000/svg','svg');band.classList.add('influence-band');band.setAttribute('viewBox','0 0 1000 40');band.setAttribute('preserveAspectRatio','none');band.setAttribute('aria-hidden','true');strip.prepend(band);}
 const s=p.settings,m=S.p.motion,points=[];
 for(let i=0;i<=160;i++)points.push(`${i*1000/160},${39-33*M.weight(i/160,s,m)}`);
 band.innerHTML=`<path d="M 0 39 L ${points.join(' L ')} L 1000 39 Z"/>`;
 for(const dot of strip.querySelectorAll('[data-pose-index]')) {
  const k=m.pose_keys[Number(dot.dataset.poseIndex)],w=M.weight(k.phase,s,m);
  dot.classList.toggle('influence-affected',w>1e-10);dot.style.setProperty('--influence-weight',String(w));
  dot.title=`姿势 ${(k.phase*100).toFixed(1)}% · 本次影响 ${Math.round(w*100)}%`;
 }
}
function refresh(force=false) {
 if(!S.p||!templateEditor.active())return;
 const g=templateEditor.state.gesture;
 const key=JSON.stringify([S.p.id,S.p.revision,S.p.motion.kind,phase(),$('influence-scope').value,
  $('influence-radius').value,$('influence-start').value,$('influence-end').value,
  $('influence-falloff').value,$('influence-strength').value,$('influence-wrap').checked,
  S.p.motion.link_loop_ends,!!g,!!rigEditor.state.busy,!!S.savePromise]);
 if(key===I.signature&&!force&&$('pose-strip').querySelector('.influence-band'))return;I.signature=key;
 const scope=$('influence-scope').value;
 $('influence-nearby').hidden=scope!=='nearby';$('influence-range').hidden=scope!=='range';
 $('influence-falloff').disabled=['single','all'].includes(scope);
 $('influence-radius-out').value=$('influence-radius').value+'%';
 const loop=['idle','walk'].includes(S.p.motion.kind)&&S.p.motion.link_loop_ends!==false;
 $('influence-wrap').disabled=!loop||scope!=='nearby';
 try {
  const p=M.plan(S.p.motion,g?.influence?.settings||options());
  $('influence-summary').textContent=`${label[p.settings.scope]} · 将影响 ${p.affected} / ${p.total} 个姿势${loop?'（含闭合边界）':''}${p.inserted?' · 当前处插入 1 个姿势':''}`;
  $('influence-summary').classList.remove('invalid');renderBand(p);$('pose-apply').disabled=!!busy();
 } catch(e) {
  $('influence-summary').textContent=e.message;$('influence-summary').classList.add('invalid');
  $('pose-apply').disabled=true;$('pose-strip').querySelector('.influence-band')?.remove();
 }
 $('influence-reapply').disabled=!lastValid()||!!busy();
 if(lastValid()) {
  const l=I.last,summary=l.result.summary;
  $('influence-last').textContent=`上次：${(l.settings.center*100).toFixed(1)}% 处，影响 ${summary.affected} 个姿势。调整范围后可重设，不会重复叠加。${summary.max_ik_error>1e-5?' 部分目标不可达，请查看诊断。':''}`;
 } else if(I.last) {$('influence-last').textContent='工程已有后续修改；为避免覆盖，不能重设上次影响。可先撤销或进行新的联动编辑。';}
}
async function persist(ctx,target,delta,result,reapply=false) {
 if(rigEditor.state.busy||S.savePromise)throw Error('正在保存；本次联动未写入，请稍后重试。');
 if(!result.summary.changed&&!reapply){toast('没有位置或角度变化，未保存。');return;}
 await rigEditor.mutate(()=>{
  if(S.p.id!==ctx.pid||S.p.revision!==ctx.revision||S.p.motion.kind!==ctx.kind)
   throw Error('工程已变化，未覆盖新的动作。');
  S.p.motion=clone(result.motion);templateEditor.state.selected=result.summary.settings.center;
  S.previewPhase=result.summary.settings.center;S.frame=rigEditor.nearestFrame(S.previewPhase);
 });
 I.last={...ctx,target,delta:clone(delta),result,afterRevision:S.p.revision};
 templateEditor.sync();refresh(true);
 const summary=result.summary;
 toast(reapply?`已重设上次影响：${summary.affected} 个姿势，无重复叠加。`:
  `已联动修改 ${summary.affected} 个姿势；可一次撤销。${summary.max_ik_error>1e-5?'部分手脚目标不可达。':''}`);
}
async function applyNumeric(target,value) {
 if(busy())return toast('正在保存或拖动，请稍候。',true);
 S.playing=false;const ctx=context(),k=M.sample(ctx.base,ctx.settings.center);
 const previous=M.valueAt(k,target,ctx.rig,ctx.bones,ctx.base.root_mode);
 const delta=Array.isArray(previous)?value.map((v,i)=>v-previous[i]):value-previous;
 const result=operation(ctx,target,delta);
 return persist(ctx,target,delta,result);
}
function beginGesture(g) {
 try{g.influence=context();return true;}catch(e){toast(e.message,true);return false;}
}
function previewGesture(g,cursor) {
 const ctx=g.influence;if(!ctx)return;
 const delta=g.mode==='fk'?(g.target==='weapon'?g.key.weapon-g.original.weapon:g.key.angles[g.bone]-g.original.angles[g.bone]):
  [cursor[0]-g.start[0],cursor[1]-g.start[1]];
 try {
  const result=operation(ctx,g.target,delta);g.influenceDelta=delta;g.influenceResult=result;g.influenceError=null;
  g.key=M.sample(result.motion,ctx.settings.center);
 }catch(e){g.influenceError=e.message;g.key=clone(g.original);g.influenceResult=null;}
}
async function commitGesture(g) {
 if(g.influenceError)throw Error(g.influenceError);
 if(g.influenceResult)return persist(g.influence,g.target,g.influenceDelta,g.influenceResult);
}
$('influence-reapply').onclick=safe(async()=>{
 if(!lastValid()||busy())return toast('上次修改后工程已变化，不能覆盖。',true);
 const last=I.last,ctx={...last,settings:options(last.settings.center),revision:S.p.revision};
 await persist(ctx,last.target,last.delta,operation(ctx,last.target,last.delta),true);
});
for(const id of ['influence-scope','influence-radius','influence-start','influence-end','influence-falloff','influence-strength','influence-wrap']) {
 $(id).addEventListener('input',()=>{S.playing=false;refresh(true);});
 $(id).addEventListener('change',()=>refresh(true));
}
window.influenceEditor={state:I,options,context,applyNumeric,beginGesture,previewGesture,commitGesture,
 sync:()=>refresh(true),afterRender:()=>refresh(),refresh};
if(S.p)refresh(true);
})();
