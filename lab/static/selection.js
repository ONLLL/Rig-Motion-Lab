/* Editor-only alpha picking and silhouette overlays. No project/export mutation. */
(() => {
'use strict';
const Q={hover:null,show:true,xray:true,project:null,lastKey:'',canvas:null};
const pixels=new WeakMap(),mask=document.createElement('canvas'),visible=document.createElement('canvas'),edge=document.createElement('canvas');
for(const c of [mask,visible,edge]){c.width=768;c.height=768;}
$('stages').insertAdjacentHTML('beforebegin',`<section class="selection-bar" aria-label="部件选择状态">
 <div><strong id="selection-title">点击角色选择部件</strong><small id="selection-detail">按实际透明像素选取；Alt + 点击可轮选重叠部件。</small></div>
 <div class="selection-tools"><label class="check"><input id="selection-highlight" type="checkbox" checked>高亮选中</label><label class="check"><input id="selection-xray" type="checkbox" checked>透视轮廓</label><button id="selection-clear">取消选择</button></div></section>`);
function alpha(im){let a=pixels.get(im);if(a)return a;const c=document.createElement('canvas');c.width=im.width;c.height=im.height;const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(im,0,0);const d=ctx.getImageData(0,0,im.width,im.height).data;a=new Uint8Array(im.width*im.height);for(let i=0;i<a.length;i++)a[i]=d[i*4+3];pixels.set(im,a);return a;}
function hitTest(pos,f=currentFrame()){
 if(!S.p)return [];const ids=[];
 for(const cmd of drawCommands(f).slice().reverse()){
  const im=image(cmd.image);if(!im||!cmd.matrix)continue;const [a,b,c,d,x,y]=cmd.matrix,det=a*d-b*c;if(Math.abs(det)<1e-12)continue;
  const px=Math.floor((d*(pos[0]-x)-c*(pos[1]-y))/det),py=Math.floor((-b*(pos[0]-x)+a*(pos[1]-y))/det);
  if(px>=0&&py>=0&&px<im.width&&py<im.height&&alpha(im)[py*im.width+px]>=16)ids.push(cmd.id);
 }
 return ids;
}
function select(id,{scroll=true}={}){
 if(id&&!S.p?.parts.some(p=>p.id===id))return;
 S.selectedPart=id||null;Q.lastKey='';$('part-select').value=id||'';syncPart();list();render();sync();
 if(scroll&&id&&S.tab==='parts')document.querySelector(`[data-layer-id="${CSS.escape(id)}"]`)?.scrollIntoView({block:'nearest'});
}
function sync(){if(!S.p)return;const p=getPart(),hover=S.p.parts.find(p=>p.id===Q.hover);let status='';
 if(p){const visible=drawCommands().some(c=>c.id===p.id);status=visible?'金色轮廓为选中部件；外接框和透明留白不参与选取。':'该部件在当前时刻隐藏；透视轮廓只用于定位，不影响导出。';$('selection-title').textContent='已选：'+p.name;$('selection-detail').textContent=`${p.bone} · ${status}`;}
 else{$('selection-title').textContent=hover?'悬停：'+hover.name:'点击角色选择部件';$('selection-detail').textContent='点击可见像素选择；Alt + 点击轮选重叠部件；空白或 Esc 取消选择。';}
 for(const id of ['selection-clear','apply-part','remove-part','edit-front','edit-back'])$(id).disabled=!p;document.body.dataset.hasPartSelection=p?'true':'false';
 for(const row of document.querySelectorAll('[data-layer-id]')){row.classList.toggle('hovered',row.dataset.layerId===Q.hover);row.setAttribute('aria-selected',String(row.dataset.layerId===S.selectedPart));}
}
function draw(cmd,ctx){const im=image(cmd.image);if(!im||!cmd.matrix)return;ctx.save();ctx.setTransform(...cmd.matrix);ctx.imageSmoothingEnabled=false;ctx.drawImage(im,0,0);ctx.restore();}
function tint(ctx,color){ctx.save();ctx.globalCompositeOperation='source-in';ctx.fillStyle=color;ctx.fillRect(0,0,768,768);ctx.restore();}
function outline(source,color,opacity,ctx){const e=edge.getContext('2d');e.clearRect(0,0,768,768);for(const [dx,dy] of [[-3,0],[3,0],[0,-3],[0,3],[-2,-2],[2,-2],[-2,2],[2,2]])e.drawImage(source,dx,dy);e.save();e.globalCompositeOperation='destination-out';e.drawImage(source,0,0);e.restore();tint(e,color);ctx.save();ctx.globalAlpha=opacity;ctx.drawImage(edge,0,0);ctx.restore();}
function overlay(id,color,selected,f,ctx){const all=drawCommands(f,true),index=all.findIndex(c=>c.id===id);if(index<0)return;const cmd=all[index];
 const a=mask.getContext('2d'),b=visible.getContext('2d');a.clearRect(0,0,768,768);b.clearRect(0,0,768,768);draw(cmd,a);
 if(selected&&Q.xray){tint(a,color);outline(mask,color,.40,ctx);ctx.save();ctx.globalAlpha=.09;ctx.drawImage(mask,0,0);ctx.restore();}
 if(!cmd.visible)return;
 b.drawImage(mask,0,0);b.save();b.globalCompositeOperation='destination-out';for(const c of all.slice(index+1))if(c.visible)draw(c,b);b.restore();tint(b,color);
 ctx.save();ctx.globalAlpha=selected?.26:.12;ctx.drawImage(visible,0,0);ctx.restore();outline(visible,color,selected?.95:.6,ctx);
}
function afterRender(f){if(!S.p||S.crop)return;const ctx=$('character').getContext('2d');if(Q.hover&&Q.hover!==S.selectedPart)overlay(Q.hover,'#b3f2e6',false,f,ctx);if(Q.show&&S.selectedPart)overlay(S.selectedPart,'#ffc66d',true,f,ctx);sync();}
function opened(p){if(Q.project!==p.id){Q.project=p.id;Q.hover=null;}Q.lastKey='';sync();}
$('selection-highlight').onchange=()=>{Q.show=$('selection-highlight').checked;render();};$('selection-xray').onchange=()=>{Q.xray=$('selection-xray').checked;render();};$('selection-clear').onclick=()=>select(null);
$('part-select').onchange=()=>select($('part-select').value,{scroll:true});
$('side-list').addEventListener('click',e=>{const b=e.target.closest('[data-part]');if(b)select(b.dataset.part,{scroll:false});});
$('side-list').addEventListener('pointerover',e=>{const row=e.target.closest('[data-layer-id]');if(row){Q.hover=row.dataset.layerId;render();}});
$('side-list').addEventListener('pointerleave',()=>{if(Q.hover){Q.hover=null;render();}});
$('character').onpointerdown=e=>{if(!S.p||S.crop||rigEditor.state.busy||S.savePromise)return;const ids=hitTest(mouse(e,$('character')));const i=e.altKey&&ids.includes(S.selectedPart)?(ids.indexOf(S.selectedPart)+1)%ids.length:0;select(ids[i]||null);};
$('character').onpointermove=e=>{if(e.buttons)return;const h=hitTest(mouse(e,$('character')))[0]||null;if(h!==Q.hover){Q.hover=h;$('character').style.cursor=h?'pointer':'default';render();}};
$('character').onpointerleave=()=>{if(Q.hover){Q.hover=null;render();}};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.target.closest('input,textarea,select')&&!document.querySelector('dialog[open]'))select(null);});
window.partSelection={state:Q,hitTest,select,afterRender,opened,sync};
if(S.p)opened(S.p);
})();
