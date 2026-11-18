/* Compiled DSH frontend, real Live2D/Edge/Pipecat background interaction. The keyed
 * host shell and model/backend responses are isolated fixtures, not a live
 * DSH/profile or microphone/desktop/cloud acceptance test. */
const {chromium}=require('../qa/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),http=require('node:http'),path=require('node:path');
const root=path.resolve(__dirname,'..'),base='http://127.0.0.1:18876';
const output='E:/Dafeiyu/verification/background-interaction/browser.json';
const shell=String.raw`
<html><head><meta charset="utf-8"></head><body style="margin:0"><main id="main" style="width:1500px;height:1000px"></main>
<script>
const test=window.__panelTest={activePanelId:null,listeners:new Set(),effects:[],dispose:[],errors:[]};
const React={
 createElement(type,props,...children){
  const node=document.createElement(type);
  for(const [key,value]of Object.entries(props||{})){
   if(key==='ref')value.current=node;else if(key==='style')Object.assign(node.style,value);else node.setAttribute(key,value);
  }
  for(const child of children.flat())if(child!=null)node.append(child);
  return node;
 },useRef:()=>({current:null}),useState:()=>['',value=>{if(value)test.errors.push(value);}],useEffect:fn=>test.effects.push(fn),
};
window.__ModuleLoader__={load(definition){definition.factory(()=>React).apply({
 layout:{panelInfo:{subscribe(fn){test.listeners.add(fn);return()=>test.listeners.delete(fn);},getSnapshot:()=>test}},
 on(name,fn){if(name==='dispose')test.dispose.push(fn);},effect(factory){for(const unused of factory())void unused;},
 slots:{inject(name,fn){return fn();},register(options,component){if(options.key==='dafeiyu-live2d')test.entry={options,component};return()=>{};}},
});}};
test.show=()=>{
 if(test.cleanup)return;
 test.activePanelId='dafeiyu-live2d';for(const fn of test.listeners)fn();
 document.getElementById('main').append(test.entry.component(test.entry.options.inject()));
 const cleanups=test.effects.splice(0).map(fn=>fn());test.cleanup=()=>cleanups.forEach(fn=>fn?.());
};
test.hide=()=>{test.activePanelId=null;for(const fn of test.listeners)fn();test.cleanup?.();test.cleanup=null;document.getElementById('main').replaceChildren();};
test.close=()=>{test.hide();for(const fn of test.dispose.splice(0))fn();};
</script><script src="/fixture/client.js"></script></body></html>`;

(async()=>{
 const health=await fetch('http://127.0.0.1:18875/api/screen-fixture',{headers:{'X-Dafeiyu-Plugin-Token':'screen-fixture-only'}});
 assert(health.ok&&(await health.json()).fixture,'start the isolated screen fixture first');
 const {createGatewayProxy,serveStatic}=await import('../plugins/dsh/src/proxy.mjs');
 const proxy=createGatewayProxy({gatewayUrl:'http://127.0.0.1:18875',token:'screen-fixture-only'});
 const roots=[{directory:path.join(root,'web/dist-dsh')},{directory:path.join(root,'web/public/models'),prefix:'models'},{directory:path.join(root,'web/public')}];
 let creationDelay=0;
 const server=http.createServer(async(req,res)=>{
  try{
   const url=new URL(req.url,base),resource=url.pathname;
   if(resource==='/'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(shell);}
   if(resource==='/fixture/client.js'){res.setHeader('Content-Type','application/javascript; charset=utf-8');return res.end(await fs.readFile(path.join(root,'plugins/dsh/src/client.js')));}
   if(resource.startsWith('/dafeiyu/api/')){
    if(req.method==='POST'&&resource==='/dafeiyu/api/sessions'&&creationDelay)await new Promise(resolve=>setTimeout(resolve,creationDelay));
    return proxy.http(req,res,resource.slice('/dafeiyu'.length)+url.search);
   }
   if(resource.startsWith('/dafeiyu/'))return serveStatic(req,res,roots,decodeURIComponent(resource.slice('/dafeiyu/'.length)));
   res.writeHead(404);res.end();
  }catch{res.writeHead(500);res.end('Fixture error');}
 });
 server.on('upgrade',(req,socket,head)=>{const url=new URL(req.url,base);if(url.pathname==='/dafeiyu/ws/voice')void proxy.upgrade(req,socket,head,'/ws/voice'+url.search);else socket.destroy();});
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(18876,'127.0.0.1',resolve);});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const report={method:'Compiled DSH bundle and real Live2D/Pipecat/Edge; synthetic keyed slot, silent microphone and screen; no real DSH profile or paid APIs',cases:[]};
 async function pageFixture(){
  const page=await browser.newPage({viewport:{width:1550,height:1050}}),requests=[],errors=[];
  page.on('request',request=>requests.push({path:new URL(request.url()).pathname,method:request.method()}));
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
   const state=window.__media={mic:0,display:0,contexts:[],fakeContexts:[],sockets:[],tracks:[],raf:0,samplingInterval:0};
   const Audio=window.AudioContext,Socket=window.WebSocket,raf=window.requestAnimationFrame,interval=window.setInterval;
   window.setInterval=(fn,ms,...args)=>{const id=interval(fn,ms,...args);if(ms===1000)state.samplingInterval=id;return id;};
   window.AudioContext=class extends Audio{constructor(...args){super(...args);state.contexts.push(this);}};
   window.WebSocket=class extends Socket{constructor(...args){super(...args);state.sockets.push(this);}};
   window.requestAnimationFrame=fn=>raf.call(window,time=>{state.raf++;fn(time);});
   navigator.mediaDevices.getUserMedia=async()=>{state.mic++;const context=new Audio();state.fakeContexts.push(context);const stream=context.createMediaStreamDestination().stream;state.tracks.push(...stream.getTracks());return stream;};
   navigator.mediaDevices.getDisplayMedia=async()=>{state.display++;const canvas=document.createElement('canvas');canvas.width=960;canvas.height=540;const ctx=canvas.getContext('2d');ctx.fillStyle='#234';ctx.fillRect(0,0,960,540);const stream=canvas.captureStream(1);state.tracks.push(...stream.getTracks());return stream;};
  });
  await page.goto(base,{waitUntil:'load'});
  return {page,requests,errors};
 }
 const ready=page=>page.waitForFunction(()=>window.__savedHost?.shadowRoot?.querySelector('.mic-btn')?.disabled===false,null,{timeout:45000});
 const saveHost=page=>page.waitForFunction(()=>{const section=document.querySelector('section[aria-label="大肥鱼数字人"]');const host=section?.lastElementChild?.firstElementChild;if(host?.shadowRoot){window.__savedHost=host;return true;}return false;});
 const inactive=page=>page.waitForFunction(()=>window.__media.sockets.every(ws=>ws.readyState===3)&&window.__media.contexts.every(context=>context.state==='closed')&&window.__media.tracks.every(track=>track.readyState==='ended'));
 const fixtureState=async(patch)=>{
  const response=await fetch('http://127.0.0.1:18875/api/screen-fixture',{method:patch?'PUT':'GET',headers:{'X-Dafeiyu-Plugin-Token':'screen-fixture-only',...(patch?{'Content-Type':'application/json'}:{})},...(patch?{body:JSON.stringify(patch)}:{})});
  assert(response.ok);return response.json();
 };
 const waitFixture=async(predicate)=>{for(let n=0;n<160;n++){const state=await fixtureState();if(predicate(state))return state;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Background fixture condition timed out');};
 try{
  const {page,requests,errors}=await pageFixture();
  await page.evaluate(()=>window.__panelTest.show());await saveHost(page);await ready(page);
  await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({state:'attached',timeout:90000});
  await page.evaluate(()=>{window.__savedCanvas=window.__savedHost.shadowRoot.querySelector('.avatar-canvas canvas');window.__savedApp=window.__savedHost.shadowRoot.querySelector('.app');});
  const initialModels=requests.filter(item=>item.path.includes('/models/')).length;
  await page.getByPlaceholder('说点什么，或开启语音...').fill('未发送的草稿，请保留');
  await page.getByRole('button',{name:'开启语音',exact:true}).click();
  await page.getByRole('button',{name:'正在聆听',exact:true}).waitFor();
  await page.getByRole('button',{name:'开始屏幕陪玩',exact:true}).click();
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await page.getByLabel('开口意愿阈值',{exact:true}).fill('0.65');
  const session=await page.evaluate(()=>new URL(window.__media.sockets.find(ws=>ws.readyState===1).url).searchParams.get('session_id'));
  const mediaBefore=await page.evaluate(()=>({sockets:window.__media.sockets.length,contexts:window.__media.contexts.length,tracks:window.__media.tracks.length}));
  await page.evaluate(()=>window.__panelTest.hide());
  await page.waitForFunction(()=>window.__savedHost.shadowRoot.querySelector('.avatar-canvas').dataset.rendering==='paused');
  assert(await page.evaluate(()=>window.__savedHost.shadowRoot.querySelector('.app').dataset.active==='false'&&window.__savedHost.shadowRoot.querySelector('.avatar-canvas').dataset.rendering==='paused'));
  await page.waitForTimeout(200);const paused=await page.evaluate(()=>window.__media.raf);await page.waitForTimeout(400);
  assert((await page.evaluate(()=>window.__media.raf))-paused<3,'hidden panel kept an animation loop running');
  assert(await page.evaluate(()=>window.__media.sockets.filter(ws=>ws.readyState===1).length===1&&window.__media.contexts.every(context=>context.state==='running')&&window.__media.tracks.every(track=>track.readyState==='live')),'hiding interrupted authorized interaction');
  const before=await fixtureState();await fixtureState({proactive:'strong'});
  // In this fixture the last 1000ms interval is the display sampling fallback.
  // Disable it to prove socket pulses, not a foreground-only JS timer, drive capture.
  await page.evaluate(()=>window.clearInterval(window.__media.samplingInterval));
  await waitFixture(state=>state.proactive_images>before.proactive_images&&state.playback_acks>before.playback_acks);
  await fixtureState({proactive:'wait'});
  report.cases.push('detached panel continues server-pulsed screen sampling with its browser sampling interval disabled, System One admission, DSH fixture reply, real audio worklet consumption ACK and microphone without reauthorization');
  await page.evaluate(()=>window.__panelTest.show());await ready(page);
  assert(await page.evaluate(()=>document.querySelector('section[aria-label="大肥鱼数字人"]').lastElementChild.firstElementChild===window.__savedHost&&window.__savedHost.shadowRoot.querySelector('.app')===window.__savedApp&&window.__savedHost.shadowRoot.querySelector('.avatar-canvas canvas')===window.__savedCanvas));
  assert.equal(await page.getByLabel('开口意愿阈值',{exact:true}).inputValue(),'0.65');
  assert.deepEqual(await page.evaluate(()=>({mic:window.__media.mic,display:window.__media.display})),{mic:1,display:1});
  assert.deepEqual(await page.evaluate(()=>({sockets:window.__media.sockets.length,contexts:window.__media.contexts.length,tracks:window.__media.tracks.length})),mediaBefore);
  await page.getByRole('button',{name:'录制一段',exact:true}).click();
  await page.getByRole('button',{name:'完成录音',exact:true}).waitFor();
  await page.evaluate(()=>window.__panelTest.hide());await page.waitForTimeout(100);
  await page.evaluate(()=>window.__panelTest.show());await ready(page);
  await page.getByRole('button',{name:'完成录音',exact:true}).waitFor();
  await page.getByRole('button',{name:'完成录音',exact:true}).click();
  await page.getByRole('button',{name:'录制一段',exact:true}).waitFor();
  report.cases.push('voice enrollment continues across a keyed page switch, stops explicitly and keeps the completed recording');
  await page.getByRole('button',{name:'关闭',exact:true}).click();
  assert.equal(await page.getByPlaceholder('说点什么，或开启语音...').inputValue(),'未发送的草稿，请保留');
  assert.equal(await page.evaluate(()=>new URL(window.__media.sockets.find(ws=>ws.readyState===1).url).searchParams.get('session_id')),session);
  assert.equal(requests.filter(item=>item.path==='/dafeiyu/api/sessions'&&item.method==='POST').length,1);
  assert.equal(requests.filter(item=>item.path==='/dafeiyu/api/settings'&&item.method==='GET').length,1);
  assert.equal(requests.filter(item=>item.path.includes('/models/')).length,initialModels);
  report.cases.push('keyed panel return preserves exact App/Live2D canvas, draft, unsaved settings and session; no model/settings reload or automatic capture');
  report.cases.push('away pauses only visual rendering; authorized capture and the same websocket/audio output are retained');
  // Equivalent to visibilitychange without OS-level focus assumptions in headless Edge.
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));});
  await page.waitForFunction(()=>window.__savedHost.shadowRoot.querySelector('.avatar-canvas').dataset.rendering==='paused');
  const hiddenBefore=await fixtureState();
  await waitFixture(state=>state.judgment_calls>hiddenBefore.judgment_calls);
  assert(await page.evaluate(()=>window.__media.sockets.filter(ws=>ws.readyState===1).length===1&&window.__media.contexts.some(context=>context.state==='running')&&window.__media.tracks.some(track=>track.kind==='video'&&track.readyState==='live')));
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'));});
  await ready(page);
  for(let i=0;i<4;i++){await page.evaluate(()=>{window.__panelTest.hide();window.__panelTest.show();});}
  await ready(page);await page.waitForTimeout(300);
  assert.equal(await page.evaluate(()=>window.__media.sockets.filter(ws=>ws.readyState===1).length),1);
  assert.equal(requests.filter(item=>item.path==='/dafeiyu/api/sessions'&&item.method==='POST').length,1);
  assert.deepEqual(errors,[]);assert.deepEqual(await page.evaluate(()=>window.__panelTest.errors),[]);
  report.cases.push('browser visibility and rapid keyed switches reuse the session with one live connection');
  // An ordinary reply already in flight must finish even after its page is gone.
  const replyBefore=await fixtureState();await fixtureState({reply_delay_ms:800,tts_samples:24000});
  await page.getByPlaceholder('说点什么，或开启语音...').fill('看看这个合成画面');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.evaluate(()=>window.__panelTest.hide());
  await waitFixture(state=>state.normal_images>replyBefore.normal_images&&state.playback_acks>replyBefore.playback_acks);
  await page.evaluate(()=>window.__panelTest.show());await ready(page);
  assert(await page.evaluate(()=>!window.__savedHost.shadowRoot.textContent.includes('已打断')));
  await fixtureState({reply_delay_ms:0,tts_samples:4800});
  report.cases.push('normal in-flight reply obtains a fresh requested screen snapshot while detached and finishes real playback without interruption');
  await page.evaluate(()=>Promise.all(window.__media.contexts.filter(context=>context.state==='running').map(context=>context.suspend())));
  const micBefore=await page.evaluate(()=>window.__media.mic);
  await page.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true}).click();
  await page.getByRole('button',{name:'开始屏幕陪玩',exact:true}).click();
  await page.waitForFunction(()=>window.__media.contexts.some(context=>context.state==='running'));
  await page.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.__media.mic),micBefore);
  report.cases.push('explicit screen-only restart after return unlocks audio output without enabling the microphone');
  await page.getByRole('button',{name:'新对话',exact:true}).click();
  await page.waitForFunction(previous=>window.__media.sockets.some(ws=>ws.readyState===1&&new URL(ws.url).searchParams.get('session_id')!==previous),session);
  await ready(page);
  assert.equal(requests.filter(item=>item.path==='/dafeiyu/api/sessions'&&item.method==='POST').length,2);
  assert.notEqual(await page.evaluate(()=>new URL(window.__media.sockets.find(ws=>ws.readyState===1).url).searchParams.get('session_id')),session);
  report.cases.push('explicit New Chat still creates a new session rather than unintentionally resuming the retained one');
  await page.evaluate(()=>window.__panelTest.close());await inactive(page);
  assert(await page.evaluate(()=>window.__savedHost.shadowRoot.childNodes.length===0));
  await page.evaluate(()=>Promise.all(window.__media.fakeContexts.map(context=>context.close())));await page.close();
  report.cases.push('plugin disposal finally destroys the retained root and media');
  creationDelay=900;
  const pending=await pageFixture();
  const creating=pending.page.waitForRequest(request=>request.method()==='POST'&&new URL(request.url()).pathname==='/dafeiyu/api/sessions');
  await pending.page.evaluate(()=>window.__panelTest.show());await saveHost(pending.page);await creating;
  await pending.page.evaluate(()=>window.__panelTest.hide());await pending.page.waitForTimeout(100);await pending.page.evaluate(()=>window.__panelTest.show());await ready(pending.page);
  assert.equal(pending.requests.filter(item=>item.path==='/dafeiyu/api/sessions'&&item.method==='POST').length,1);
  await pending.page.evaluate(()=>window.__panelTest.close());await inactive(pending.page);await pending.page.close();
  report.cases.push('hidden during delayed session creation preserves the pending POST and first connection without an orphan replacement');
  report.passed=true;report.real_desktop_captured=false;report.paid_api_called=false;
  console.log('PASS: '+report.cases.length+' compiled panel-retention cases');
 }catch(error){report.error=error.message;throw error;}
 finally{await fs.mkdir(path.dirname(output),{recursive:true});await fs.writeFile(output,JSON.stringify(report,null,2));await browser.close();proxy.dispose();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
