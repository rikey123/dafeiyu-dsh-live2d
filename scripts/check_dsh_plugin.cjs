/* Real DSH/browser smoke. No microphone capture. The explicit
 * DSH_TEST_LIVE_TURN=1 opt-in makes one short request using the host model. */
const { chromium } = require('../qa/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const origin = process.env.DSH_TEST_ORIGIN || 'http://127.0.0.1:3081';
  const liveTurn = process.env.DSH_TEST_LIVE_TURN === '1';
  const log = process.env.DSH_TEST_ENTRY_LOG || path.join(root,'.runtime','dsh-acceptance.log');
  const logBytes=fs.readFileSync(log);
  // Windows PowerShell redirection uses UTF-16LE; native launcher logs use UTF-8.
  const logText=logBytes.toString(logBytes[0]===0xff&&logBytes[1]===0xfe?'utf16le':'utf8');
  const entries = logText.replace(/\x1b\[[0-9;]*m/g,'').match(/https?:\/\/(?:127\.0\.0\.1|localhost):\d+\/\?token=[^\s<>"']+/g) || [];
  const entry = entries.reverse().find(x => new URL(x).origin === origin);
  if (!entry) throw new Error('No entry URL in this owned acceptance log (token will not be printed)');
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const page = await browser.newPage({viewport:{width:1600,height:1000}});
  const errors=[], failures=[], requests=[], sockets=[];
  page.on('websocket',ws=>{
    if(new URL(ws.url()).pathname!=='/dafeiyu/ws/voice') return;
    const record={opened:Date.now(),sent:[],received:[]};sockets.push(record);
    ws.on('framesent',f=>record.sent.push({at:Date.now(),bytes:Buffer.byteLength(f.payload)}));
    ws.on('framereceived',f=>record.received.push({at:Date.now(),bytes:Buffer.byteLength(f.payload),audio:Buffer.isBuffer(f.payload)&&f.payload[0]===0x12}));
    ws.on('socketerror',e=>record.error=e);ws.on('close',()=>record.closed=Date.now());
  });
  page.on('pageerror',e=>errors.push(e.message));
  page.on('requestfailed',r=>failures.push({path:new URL(r.url()).pathname,error:r.failure()?.errorText}));
  page.on('request',r=>{try{requests.push(new URL(r.url()).pathname);}catch{}});
  await page.addInitScript(() => {
    window.__dafeiyuMicAttempts=0;
    window.__dafeiyuSockets=[]; window.__dafeiyuContexts=[];
    const Socket=window.WebSocket, Audio=window.AudioContext;
    window.WebSocket=class extends Socket {constructor(...args){super(...args);window.__dafeiyuSockets.push(this);}};
    window.AudioContext=class extends Audio {constructor(...args){super(...args);window.__dafeiyuContexts.push(this);}};
    if(navigator.mediaDevices) navigator.mediaDevices.getUserMedia=async()=>{ window.__dafeiyuMicAttempts++; throw new Error('Microphone deliberately disabled in no-audio acceptance'); };
  });
  try {
    await page.goto(entry,{waitUntil:'domcontentloaded'});
    await page.waitForTimeout(1500);
    // First-run notice in a fresh isolated DSH home. Never click model login/consent.
    for (const name of ['我知道了','开始使用','继续使用','继续','Got it']) {
      const button=page.getByRole('button',{name,exact:true});
      if(await button.count() && await button.first().isVisible()) await button.first().click();
    }
    const fish=page.getByText('大肥鱼',{exact:true}).first();
    await fish.waitFor({timeout:30000}); await fish.click();
    const panel=page.locator('section[aria-label="大肥鱼数字人"]');
    await panel.waitFor({timeout:30000});
    await panel.locator('canvas').first().waitFor({state:'attached',timeout:90000});
    // Real backend + DSH-owned session + Pipecat protobuf ready, not just canvas paint.
    await page.waitForFunction(() => [...document.querySelectorAll('*')].some(host => {
      const mic=host.shadowRoot?.querySelector('.mic-btn');return mic && !mic.disabled;
    }),{},{timeout:120000});
    assert.equal(await page.evaluate(()=>window.__dafeiyuMicAttempts),0,'initial mount must not open microphone');
    assert(!requests.some(x=>x==='/api/memories'||x==='/dafeiyu/api/memories'),'legacy memory must not be requested');
    assert(requests.some(x=>x==='/dafeiyu/api/settings'),'settings must use the plugin prefix');
    assert(!requests.some(x=>x==='/api/settings'),'standalone URLs must not leak into DSH');
    const status=await page.evaluate(async()=>{
      const response=await fetch('/dafeiyu/api/settings'); const settings=await response.json();
      return {status:response.status,harness_provider:settings.harness_provider,memory_owner:settings.memory_owner,llm_model:settings.llm_model};
    });
    assert.equal(status.status,200); assert.equal(status.harness_provider,'dsh'); assert.equal(status.memory_owner,'dsh');
    const memoryStatus=await page.evaluate(async()=>(await fetch('/dafeiyu/api/memories')).status);
    assert.equal(memoryStatus,410);
    const nativeSession=await page.evaluate(async()=>{
      const create=await fetch('/dafeiyu/api/sessions',{method:'POST'});const row=await create.json();
      if(create.status!==201) return {created:create.status};
      const history=await fetch(`/dafeiyu/api/sessions/${encodeURIComponent(row.id)}/messages`);
      const messages=await history.json();const archived=await fetch(`/dafeiyu/api/sessions/${encodeURIComponent(row.id)}`,{method:'DELETE'});
      return {created:create.status,history:history.status,empty:Array.isArray(messages)&&messages.length===0,archive:archived.status};
    });
    assert.deepEqual(nativeSession,{created:201,history:200,empty:true,archive:200});
    let liveReply=null;
    if(liveTurn) {
      const session=await page.evaluate(()=>{
        const socket=window.__dafeiyuSockets.find(s=>s.readyState===1&&new URL(s.url).pathname==='/dafeiyu/ws/voice');
        return new URL(socket.url).searchParams.get('session_id');
      });
      const prompt='这是语音连接验收，请不要调用任何工具，只回复：语音连接正常。';
      await panel.locator('.compose > input').fill(prompt);
      await panel.getByRole('button',{name:'发送',exact:true}).click();
      // Generated captions do not prove playback. Wait for the native-session
      // projection, which is written only after real worklet consumption ACKs.
      let messages=[];
      const deadline=Date.now()+180000;
      while(Date.now()<deadline) {
        messages=await page.evaluate(async session=>{
          const response=await fetch(`/dafeiyu/api/sessions/${encodeURIComponent(session)}/messages`);
          if(!response.ok) throw new Error('Native session history unavailable');
          return response.json();
        },session);
        if(messages.some(row=>row.role==='user'&&row.content===prompt)&&messages.some(row=>row.role==='assistant'&&row.content.trim())) break;
        await page.waitForTimeout(1000);
      }
      assert(messages.some(row=>row.role==='user'&&row.content===prompt),'native user turn must be persisted');
      assert(messages.some(row=>row.role==='assistant'&&row.content.trim()),'native assistant history must contain a playback-confirmed prefix');
      const audio=sockets.flatMap(s=>s.received).filter(frame=>frame.audio);
      assert(audio.length>0,'real PCM frames must reach the browser');
      liveReply={model:status.llm_model,audio_frames:audio.length,audio_wire_bytes:audio.reduce((total,frame)=>total+frame.bytes,0),confirmed_assistant_chars:messages.filter(row=>row.role==='assistant').reduce((total,row)=>total+row.content.length,0),playback_confirmed:true};
    }
    await fs.promises.mkdir(path.join(root,'.runtime/dsh-acceptance'),{recursive:true});
    await page.screenshot({path:path.join(root,'.runtime/dsh-acceptance/panel.png'),fullPage:true});
    const connected=await page.evaluate(()=>window.__dafeiyuSockets.some(s=>s.readyState===1&&new URL(s.url).pathname==='/dafeiyu/ws/voice'));
    assert(connected,'same-origin speech WebSocket must complete ready handshake');
    await page.getByRole('button',{name:'插件',exact:true}).click();
    // DSH's own connection must remain alive; only the plugin's voice sockets
    // belong to this lifecycle assertion.
    await page.waitForFunction(()=>window.__dafeiyuSockets.filter(s=>new URL(s.url).pathname==='/dafeiyu/ws/voice').every(s=>s.readyState===3)&&window.__dafeiyuContexts.every(c=>c.state==='closed'),{},{timeout:15000});
    await fish.click();
    await page.waitForFunction(() => [...document.querySelectorAll('*')].some(host => {
      const mic=host.shadowRoot?.querySelector('.mic-btn');return mic && !mic.disabled;
    }),{},{timeout:30000});
    assert.equal(await page.evaluate(()=>window.__dafeiyuMicAttempts),0,'reactivating must not reacquire microphone');
    await page.getByRole('button',{name:'插件',exact:true}).click();
    await page.waitForFunction(()=>window.__dafeiyuSockets.filter(s=>new URL(s.url).pathname==='/dafeiyu/ws/voice').every(s=>s.readyState===3)&&window.__dafeiyuContexts.every(c=>c.state==='closed'),{},{timeout:15000});
    const report={status,rendered:true,voice_ready:true,native_session:nativeSession,live_reply:liveReply,inactive_releases_audio:true,reactivation_ready:true,microphone_attempts:0,legacy_memory_requested_by_frontend:false,memory_route_status:memoryStatus,errors,failures,asset_requests:requests.filter(x=>x.startsWith('/dafeiyu/')).length};
    await fs.promises.writeFile(path.join(root,'.runtime/dsh-acceptance/report.json'),JSON.stringify(report,null,2));
    if(errors.length) throw new Error(`Browser errors: ${JSON.stringify(errors)}`);
    console.log(JSON.stringify(report,null,2));
  } catch(error) {
    await fs.promises.mkdir(path.join(root,'.runtime/dsh-acceptance'),{recursive:true});
    await page.screenshot({path:path.join(root,'.runtime/dsh-acceptance/failure.png'),fullPage:true}).catch(()=>{});
    const diagnostics=await page.evaluate(()=>({text:document.body.innerText.slice(-7000),shadow:[...document.querySelectorAll('*')].filter(h=>h.shadowRoot).map(h=>h.shadowRoot.textContent.slice(-6000)),dialogs:[...document.querySelectorAll('[role="dialog"]')].map(b=>b.textContent)})).catch(()=>({}));
    await fs.promises.writeFile(path.join(root,'.runtime/dsh-acceptance/failure.json'),JSON.stringify({message:error.message,errors,failures,sockets,diagnostics},null,2));
    throw error;
  } finally { await browser.close(); }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
