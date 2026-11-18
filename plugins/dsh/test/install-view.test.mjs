import test from 'node:test';
import assert from 'node:assert/strict';
import {mountInstallView} from '../src/install-view.js';
class Node {
  constructor(tag='host', doc) { this.tag=tag; this.ownerDocument=doc; this.children=[]; this.events={}; this.value=''; this.checked=false; this.hidden=false; this.disabled=false; this.textContent=''; }
  appendChild(n) { this.children.push(n); return n; }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute() {}
  addEventListener(type, fn) { (this.events[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.events[type]=(this.events[type] || []).filter(x=>x!==fn); }
  dispatch(type) { for (const fn of this.events[type] || []) fn({preventDefault(){}}); }
  attachShadow() { return this.shadowRoot=new Node('shadow', this.ownerDocument); }
}
const makeHost=()=>{ const doc={createElement: tag=>new Node(tag,doc)}; return new Node('host',doc); };
const all=node=>[node,...node.children.flatMap(all)];
const find=(host, predicate)=>all(host.shadowRoot).find(predicate);
const response=data=>({ok:true,json:async()=>data});
const base={available:true,ready:false,stage:'idle',assets:{avatar:false,cubismCore:false,sensevoiceModel:true,vadModel:true}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('progress and ready fire once through polling', async()=>{
  const host=makeHost(); let ready=0, calls=0;
  const view=await mountInstallView(host,{onReady:()=>ready++,fetch:async()=>response(++calls===1?{...base,stage:'running',progress:{downloaded:50,total:100}}:{...base,ready:true})});
  assert.ok(find(host,n=>n.textContent.includes('50 字节 / 100 字节')));
  await new Promise(resolve=>setTimeout(resolve,1600));
  assert.equal(ready,1); view.dispose(); assert.equal(ready,1);
});
test('failed installation retries with defaults and completion offers continue', async()=>{
  const host=makeHost(); const requests=[]; let ready=0;
  await mountInstallView(host,{onReady:()=>ready++,fetch:async(path,options)=>{ requests.push([path,options]); return response(requests.length===1?{...base,stage:'failed'}:requests.length===2?{...base,stage:'complete'}:{...base,ready:true}); }});
  const form=find(host,n=>n.tag==='form'); form.dispatch('submit'); await flush();
  const body=JSON.parse(requests[1][1].body); assert.equal(body.source,'china'); assert.equal(body.acceptCoreLicense,false); assert.equal(body.homeDir,'E:/DafeiyuCompanion'); assert.equal(body.models,undefined);
  assert.ok(find(host,n=>n.textContent.includes('角色：缺失')));
  const button=find(host,n=>n.textContent==='暂不导入，进入设置'); assert.equal(button.hidden,false); button.dispatch('click'); await flush();
  assert.equal(requests[2][0],'/dafeiyu/install/continue'); assert.equal(ready,1);
});
test('dispose prevents late ready', async()=>{
  const host=makeHost(); let resolve, ready=0, calls=0;
  const view=await mountInstallView(host,{onReady:()=>ready++,fetch:()=>++calls===1?Promise.resolve(response(base)):new Promise(r=>resolve=r)});
  find(host,n=>n.tag==='form').dispatch('submit'); view.dispose(); resolve(response({...base,ready:true})); await flush(); assert.equal(ready,0);
});
test('source mode enters directly and unsafe HTTP detail is hidden', async()=>{
  let ready=0; await mountInstallView(makeHost(),{onReady:()=>ready++,fetch:async()=>response({available:false})}); assert.equal(ready,1);
  const host=makeHost(); let calls=0;
  const view=await mountInstallView(host,{fetch:async()=>++calls===1?response(base):{ok:false,json:async()=>({detail:'https://secret.example/path'})}});
  find(host,n=>n.tag==='form').dispatch('submit'); await flush();
  assert.ok(find(host,n=>n.textContent.includes('操作未完成'))); assert.equal(all(host.shadowRoot).some(n=>n.textContent.includes('secret.example')),false);
  view.dispose();
});

test('configured home is locked, GPU models are opt-in and official links are present', async()=>{
  const host=makeHost(); const requests=[];
  const view=await mountInstallView(host,{fetch:async(path, options)=>{requests.push([path,options]); return response({...base,homeConfigured:true,homeDir:'E:/fixed',stage:'failed',message:'secret https://example.com'});}});
  const home=find(host,n=>n.tag==='input' && n.value==='E:/fixed'); assert.equal(home.disabled,true);
  assert.ok(find(host,n=>n.href==='https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html'));
  assert.ok(find(host,n=>n.href==='https://www.live2d.com/en/download/cubism-sdk/'));
  assert.ok(find(host,n=>n.textContent.includes('data/logs/installation.log')));
  assert.equal(all(host.shadowRoot).some(n=>n.textContent.includes('secret https://')),false);
  const indexLabel=find(host,n=>n.tag==='label' && n.children.some(c=>c.textContent==='IndexTTS（GPU）'));
  const gptLabel=find(host,n=>n.tag==='label' && n.children.some(c=>c.textContent==='GPT-SoVITS（GPU）'));
  assert.equal(indexLabel.children[0].checked,false); assert.equal(gptLabel.children[0].checked,false);
  indexLabel.children[0].checked=true; gptLabel.children[0].checked=true;
  find(host,n=>n.tag==='form').dispatch('submit'); await flush();
  assert.deepEqual(JSON.parse(requests[1][1].body).models,['index','gpt-sovits']); assert.equal(home.disabled,true); view.dispose();
});
test('failed status polling retries and reaches ready', async()=>{
  const host=makeHost(); let calls=0, ready=0;
  const view=await mountInstallView(host,{onReady:()=>ready++,fetch:async()=>{if (++calls===1) throw new Error('network'); return response({...base,ready:true});}});
  assert.ok(find(host,n=>n.textContent.includes('自动重试')));
  await new Promise(resolve=>setTimeout(resolve,1600)); assert.equal(ready,1); assert.equal(calls,2); view.dispose();
});

test('character sources are direct links, but never trigger automatic downloads', async()=>{
  const host=makeHost(), requests=[];
  const view=await mountInstallView(host,{fetch:async(path, options)=>{requests.push([path,options]);return response(base);}});
  const hrefs=[
    'https://www.bilibili.com/video/BV1KmxY66EZ3/',
    'https://github.com/YJackie-Li/DeepSeek-chan',
    'https://github.com/YJackie-Li/DeepSeek-chan/archive/824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f.zip',
    'https://github.com/YJackie-Li/DeepSeek-chan/blob/824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f/README.md',
  ];
  for(const href of hrefs){
    const link=find(host,n=>n.tag==='a'&&n.href===href);
    assert.ok(link);assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');
  }
  assert.ok(find(host,n=>n.textContent.includes('社区仓库未核实为作者本人维护')));
  assert.ok(find(host,n=>n.textContent.includes('神宫凉子')));
  assert.deepEqual(requests.map(([path])=>path),['/dafeiyu/install']);
  find(host,n=>n.tag==='form').dispatch('submit');await flush();
  const body=JSON.parse(requests[1][1].body);
  assert.equal(body.avatarUrl,undefined);assert.equal(body.avatarSha256,undefined);
  assert.equal(body.acceptAvatarLicense,false);
  view.dispose();
});

test('one explicit checkbox installs the pinned avatar without a ZIP path or URL', async()=>{
  const host=makeHost(),requests=[];
  const view=await mountInstallView(host,{fetch:async(path,options)=>{requests.push([path,options]);return response(base);}});
  const label=find(host,n=>n.tag==='label'&&n.children.some(c=>c.textContent.includes('自动下载安装大肥鱼')));
  assert.ok(label);const checkbox=label.children[0];assert.equal(checkbox.checked,false);
  assert.equal(requests.length,1);checkbox.checked=true;
  find(host,n=>n.tag==='form').dispatch('submit');await flush();
  const body=JSON.parse(requests[1][1].body);
  assert.equal(body.avatarPreset,'deepseek-chan');assert.equal(body.acceptAvatarLicense,true);
  assert.equal(body.avatarUrl,undefined);assert.equal(body.avatarSha256,undefined);assert.equal(body.avatarArchive,undefined);
  view.dispose();
});

test('automatic/manual conflicts are visible and a manual import still works after opting out', async()=>{
  const host=makeHost(),requests=[];
  const view=await mountInstallView(host,{fetch:async(path,options)=>{requests.push([path,options]);return response(base);}});
  const auto=find(host,n=>n.tag==='label'&&n.children.some(c=>c.textContent.includes('自动下载安装大肥鱼'))).children[0];
  const archive=find(host,n=>n.tag==='label'&&n.children.some(c=>c.textContent.includes('本地角色 ZIP 路径'))).children[1];
  auto.checked=true;archive.value='E:/Assets/character.zip';
  find(host,n=>n.tag==='form').dispatch('submit');await flush();assert.equal(requests.length,1);
  assert.ok(find(host,n=>n.textContent.includes('自动安装与手动导入只能选择一种')));
  auto.checked=false;find(host,n=>n.tag==='form').dispatch('submit');await flush();
  assert.equal(JSON.parse(requests[1][1].body).avatarArchive,archive.value);
  assert.equal(JSON.parse(requests[1][1].body).avatarPreset,undefined);view.dispose();
});
