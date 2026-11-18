/* Compiled browser + real RTVI/gateway + native DSH attachment adapter.
 * Synthetic canvas and offline route only: NOT evidence of a paid model's decisions. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire}=require('node:module'),{pathToFileURL}=require('node:url');
const {chromium}=require(process.env.DAFEIYU_QA_MODULES || 'G:/dafeiyu/qa/node_modules/playwright');
const out=process.env.DAFEIYU_SCREEN_TOOL_QA || 'E:/Dafeiyu/qa/dsh-screen-tool-20261115';
fs.mkdirSync(out,{recursive:true});process.env.TEMP=path.join(out,'tmp');process.env.TMP=process.env.TEMP;fs.mkdirSync(process.env.TEMP,{recursive:true});
const base='http://127.0.0.1:18876',token='screen-tool-fixture-only',headers={'X-Dafeiyu-Plugin-Token':token};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,label) {const deadline=Date.now()+25000;while(Date.now()<deadline){if(await fn())return;await pause(70);}throw Error(label);}
async function state(){const res=await fetch(base+'/api/screen-tool-fixture',{headers});assert(res.ok);const data=await res.json();assert(data.fixture);return data;}
(async()=>{
  await state();
  const modules=process.env.DSH_RUNTIME_MODULES_ROOT || 'C:/Users/Administrator/AppData/Roaming/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules';
  const requireDSH=createRequire(path.join(modules,'@deepseek-ai/dsh/package.json'));
  const load=name=>import(pathToFileURL(requireDSH.resolve(name)).href);
  const [{Context},{LocalAttachmentStore},{defineTool},adapter]=await Promise.all([
    load('@deepseek-ai/cordis'),load('@deepseek-ai/dsh-attachment-local'),load('@deepseek-ai/dsh-tools'),
    import('../plugins/dsh/src/screen-tool.mjs'),
  ]);
  const context=new Context(),attachments=new LocalAttachmentStore(context,{dshHome:path.join(out,'native-attachments')});
  const ctx={attachments,llm:{async resolveModelInfo(){return {inputModalities:['text','image']};}},agents:{get:()=>undefined}};
  const tool=defineTool(adapter.screenToolDefinition(ctx,{snapshot:(id,signal)=>adapter.requestScreenSnapshot({gatewayUrl:base,token},id,signal)}));
  const browser=await chromium.launch({channel:'msedge',headless:true,args:['--enable-gpu','--use-angle=d3d11']});
  const page=await browser.newPage({viewport:{width:1550,height:1000},extraHTTPHeaders:headers}),errors=[];
  const wireEvents=[];
  page.on('websocket',ws=>{for(const direction of ['framereceived','framesent'])ws.on(direction,frame=>{
    const bytes=Buffer.from(frame.payload),i=bytes.indexOf('{"label"');if(i<0)return;
    try{const v=JSON.parse(bytes.subarray(i).toString());wireEvents.push({direction,type:v.type,data:v.data?.t?{t:v.data.t,...(v.data.t==='voice.screen'?{active:v.data.d.active}:{})}:v.data?.type?{type:v.data.type,purpose:v.data.purpose,reason:v.data.reason}:undefined});}catch{}
  });});
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
    window.__screenToolTest={grants:0,microphones:0,tracks:[],requests:[],encodes:[]};
    window.addEventListener('screen-companion-request',e=>window.__screenToolTest.requests.push(e.detail));
    const toBlob=HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob=function(callback,...args){const start=Date.now();return toBlob.call(this,blob=>{window.__screenToolTest.encodes.push({elapsed:Date.now()-start,size:blob?.size});callback(blob);},...args);};
    navigator.mediaDevices.getUserMedia=async()=>{window.__screenToolTest.microphones++;throw Error('Real capture forbidden');};
    navigator.mediaDevices.getDisplayMedia=async()=>{
      window.__screenToolTest.grants++;
      const canvas=document.createElement('canvas');canvas.width=960;canvas.height=540;
      const ctx=canvas.getContext('2d');ctx.fillStyle='#12213b';ctx.fillRect(0,0,960,540);ctx.fillStyle='white';ctx.font='42px sans-serif';ctx.fillText('SYNTHETIC SCREEN TOOL A',80,240);
      window.__screenToolTest.canvas=canvas;const stream=canvas.captureStream(8);window.__screenToolTest.tracks.push(...stream.getTracks());return stream;
    };
  });
  const report={method:'Real compiled UI/Edge/RTVI/gateway/native DSH tool and attachment adapter; offline model route; synthetic canvas; fixture snapshot budget 5000ms (not a latency measurement)',cases:[]};
  try {
    await page.goto(base,{waitUntil:'domcontentloaded'});
    await page.waitForLoadState('networkidle');
    const start=page.getByRole('button',{name:'开始屏幕陪玩',exact:true});
    await until(()=>start.isEnabled(),'sharing must work with System One disabled');
    await until(async()=>(await state()).providers.length===1,'live capture provider missing');
    const id=(await state()).providers[0];
    const agent={id,session:{id,header:{},requestHeader:()=>({config:{provider:'offline',model:'canvas-fixture'}})}};
    const capture=()=>tool.execute({}, {agent,signal:new AbortController().signal});
    assert.deepEqual(await capture(),{available:false,reason:'not_shared'});
    assert.equal(await page.evaluate(()=>window.__screenToolTest.grants),0);report.cases.push('no sharing means no image and no permission acquisition');
    await start.click();await page.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true}).waitFor();
    await pause(300);
    const first=await capture();assert.equal(first.available,true,JSON.stringify(first));assert.equal(first.image.width,960);assert.equal(first.image.height,540);
    assert(exists(attachments.imageHostPath(first.image)));assert.equal(tool.output.render({},first)[1].type,'image');
    report.cases.push('DSH tool -> authenticated gateway -> actual browser snapshot -> native stored image, with System One and auto-intent disabled');
    await page.evaluate(()=>{const c=window.__screenToolTest.canvas,ctx=c.getContext('2d');ctx.fillStyle='#9b3211';ctx.fillRect(0,0,c.width,c.height);ctx.fillStyle='white';ctx.fillText('SYNTHETIC SCREEN TOOL B',80,240);});
    await pause(300);
    const second=await capture();assert.equal(second.available,true);assert.notEqual(first.image.attachmentId,second.image.attachmentId);report.cases.push('second request obtains changed live content, not the old frame');
    const child={id:'offline-delegation',session:{id:'offline-delegation',header:{origin:'subagent',parentSession:id},requestHeader:agent.session.requestHeader}};
    ctx.agents.get=key=>key===id?agent:undefined;
    assert.equal((await tool.execute({}, {agent:child,signal:new AbortController().signal})).available,true);report.cases.push('native delegated child resolves only its parent sharing session');
    const unrelated={...agent,id:'unrelated',session:{...agent.session,id:'unrelated'}};
    assert.deepEqual(await tool.execute({}, {agent:unrelated,signal:new AbortController().signal}),{available:false,reason:'no_connection'});
    report.cases.push('unrelated conversation cannot read the shared stream');
    await page.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true}).click();
    await until(()=>page.evaluate(()=>window.__screenToolTest.tracks.every(t=>t.readyState==='ended')),'shared tracks not released');
    await pause(150);assert.deepEqual(await capture(),{available:false,reason:'not_shared'});report.cases.push('revocation returns no image and never revives the old capture');
    report.media=await page.evaluate(()=>({syntheticGrants:window.__screenToolTest.grants,microphoneRequests:window.__screenToolTest.microphones}));
    assert.deepEqual(report.media,{syntheticGrants:1,microphoneRequests:0});assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(out,'browser.png'),fullPage:true});
    await page.close();await until(async()=>(await state()).providers.length===0,'provider leaked after disconnect');
    assert.deepEqual(await capture(),{available:false,reason:'no_connection'});report.cases.push('disconnect unregisters the exact live provider');
    report.passed=true;report.realDesktopCaptured=false;report.paidModelCalled=false;report.pageErrors=errors;
    console.log(JSON.stringify(report,null,2));
  } catch(error) {report.error=error.stack;report.pageErrors=errors;report.wireEvents=wireEvents;report.capture=await page.evaluate(()=>({requests:window.__screenToolTest.requests,encodes:window.__screenToolTest.encodes})).catch(()=>undefined);await page.screenshot({path:path.join(out,'browser-failure.png'),fullPage:true}).catch(()=>{});throw error;}
  finally {fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));await browser.close();}
  function exists(file){return fs.existsSync(file);}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
