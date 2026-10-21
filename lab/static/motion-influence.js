/* Pure proportional pose editing. No DOM, network, shared state or pixel edits.
 * Each affected pose receives the SAME DELTA times a temporal weight, not a
 * copy of the selected pose. The caller owns revision leases and undo/redo.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.motionInfluence = api;
})(globalThis, function () {
  'use strict';
  const topology=typeof module==='object'&&module.exports?require('./rig-topology.js'):globalThis.rigTopology;
  const copy = x => structuredClone(x);
  const rad = x => x * Math.PI / 180;
  const deg = x => x * 180 / Math.PI;
  const close = (a, b) => Math.abs(a - b) < 1e-6;
  const finite = (x, label) => {
    if (!Number.isFinite(x)) throw Error(label + '必须是有限数值。');
    return x;
  };
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const nearest = (value, around) => around + deg(Math.atan2(Math.sin(rad(value-around)), Math.cos(rad(value-around))));
  const isLoop = m => ['walk', 'idle'].includes(m.kind) && m.link_loop_ends !== false;

  function settings(raw) {
    const s = Object.assign({scope:'nearby', center:0, radius:.2, start:0, end:1,
      falloff:'smooth', strength:1, wrap:true}, raw);
    if (!['single','nearby','range','all'].includes(s.scope)) throw Error('未知编辑影响范围。');
    if (!['smooth','linear','constant'].includes(s.falloff)) throw Error('未知过渡曲线。');
    for (const key of ['center','radius','start','end','strength']) finite(s[key], key);
    if (s.center<0 || s.center>1 || s.strength<0 || s.strength>1 || s.radius<.005 || s.radius>.5)
      throw Error('时间、影响强度或半径超出范围。');
    if (s.scope==='range' && (s.start<0 || s.end>1 || s.start>=s.end || s.center<s.start || s.center>s.end))
      throw Error('指定区间必须包含当前时间，且起点小于终点。');
    s.wrap = s.wrap === true;
    return s;
  }

  function envelope(phase, s, loop) {
    if (s.scope==='single') return close(phase,s.center) ? s.strength : 0;
    if (s.scope==='all') return s.strength;
    let distance;
    if (s.scope==='nearby') {
      distance = Math.abs(phase-s.center);
      if (loop && s.wrap) distance = Math.min(distance,1-distance);
      distance /= s.radius;
    } else {
      if (phase<s.start || phase>s.end) return 0;
      if (close(phase,s.center)) return s.strength;
      distance = phase<s.center ? (s.center-phase)/(s.center-s.start) : (phase-s.center)/(s.end-s.center);
    }
    if (distance>1 || (distance>=1 && s.falloff!=='constant')) return 0;
    const t=clamp(1-distance,0,1);
    return s.strength*(s.falloff==='constant' ? 1 : s.falloff==='linear' ? t : t*t*(3-2*t));
  }

  function weight(phase, s, motion) {
    // 0 and 1 are two stored samples of one cycle boundary. Apply the same
    // delta to BOTH without copying travel, contacts or unrelated bone angles.
    if (isLoop(motion) && (phase===0 || phase===1))
      return Math.max(envelope(0,s,true),envelope(1,s,true));
    return envelope(phase,s,isLoop(motion));
  }

  function sample(motion, u, rig=null) {
    const keys=motion.pose_keys;
    if (!keys?.length) throw Error('请先将当前模板转换成可编辑关键帧。');
    if (u<=keys[0].phase) return {...copy(keys[0]),phase:u};
    if (u>=keys.at(-1).phase) return {...copy(keys.at(-1)),phase:u};
    for (let i=0;i<keys.length-1;i++) {
      const a=keys[i],b=keys[i+1];
      if (Math.abs(u-b.phase)<1e-12) return copy(b);
      if (a.phase<=u && u<b.phase) {
        let t=(u-a.phase)/(b.phase-a.phase);
        if(a.interpolation==='smooth')t=t*t*(3-2*t);else if(a.interpolation==='step')t=0;
        const lerp=(x,y)=>x+(y-x)*t,k=copy(a);k.phase=u;
        k.root=a.root.map((v,j)=>lerp(v,b.root[j]));k.travel_x=lerp(a.travel_x,b.travel_x);
        k.weapon=lerp(a.weapon,b.weapon);
        for(const n of new Set([...Object.keys(a.angles),...Object.keys(b.angles)])){if(rig)k.angles[n]=lerp(topology.local(a,rig,n),topology.local(b,rig,n));else if(n in a.angles&&n in b.angles)k.angles[n]=lerp(a.angles[n],b.angles[n]);}
        k.targets={};
        for(const n of new Set([...Object.keys(a.targets),...Object.keys(b.targets)])) {
          const p=a.targets[n]||b.targets[n],q=b.targets[n]||p;
          k.targets[n]=n.endsWith('_ankle')&&a.contacts[n[0]]?p.slice():p.map((v,j)=>lerp(v,q[j]));
        }
        return k;
      }
    }
    throw Error('姿势关键帧时间无效。');
  }

  function world(key, rig, bones) {
    return topology.world(key,rig,bones);
  }

  function valueAt(key, target, rig, bones, rootMode) {
    if(target==='weapon') return key.weapon;
    if(target.startsWith('bone:')) return topology.local(key,rig,target.slice(5));
    const p=world(key,rig,bones).points[target];
    if(!p)throw Error('未知调姿目标。');
    return [p[0]-(rootMode==='in_place'?key.travel_x:0),p[1]];
  }

  function plan(motion, raw) {
    if(motion.driver!=='keyframes')throw Error('请先将当前模板转换成可编辑关键帧。');
    const s=settings(raw),phases=motion.pose_keys.map(k=>k.phase);
    const existing=phases.find(p=>close(p,s.center));
    const inserted=existing===undefined;
    // Resolve sub-microsecond input to the real key, never create duplicate keys.
    if(!inserted)s.center=existing;
    if(inserted)phases.push(s.center);
    phases.sort((a,b)=>a-b);
    const weighted=phases.map(phase=>({phase,weight:weight(phase,s,motion)}));
    return {settings:s,weights:weighted,affected:weighted.filter(k=>k.weight>1e-10).length,
      total:phases.length,inserted};
  }

  function shiftKey(key,target,delta,amount,rig,bones) {
    if(target==='weapon'){key.weapon+=delta*amount;return 0;}
    if(target.startsWith('bone:')){key.angles[target.slice(5)]=topology.local(key,rig,target.slice(5))+delta*amount;return 0;}
    if(target==='pelvis'){key.root=key.root.map((v,i)=>v+delta[i]*amount);return 0;}
    const f=world(key,rig,bones),side=target[0],leg=target.endsWith('_ankle');
    const limb=side+(leg?'_leg':'_arm');
    if(topology.single(rig,limb)){
      const [root,,end]=topology.limbs[limb],a=f.points[root],old=f.points[end],goal=old.map((v,i)=>v+delta[i]*amount),dx=goal[0]-a[0],dy=goal[1]-a[1],distance=Math.hypot(dx,dy),theta=distance>1e-10?Math.atan2(dy,dx):f.angles[limb],parent=f.parents[limb];
      key.angles[limb]=nearest(deg(theta-(parent?f.angles[parent]:0)),topology.local(key,rig,limb));
      if(!leg||!key.contacts[side])key.targets[target]=goal;
      return Math.abs(distance-Math.hypot(...rig.joints[end].map((v,i)=>v-rig.joints[root][i])));
    }
    const upper=side+(leg?'_thigh':'_upper_arm'),lower=side+(leg?'_shin':'_forearm');
    const [root,middle]=bones[upper],end=bones[lower][1],a=f.points[root],old=f.points[end];
    const goal=old.map((v,i)=>v+delta[i]*amount);
    const L1=Math.hypot(...rig.joints[middle].map((v,i)=>v-rig.joints[root][i]));
    const L2=Math.hypot(...rig.joints[end].map((v,i)=>v-rig.joints[middle][i]));
    const vx=goal[0]-a[0],vy=goal[1]-a[1],distance=Math.hypot(vx,vy),eps=(L1+L2)*1e-12;
    let dx=vx,dy=vy,mag=distance;
    if(mag<=eps){dx=old[0]-a[0];dy=old[1]-a[1];mag=Math.hypot(dx,dy);}
    if(mag<=eps){dx=rig.joints[end][0]-rig.joints[root][0];dy=rig.joints[end][1]-rig.joints[root][1];mag=Math.hypot(dx,dy);}
    if(mag<=eps){dx=1;dy=0;mag=1;}
    const ux=dx/mag,uy=dy/mag,d=clamp(distance,Math.max(Math.abs(L1-L2),eps),L1+L2);
    const along=(L1*L1-L2*L2+d*d)/(2*d),h=Math.sqrt(Math.max(0,L1*L1-along*along));
    // Keep each authored pose's elbow/knee branch; a global bind sign could
    // flip a manually edited chain. Near straight/folded, use bind sign.
    const cross=(old[0]-a[0])*(f.points[middle][1]-a[1])-(old[1]-a[1])*(f.points[middle][0]-a[0]);
    const bend=Math.abs(cross)>1e-10?Math.sign(cross):rig.bend[side+(leg?'_leg':'_arm')];
    const b=[a[0]+along*ux-bend*h*uy,a[1]+along*uy+bend*h*ux];
    const c=[a[0]+d*ux,a[1]+d*uy],up=Math.atan2(b[1]-a[1],b[0]-a[0]);
    const lo=Math.atan2(c[1]-b[1],c[0]-b[0]),parent=f.parents[upper];
    key.angles[upper]=nearest(deg(up-(parent?f.angles[parent]:0)),key.angles[upper]);
    key.angles[lower]=nearest(deg(lo-up),key.angles[lower]);
    // Preserve plant targets instead of changing the definition of 'ground' to
    // conceal contact loss. Non-contact targets track the requested edit.
    if(!leg || !key.contacts[side])key.targets[target]=goal;
    return Math.hypot(c[0]-goal[0],c[1]-goal[1]);
  }

  function apply(motion,rig,bones,request) {
    const p=plan(motion,request),target=request.target;
    if(!['pelvis','l_wrist','r_wrist','l_ankle','r_ankle','weapon',...Object.keys(topology.bones(rig,bones)).map(n=>'bone:'+n)].includes(target))
      throw Error('未知调姿目标。');
    const angular=target==='weapon'||target.startsWith('bone:'),delta=request.delta;
    if(angular)finite(delta,'角度变化');
    else if(!Array.isArray(delta)||delta.length!==2)throw Error('位置变化需要 X/Y 两个数值。');
    else delta.forEach(v=>finite(v,'位置变化'));
    const magnitude=angular?Math.abs(delta):Math.hypot(...delta);
    if(magnitude<1e-12 || p.settings.strength===0)
      return {motion:copy(motion),summary:{...p,changed:false,affected:0,max_ik_error:0,warnings:[]}};
    if(p.inserted && motion.pose_keys.length>=129)throw Error('姿势数已达 129；请选择已有关键帧，未修改动作。');
    const result=copy(motion),warnings=[];
    if(p.inserted){result.pose_keys.push(sample(motion,p.settings.center,rig));result.pose_keys.sort((a,b)=>a.phase-b.phase);}
    let residual=0;
    for(let i=0;i<result.pose_keys.length;i++) {
      const key=result.pose_keys[i],w=p.weights[i].weight;
      if(w<=1e-10)continue;
      residual=Math.max(residual,shiftKey(key,target,delta,w,rig,bones));
      if(key.root.some(v=>!Number.isFinite(v)||Math.abs(v)>10)||Math.abs(key.weapon)>7200||
         Object.values(key.angles).some(a=>!Number.isFinite(a)||Math.abs(a)>7200)||
         Object.values(key.targets).flat().some(v=>!Number.isFinite(v)||Math.abs(v)>20))
        throw Error('本次联动超出姿势数值范围；未保存任何部分，请减小修改量。');
    }
    if(residual>1e-5)warnings.push('部分手脚目标超出可达范围，保持骨长并报告误差，未强行拉伸。');
    if(target.includes('ankle')||target==='pelvis'||target.startsWith('bone:'))
      warnings.push('这是姿势联动，不自动锁脚；请检查接地误差与循环衔接。');
    if(p.inserted)warnings.push('当前时间原为插值姿势，已插入一个关键帧；插值可能随之变化。');
    return {motion:result,summary:{...p,changed:true,max_ik_error:residual,warnings}};
  }
  return {settings,envelope,weight,plan,sample,world,valueAt,apply};
});
