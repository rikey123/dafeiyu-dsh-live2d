/* Explicit paid opt-in. The ONLY image is a generated test canvas: never the
 * owner's desktop, webcam or microphone. Original screen settings are restored. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('../qa/node_modules/playwright');
if (process.env.DSH_TEST_SCREEN_LIVE !== '1') {
  console.log('Not run: set DSH_TEST_SCREEN_LIVE=1 for one real image judgment and, if admitted, one native DSH reply/TTS.');
  process.exit(0);
}
function wire(payload) {
  const bytes = Buffer.from(payload), i = bytes.indexOf('{"label"');
  if (i >= 0) try { return JSON.parse(bytes.subarray(i).toString()); } catch {}
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout=30000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) {const value=await fn(); if(value) return value; await delay(100);}
  throw Error('Live screen acceptance timed out');
}
(async () => {
  const root=path.resolve(__dirname,'..'), out=path.join(root,'.runtime/dsh-acceptance');
  fs.mkdirSync(out,{recursive:true});
  const bytes=fs.readFileSync(process.env.DSH_TEST_ENTRY_LOG || path.join(root,'.runtime/dsh-active.log'));
  const text=bytes.toString(bytes[0]===255&&bytes[1]===254?'utf16le':'utf8');
  const entry=[...text.matchAll(/https?:\/\/(?:127\.0\.0\.1|localhost):\d+\/\?token=[^\s<>"']+/g)].at(-1)?.[0];
  assert(entry,'owned host entry required');
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1500,height:1000}});
  let original, changed=false, session;
  const events=[], sent=[], errors=[], started=Date.now();
  page.on('pageerror',e=>errors.push(e.message));
  page.on('websocket',ws=>{
    if(new URL(ws.url()).pathname!=='/dafeiyu/ws/voice') return;
    session=new URL(ws.url()).searchParams.get('session_id');
    ws.on('framereceived',f=>{const m=wire(f.payload);if(m) events.push(m);});
    ws.on('framesent',f=>{const m=wire(f.payload);if(m) sent.push(m);});
  });
  await page.addInitScript(()=>{
    window.__testDisplayCalls=0; window.__testMicCalls=0; window.__testTracks=[];
    navigator.mediaDevices.getUserMedia=async()=>{window.__testMicCalls++;throw Error('microphone disabled');};
    navigator.mediaDevices.getDisplayMedia=async()=>{
      window.__testDisplayCalls++;
      const canvas=document.createElement('canvas');canvas.width=960;canvas.height=540;
      const ctx=canvas.getContext('2d');ctx.fillStyle='#152338';ctx.fillRect(0,0,960,540);
      ctx.textAlign='center';ctx.fillStyle='#ffd65b';ctx.font='bold 90px sans-serif';ctx.fillText('VICTORY!',480,190);
      ctx.fillStyle='#fff';ctx.font='bold 55px sans-serif';ctx.fillText('团队胜利 · 10 : 0',480,295);
      ctx.font='24px sans-serif';ctx.fillText('陪玩链路测试：模拟游戏结算画面，并非真实游戏',480,420);
      const stream=canvas.captureStream(5);window.__testTracks.push(...stream.getTracks());
      // Keep the source alive without mutating pixels; local differencing must
      // prevent subsequent judgments on the identical image.
      window.__testCanvas=canvas;return stream;
    };
  });
  const api=(method,body)=>page.evaluate(async ({method,body})=>{
    const r=await fetch('/dafeiyu/api/settings',{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok) throw Error(`settings HTTP ${r.status}`);return r.json();
  },{method,body});
  try {
    await page.goto(entry,{waitUntil:'domcontentloaded'});
    await page.getByText('大肥鱼',{exact:true}).first().waitFor({timeout:45000});
    original=await api('GET');
    assert(original.systemone_enabled,'enable/configure System One in owner settings before this live test');
    assert(original.screen_model_ready,'native DSH model is not image-capable');
    const testWait=process.env.DSH_TEST_SCREEN_WAIT_THRESHOLD;
    const waitThreshold=testWait===undefined ? original.screen_companion_wait_threshold : Number(testWait);
    assert(Number.isFinite(waitThreshold)&&waitThreshold>=0&&waitThreshold<=.5,'invalid explicit test wait threshold');
    await api('PUT',{screen_companion_enabled:true,screen_companion_wait_threshold:waitThreshold});changed=true;
    await page.getByText('大肥鱼',{exact:true}).first().click();
    const panel=page.locator('section[aria-label="大肥鱼数字人"]');
    await until(()=>panel.getByRole('button',{name:'开始屏幕陪玩',exact:true}).isEnabled().catch(()=>false),120000);
    assert.equal(await page.evaluate(()=>window.__testDisplayCalls),0,'no automatic capture');
    await panel.getByRole('button',{name:'开始屏幕陪玩',exact:true}).click();
    const status=await until(()=>events.map(m=>m.data).find(d=>d?.type==='voice.screen.status'&&['accepted','waiting','unavailable'].includes(d.status)),20000);
    let confirmed=false;
    if(status.status==='accepted') {
      await until(()=>sent.find(m=>m.data?.t==='voice.playback'&&m.data.d?.completed),180000);
      confirmed=true;
    }
    const stop=panel.getByRole('button',{name:'● 屏幕分享中 · 立即停止',exact:true});
    if(await stop.count()) await stop.click();
    await until(()=>page.evaluate(()=>window.__testTracks.every(t=>t.readyState==='ended')));
    const counts=await page.evaluate(()=>({synthetic_display_calls:window.__testDisplayCalls,microphone_calls:window.__testMicCalls}));
    const images=sent.filter(m=>m.data?.t==='voice.screen.frame').length;
    assert.equal(counts.microphone_calls,0);assert.equal(counts.synthetic_display_calls,1);assert.equal(images,1);
    const report={synthetic_image_only:true,real_desktop_captured:false,real_systemone:true,
      decision:status,test_wait_threshold:waitThreshold,native_reply_playback_confirmed:confirmed,model:original.llm_model,
      uploaded_frames:images,elapsed_ms:Date.now()-started,...counts,errors};
    fs.writeFileSync(path.join(out,'screen-live-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
    assert.notEqual(status.status,'unavailable',`real image judgment unavailable: ${status.reason}`);
    assert.equal(errors.length,0);
  } finally {
    if(changed) await api('PUT',{screen_companion_enabled:original.screen_companion_enabled,
      screen_companion_wait_threshold:original.screen_companion_wait_threshold});
    if(session) await page.evaluate(async id=>{await fetch('/dafeiyu/api/sessions/'+encodeURIComponent(id),{method:'DELETE'});},session).catch(()=>{});
    await browser.close();
  }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
