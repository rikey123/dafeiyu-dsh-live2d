/* Real compiled UI/Edge/Pipecat, but controlled local decision/bridge/tone
 * fixtures only. No real desktop, microphone, DSH credentials or paid models. */
const {chromium}=require('../qa/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base='http://127.0.0.1:18875', headers={'X-Dafeiyu-Plugin-Token':'screen-fixture-only'};
const output='E:/Dafeiyu/verification/screen-request/browser.json';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,label,timeout=25000){const end=Date.now()+timeout;while(Date.now()<end){if(await fn())return;await sleep(60);}throw Error(label);}
function wire(payload){const bytes=Buffer.from(payload),i=bytes.indexOf('{"label"');if(i>=0)try{return JSON.parse(bytes.subarray(i).toString());}catch{}}
async function api(method='GET',body){const r=await fetch(base+'/api/screen-fixture',{method,headers:{...headers,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});assert(r.ok,'isolated fixture required');const v=await r.json();assert(v.fixture);return v;}
(async()=>{
 await api();
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1550,height:1100},extraHTTPHeaders:headers});
 const events=[],sent=[],errors=[];
 let session;
 page.on('pageerror',e=>errors.push(e.message));
 page.on('websocket',ws=>{session=new URL(ws.url()).searchParams.get('session_id');ws.on('framereceived',f=>{const e=wire(f.payload);if(e)events.push(e);});ws.on('framesent',f=>{const e=wire(f.payload);if(e)sent.push(e);});});
 await page.addInitScript(()=>{
  window.__screenTest={display:0,mic:0,tracks:[],contexts:[]};
  const Audio=window.AudioContext;
  window.AudioContext=class extends Audio {constructor(...args){super(...args);window.__screenTest.contexts.push(this);}};
  navigator.mediaDevices.getUserMedia=async()=>{window.__screenTest.mic++;throw Error('Fixture microphone refused');};
  navigator.mediaDevices.getDisplayMedia=async()=>{
   window.__screenTest.display++;
   const canvas=document.createElement('canvas');canvas.width=960;canvas.height=540;
   const ctx=canvas.getContext('2d');ctx.fillStyle='#19314b';ctx.fillRect(0,0,960,540);
   ctx.fillStyle='#fff';ctx.font='48px sans-serif';ctx.fillText('SYNTHETIC SCREEN TEST',100,250);
   window.__screenTest.canvas=canvas;const stream=canvas.captureStream(5);window.__screenTest.tracks.push(...stream.getTracks());return stream;
  };
 });
 const report={method:'Real compiled frontend + Edge + protobuf/Pipecat/worklet; synthetic screen/decision/bridge/TTS fixtures, NOT live DSH vision acceptance',cases:[]};
 const message=()=>page.getByPlaceholder('说点什么，或开启语音...');
 const ask=async()=>{await message().fill('你能看到我的屏幕吗？请看看这个图表。');await page.getByRole('button',{name:'发送',exact:true}).click();};
 const ackCount=()=>sent.filter(e=>e.data?.t==='voice.playback'&&e.data.d?.completed).length;
 try{
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'开始屏幕陪玩',exact:true}).waitFor();
  await until(()=>page.getByRole('button',{name:'开始屏幕陪玩',exact:true}).isEnabled(),'screen not ready');
  assert.equal(await page.evaluate(()=>window.__screenTest.display),0);
  await page.getByRole('button',{name:'开始屏幕陪玩',exact:true}).click();
  await until(()=>events.some(e=>e.data?.reason==='low_desire'),'first judgment missing');
  const diagnostics=page.getByRole('region',{name:'屏幕陪玩',exact:true});
  await diagnostics.locator('summary').click();
  await until(async()=>{const text=await diagnostics.textContent();return text.includes('开口意愿未达到阈值')&&text.includes('生效阈值 0.900');},'visible threshold diagnostics missing');
  const first=await api();assert.equal(first.judgment_calls,1);assert.equal(first.proactive_images,0);
  report.cases.push('explicit grant only; low proactive desire produces no bridge/TTS');
  await api('PUT',{proactive:'ambiguous'});
  await until(async()=>{const s=await api();return s.proactive_images===1&&s.playback_acks>=1;},'static refresh did not recover proactive reply',20000);
  assert(events.some(e=>e.data?.reason==='strong_desire'));
  const accepted=events.map(e=>e.data).find(e=>e?.reason==='strong_desire');
  assert(accepted.intent_confidence<accepted.intent_confidence_threshold);
  assert(accepted.non_wait_probability>.99);
  await until(async()=>{const text=await diagnostics.textContent();return text.includes('意图语气分布置信度 0.471')&&text.includes('不单独决定开口');},'ambiguous purpose diagnostics missing');
  assert(sent.filter(e=>e.data?.t==='voice.screen.frame').length>=2);
  report.cases.push('unchanged screen refresh and ambiguous comment/cheer purpose reach proactive reply and real playback ACK');
  const beforeAck=ackCount(),beforeSnapshots=sent.filter(e=>e.data?.t==='voice.screen.snapshot').length;
  await ask();
  await until(async()=>{const s=await api();return s.normal_images===1&&ackCount()>beforeAck;},'requested current frame failed');
  assert.equal(sent.filter(e=>e.data?.t==='voice.screen.snapshot').length-beforeSnapshots,1);
  assert(events.some(e=>e.data?.type==='voice.screen.request'));
  assert(events.some(e=>e.data?.reason==='request_attached'));
  report.cases.push('user intent forces fresh unchanged frame during proactive cooldown and answers once');
  // A microphone failure must not revoke an independent display grant.
  const mic=page.locator('.mic-btn');await mic.click();
  await until(()=>page.evaluate(()=>window.__screenTest.mic===1),'fake mic acquisition not attempted');
  assert.equal(await page.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true}).count(),1);
  assert(await page.evaluate(()=>window.__screenTest.tracks.every(t=>t.readyState==='live')));
  report.cases.push('microphone toggle/failure leaves independently authorized screen sharing active');
  await page.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true}).click();
  await until(()=>page.evaluate(()=>window.__screenTest.tracks.every(t=>t.readyState==='ended')),'tracks leaked');
  await until(async()=>!(await diagnostics.textContent()).includes('最近主动判断'),'old decision retained after screen off');
  const noShare=await api(),sentBefore=sent.length;
  await ask();
  await until(()=>events.some(e=>e.data?.reason==='request_not_shared'),'no-share explanation missing');
  await until(async()=>{const s=await api();return s.tts_calls>noShare.tts_calls;},'normal question lost after screen off');
  assert.equal((await api()).normal_images,noShare.normal_images);
  assert(!sent.slice(sentBefore).some(e=>e.data?.t==='voice.screen.snapshot'));
  assert.equal(await page.evaluate(()=>window.__screenTest.display),1,'no automatic permission reacquisition');
  report.cases.push('off releases tracks, later screen question sends no image and never reacquires permission');
  assert.equal(errors.length,0);report.fixture=await api();report.session_metrics=await page.evaluate(async id=>{const r=await fetch('/api/voice/metrics/'+encodeURIComponent(id));return r.json();},session);
  report.real_desktop_captured=false;report.paid_api_called=false;report.passed=true;
  console.log('PASS: '+report.cases.length+' compiled browser screen cases; no real capture or paid API');
 }catch(e){report.error=e.message;report.fixture=await api().catch(()=>undefined);report.media=await page.evaluate(()=>({contexts:window.__screenTest.contexts.map(context=>({state:context.state,time:context.currentTime})),display:window.__screenTest.display,hidden:document.hidden})).catch(()=>undefined);report.client_acks=ackCount();report.errors=errors;console.error(JSON.stringify({fixture:report.fixture,media:report.media,acks:report.client_acks,errors}));throw e;}
 finally{fs.mkdirSync(require('node:path').dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
