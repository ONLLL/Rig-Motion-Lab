/* Pure topology helpers. Stored legacy angles/points are never discarded. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.rigTopology=api;})(globalThis,function(){
'use strict';
const limbs={l_arm:['l_shoulder','l_elbow','l_wrist','l_upper_arm','l_forearm'],r_arm:['r_shoulder','r_elbow','r_wrist','r_upper_arm','r_forearm'],l_leg:['l_hip','l_knee','l_ankle','l_thigh','l_shin'],r_leg:['r_hip','r_knee','r_ankle','r_thigh','r_shin']};
const single=(rig,n)=>rig.limb_modes?.[n]==='single';
function bones(rig,all){const out={};for(const [name,pair] of Object.entries(all)){if(limbs[name])continue;const entry=Object.entries(limbs).find(([,v])=>v[3]===name||v[4]===name);if(entry&&single(rig,entry[0])){if(entry[1][3]===name)out[entry[0]]=[entry[1][0],entry[1][2]];}else out[name]=pair;}return out;}
function joints(rig,names){const hidden=new Set(Object.entries(limbs).filter(([n])=>single(rig,n)).map(([,v])=>v[1]));return names.filter(n=>!hidden.has(n));}
const angle=(a,b)=>Math.atan2(b[1]-a[1],b[0]-a[0]);
function local(key,rig,n){if(Number.isFinite(key.angles[n]))return key.angles[n];const v=limbs[n];if(!v)throw Error('缺少骨骼角度：'+n);return key.angles[v[3]]+(angle(rig.joints[v[0]],rig.joints[v[2]])-angle(rig.joints[v[0]],rig.joints[v[1]]))*180/Math.PI;}
function world(key,rig,all){const active=bones(rig,all),parents={},angles={},points={pelvis:[rig.joints.pelvis[0]+key.root[0]+key.travel_x,rig.joints.pelvis[1]+key.root[1]]};for(const[n,[a,b]]of Object.entries(active)){const ancestry=limbs[n]?active:Object.fromEntries(Object.entries(all).filter(([name])=>!limbs[name]));const parent=Object.keys(ancestry).find(p=>ancestry[p][1]===a);parents[n]=parent;const theta=local(key,rig,n)*Math.PI/180+(parent?angles[parent]:0),len=Math.hypot(...rig.joints[b].map((v,i)=>v-rig.joints[a][i]));angles[n]=theta;points[b]=[points[a][0]+len*Math.cos(theta),points[a][1]+len*Math.sin(theta)];if(limbs[n]){const [,mid,,upper,lower]=limbs[n],delta=theta-angle(rig.joints[a],rig.joints[b]),v=rig.joints[mid].map((x,i)=>x-rig.joints[a][i]);points[mid]=[points[a][0]+Math.cos(delta)*v[0]-Math.sin(delta)*v[1],points[a][1]+Math.sin(delta)*v[0]+Math.cos(delta)*v[1]];angles[upper]=angle(points[a],points[mid]);angles[lower]=angle(points[mid],points[b]);}}return{points,angles,parents};}
function activeBone(rig,name){for(const[n,v]of Object.entries(limbs))if(single(rig,n)&&(name===v[3]||name===v[4]))return n;return name;}
return{limbs,single,bones,joints,local,world,activeBone};
});
