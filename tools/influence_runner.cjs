/* Headless harness for the browser's exact editing arithmetic (no DOM/network). */
'use strict';
const fs=require('node:fs');
const M=require('../lab/static/motion-influence.js');
function run(x){
 const before=JSON.stringify(x.motion);
 try {
  let result;
  if(x.action==='plan')result=M.plan(x.motion,x.request);
  else if(x.action==='sample')result=M.sample(x.motion,x.phase);
  else if(x.action==='world')result=M.world(x.key,x.rig,x.bones);
  else result=M.apply(x.motion,x.rig,x.bones,x.request);
  return {ok:true,result,source_unchanged:before===JSON.stringify(x.motion)};
 }catch(e){return {ok:false,error:String(e.message),source_unchanged:before===JSON.stringify(x.motion)};}
}
const input=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(Array.isArray(input)?input.map(run):run(input)));
