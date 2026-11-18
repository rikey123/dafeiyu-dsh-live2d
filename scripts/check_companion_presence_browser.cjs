/* Compiled UI/Edge/RTVI/TTS/ACK; only synthetic media and offline model fixtures. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.DAFEIYU_QA_MODULES || 'G:/dafeiyu/qa/node_modules/playwright');
const base='http://127.0.0.1:18878',headers={'X-Dafeiyu-Plugin-Token':'presence-fixture-only'},out=process.env.DAFEIYU_PRESENCE_QA || 'E:/Dafeiyu/qa/companion-presence-20261116';
fs.mkdirSync(out,{recursive:true});
process.env.TEMP=path.join(out,'browser-tmp');process.env.TMP=process.env.TEMP;fs.mkdirSync(process.env.TEMP,{recursive:true});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,label,timeout=25000){const deadline=Date.now()+timeout;while(Date.now()<deadline){if(await fn())return;await pause(80);}throw Error(label);}
async function api(route='/api/presence-fixture',method='GET',body){const r=await fetch(base+route,{method,headers:{...headers,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});assert(r.ok,'fixture API '+r.status);return r.json();}
const fixture=()=>api();const change=body=>api('/api/presence-fixture','PUT',body);
function wire(payload){const b=Buffer.from(payload),i=b.indexOf('{"label"');if(i>=0)try{return JSON.parse(b.subarray(i).toString());}catch{}}
(async()=>{
 assert.equal((await fixture()).fixture,true);
 const browser=await chromium.launch({channel:'msedge',headless:true,args:['--enable-gpu','--use-angle=d3d11']}),page=await browser.newPage({viewport:{width:1550,height:1050},extraHTTPHeaders:headers});
 const events=[],sent=[],errors=[],report={method:'Real compiled UI/Edge/Pipecat/PCM ACK; synthetic canvas + offline HTTP/SSE decision/DSH/TTS; only local scheduling clock advanced',cases:[]};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('websocket',ws=>{ws.on('framereceived',f=>{const v=wire(f.payload);if(v)events.push(v);});ws.on('framesent',f=>{const v=wire(f.payload);if(v)sent.push(v);});});
 await page.addInitScript(()=>{
  window.__presence={grants:0,microphones:0,tracks:[]};
  navigator.mediaDevices.getUserMedia=async()=>{window.__presence.microphones++;throw Error('Real microphone forbidden');};
  navigator.mediaDevices.getDisplayMedia=async()=>{
   window.__presence.grants++;const c=document.createElement('canvas');c.width=960;c.height=540;
   const ctx=c.getContext('2d');ctx.fillStyle='#152a46';ctx.fillRect(0,0,960,540);ctx.fillStyle='white';ctx.font='40px sans-serif';ctx.fillText('SYNTHETIC COMPANION SCREEN',50,260);
   window.__presence.canvas=c;const stream=c.captureStream(8);window.__presence.tracks.push(...stream.getTracks());return stream;
  };
 });
 const start=()=>page.getByRole('button',{name:'开始屏幕陪玩',exact:true});
 const stop=()=>page.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true});
 async function ready(){await until(()=>start().isEnabled(),'voice/share not ready');}
 async function open(){await page.getByRole('button',{name:'设置',exact:true}).click();await page.locator('.drawer').waitFor();}
 async function save(){await page.getByRole('button',{name:'保存设置',exact:true}).click();await page.locator('.drawer').waitFor({state:'hidden'});await ready();}
 try{
  await page.goto(base,{waitUntil:'domcontentloaded'});await ready();
  assert.equal(await page.evaluate(()=>window.__presence.grants),0);
  await start().click();await until(async()=>{const s=await fixture();return s.judgment_calls>0&&s.persona_seen&&s.interests_seen;},'Jev did not see active native persona/interests');
  assert.equal((await fixture()).vision_calls,0);await stop().click();
  report.cases.push('Jev screen judgment uses active native persona and saved interests; low desire makes no DSH/TTS request');
  await open();await page.getByRole('combobox',{name:'屏幕陪伴模式'}).selectOption('direct');
  await page.getByLabel('启用 System One 判断',{exact:true}).uncheck();
  assert.equal(await page.getByLabel('共同兴趣',{exact:true}).inputValue(),'OFFLINE_INTERESTS_星露谷与音乐视频');
  assert.equal(await page.getByText('每小时最多 DSH 看画面次数',{exact:true}).count(),1);
  await save();assert.equal((await api('/api/settings')).screen_companion_mode,'direct');
  await change({silence:true});const directBefore=await fixture();await start().click();
  await until(async()=>(await fixture()).direct_calls>directBefore.direct_calls,'direct screen not routed to DSH');await pause(800);
  let current=await fixture();assert.equal(current.judgment_calls,directBefore.judgment_calls);assert.equal(current.tts_calls,directBefore.tts_calls);
  assert.equal(current.decision_calls,directBefore.decision_calls);
  assert(!events.some(e=>e.type==='error'&&/empty|no audio|generation failed/i.test(JSON.stringify(e))));
  report.cases.push('direct mode bypasses screen Jev call; successful empty SSE means silence, without TTS/error');
  await change({silence:false,advance_s:31});const ackBefore=current.playback_acks;
  await until(async()=>(await fixture()).playback_acks>ackBefore,'direct speech did not reach actual playback ACK');
  assert.equal((await fixture()).judgment_calls,directBefore.judgment_calls);assert.equal((await fixture()).decision_calls,directBefore.decision_calls);await stop().click();
  report.cases.push('later direct screen reply reaches original PCM player and real consumption ACK');
  await open();await page.getByLabel('空闲时主动聊天',{exact:true}).check();
  const after=page.getByLabel('无互动多久后主动说话（秒）',{exact:true});await after.fill('');
  await page.getByRole('button',{name:'保存设置',exact:true}).click();
  assert.equal(await after.evaluate(el=>el.validity.valid),false);assert.equal((await api('/api/settings')).idle_companion_enabled,false);
  await after.fill('30');await save();
  const idleBefore=await fixture(),grantsBefore=await page.evaluate(()=>window.__presence.grants);
  await change({advance_s:61});
  await until(async()=>{const s=await fixture();return s.idle_calls>idleBefore.idle_calls&&s.playback_acks>idleBefore.playback_acks;},'idle text opportunity did not speak');
  current=await fixture();assert.equal(current.idle_images,idleBefore.idle_images);assert.equal(current.idle_interests_seen,true);
  assert.equal(await page.evaluate(()=>window.__presence.grants),grantsBefore);
  report.cases.push('independent idle timer speaks with interests and no shared screen, without acquiring a capture permission');
  await change({busy:true,advance_s:61});const count=current.idle_calls;
  await until(()=>events.some(e=>e.data?.type==='voice.idle'&&e.data.reason==='busy'),'native busy skip diagnosis missing');
  assert.equal((await fixture()).idle_calls,count);
  await change({busy:false,advance_s:61});await until(async()=>(await fixture()).idle_calls>count,'idle never recovered after native task finished');
  report.cases.push('native busy tasks suppress optional idle opportunities without cancellation, later opportunities recover');
  await open();await page.getByRole('combobox',{name:'屏幕陪伴模式'}).selectOption('systemone');await page.getByLabel('启用 System One 判断',{exact:true}).check();await save();
  const imageBefore=await fixture();await start().click();await stop().waitFor();await pause(350);
  await change({advance_s:61});
  await until(async()=>{const s=await fixture();return s.idle_images>imageBefore.idle_images&&s.playback_acks>imageBefore.playback_acks;},'idle fresh screen path failed');
  assert(sent.some(e=>e.data?.t==='voice.screen.snapshot'));
  assert(events.some(e=>e.data?.type==='voice.screen.request'&&e.data.purpose==='idle'));
  report.cases.push('idle opportunity obtains a fresh authorized synthetic screen and reaches existing speech/ACK route');
  await stop().click();await until(()=>page.evaluate(()=>window.__presence.tracks.every(t=>t.readyState==='ended')),'capture leaked after off');
  await open();assert((await page.locator('.drawer').textContent()).includes('安静后主动搭话'));await page.screenshot({path:path.join(out,'settings.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>window.__presence.microphones),0);assert.deepEqual(errors,[]);
  report.state=await fixture();report.realDesktopCaptured=false;report.paidModelCalled=false;report.passed=true;report.pageErrors=errors;
  console.log('PASS '+report.cases.length+' companion presence browser cases, synthetic only');
 }catch(e){report.error=e.message;report.state=await fixture().catch(()=>undefined);report.pageErrors=errors;report.eventTypes=events.map(e=>({type:e.type,data:e.data?.type,reason:e.data?.reason})).slice(-80);await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e;}
 finally{fs.writeFileSync(path.join(out,'browser-presence.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
