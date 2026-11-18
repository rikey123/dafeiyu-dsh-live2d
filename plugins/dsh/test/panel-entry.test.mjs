import test from 'node:test';
import assert from 'node:assert/strict';
import {createPanelMount} from '../src/panel-entry.js';
const tick=()=>new Promise(done=>setImmediate(done));
function fixture(){
  const node=()=>({style:{},children:[],appendChild(child){child.parent=this;this.children.push(child);},replaceChildren(...children){this.children=children;},remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}});
  const host=node();host.ownerDocument={createElement:node};return host;
}
test('install gate retains panel visibility and mounts original app exactly once',async()=>{
  const host=fixture(),active=[];let onReady,mounts=0,stops=0,installerStops=0;
  const mount=createPanelMount({loadInstaller:async()=>({mountInstallView:async(_host,options)=>{onReady=options.onReady;return {dispose(){installerStops++;}};}}),loadApp:async()=>({mountDafeiyu(_host,options){assert.equal(options.active,false);mounts++;return {setActive:v=>active.push(v),dispose:()=>stops++};}})});
  const app=mount(host,{active:true});await tick();app.setActive(false);assert.equal(mounts,0);onReady();onReady();await tick();assert.equal(mounts,1);assert(installerStops);app.setActive(true);assert.equal(active.at(-1),true);app.dispose();app.dispose();assert.equal(stops,1);
});
test('disposing before installer resolves cannot mount late app or retain installer',async()=>{
  const host=fixture();let finish,onReady,mounts=0,stops=0;
  const mount=createPanelMount({loadInstaller:async()=>({mountInstallView:async(_host,options)=>{onReady=options.onReady;await new Promise(done=>{finish=done;});return {dispose:()=>stops++};}}),loadApp:async()=>{mounts++;}});
  const app=mount(host);await tick();app.dispose();onReady();finish();await tick();assert.equal(mounts,0);assert.equal(stops,1);assert.equal(host.children.length,0);
});
