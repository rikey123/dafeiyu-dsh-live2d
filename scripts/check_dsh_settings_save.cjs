/* Real DSH settings saves, including a temporary API-mode round trip. Never
 * reads credentials, supplies a dummy key, enables capture, or requests TTS.
 * The original TTS mode is restored; other user settings/keys are preserved. */
const {chromium}=require('../qa/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
// Never silently use a stale manual host: a second instance competes with the
// user's Launcher for the fixed gateway port and has a different private token.
const origin=process.env.DSH_TEST_ORIGIN;
const logPath=process.env.DSH_TEST_ENTRY_LOG;
const output=path.join(root,'.runtime/dsh-acceptance/settings-save.json');
(async()=>{
 assert(origin&&logPath,'Set DSH_TEST_ORIGIN and DSH_TEST_ENTRY_LOG for the existing Launcher instance; do not start another DSH');
 const target=new URL(origin);
 assert(target.protocol==='http:'&&['127.0.0.1','localhost'].includes(target.hostname)&&target.origin===origin,
  'DSH_TEST_ORIGIN must be the exact loopback HTTP origin, without credentials or query');
 const bytes=fs.readFileSync(logPath),log=bytes.toString(bytes[0]===0xff&&bytes[1]===0xfe?'utf16le':'utf8');
 const entries=log.replace(/\x1b\[[0-9;]*m/g,'').match(/https?:\/\/(?:127\.0\.0\.1|localhost):\d+\/\?token=[^\s<>"']+/g)||[];
 const entry=entries.reverse().find(x=>new URL(x).origin===origin);assert(entry,'No current host entry; token not printed');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],writes=[];
 let before,restored=false;
 const report={method:'Real DSH embedded UI, no microphone, model generation or TTS call',saves:[],restored:false};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{const p=new URL(r.url()).pathname;if(p.endsWith('/api/settings')&&r.method()==='PUT')writes.push(p);});
 await page.addInitScript(()=>{
  window.__saveTestMicCalls=0;
  navigator.mediaDevices.getUserMedia=async()=>{window.__saveTestMicCalls++;throw Error('Capture disabled in save QA');};
 });
 const publicState=()=>page.evaluate(async()=>{
  const r=await fetch('/dafeiyu/api/settings');if(!r.ok)throw Error('Settings read failed: '+r.status);
  const s=await r.json();return {mode:s.tts_mode,provider:s.tts_api_provider,voice:s.tts_api_voice,
    ttsKeySet:s.tts_api_key_set,decisionKeySet:s.systemone_ark_api_key_set,harness:s.harness_provider,memory:s.memory_owner};
 });
 try{
  await page.goto(entry,{waitUntil:'domcontentloaded'});
  const fish=page.getByText('大肥鱼',{exact:true}).first();await fish.waitFor({timeout:30000});await fish.click();
  const panel=page.locator('section[aria-label="大肥鱼数字人"]');await panel.waitFor({timeout:30000});
  const ready=()=>panel.locator('.mic-btn:not([disabled])').waitFor({timeout:120000});
  await ready();before=await publicState();assert.equal(before.harness,'dsh');assert.equal(before.memory,'dsh');
  for(const mode of [before.mode,'api',before.mode]){
   await panel.getByRole('button',{name:'设置',exact:true}).click();
   await panel.locator('label').filter({hasText:/^语音合成模式/}).locator('select').selectOption(mode);
   const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/dafeiyu/api/settings'&&r.request().method()==='PUT',{timeout:150000});
   await panel.getByRole('button',{name:'保存设置',exact:true}).click();
   const r=await response;assert.equal(r.status(),200,'Settings save failed; response body and secrets deliberately not logged');
   await panel.locator('.drawer').waitFor({state:'hidden'});await ready();
   const saved=await publicState();assert.equal(saved.mode,mode);assert.equal(saved.provider,before.provider);
   assert.equal(saved.ttsKeySet,before.ttsKeySet);assert.equal(saved.decisionKeySet,before.decisionKeySet);
   report.saves.push({mode,status:r.status()});
  }
  assert.deepEqual(await publicState(),before);restored=true;
  assert.equal(await page.evaluate(()=>window.__saveTestMicCalls),0);assert.deepEqual(errors,[]);
  assert.equal(writes.length,3,'each click must submit exactly once, no automatic save replay');
  console.log('PASS: three real DSH settings saves, including API mode; original mode and key presence preserved');
 }catch(e){report.error=String(e);throw e;}
 finally{
  if(before&&!restored){
   // Restore only the mode, never overwrite concurrently edited API fields or keys.
   restored=await page.evaluate(async mode=>{
    const r=await fetch('/dafeiyu/api/settings',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({tts_mode:mode})});return r.ok;
   },before.mode).catch(()=>false);
  }
  report.restored=restored;fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));
  await browser.close();if(before&&!restored)throw Error('Original mode restoration failed; consult local acceptance report');
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
