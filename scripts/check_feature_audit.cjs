/* Same compiled frontend + real local inference. LLM/API responses are labelled
 * loopback fixtures; no paid services, human identity or acoustic accuracy claims.
 * Requires the isolated acceptance gateway on 8875, never the user's database.
 */
const fs = require('node:fs'), assert = require('node:assert/strict')
const { chromium } = require('../qa/node_modules/playwright')
const base = 'http://127.0.0.1:8875'
const out = process.env.AUDIT_OUTPUT_DIR || 'E:/Dafeiyu/verification/feature-audit'
const report = { date: '2026-11-14', method: 'Real Edge frontend, PCM worklet playback and local models; controlled loopback LLM and API fixtures. No paid API or human microphone accuracy claim.', cases: [] }
fs.mkdirSync(out, {recursive: true})
const suffix = process.env.AUDIT_CASE_FILTER ? '-'+process.env.AUDIT_CASE_FILTER.replace(/[^a-z0-9]/gi,'-').slice(0,60) : ''
const save = () => fs.writeFileSync(out+'/browser-audit'+suffix+'.json', JSON.stringify(report,null,2))
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms))

;(async()=>{
 const browser = await chromium.launch({channel:'msedge',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--use-file-for-fake-audio-capture=E:/Dafeiyu/verification/feature-audit/microphone.wav']})
 const context = await browser.newContext({viewport:{width:1440,height:1100},permissions:['microphone']})
 await context.addInitScript(()=>{
  window.__audit = {consumed:0,micCalls:0,tracks:[],maxMouth:0}
  const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
  navigator.mediaDevices.getUserMedia = async c=>{window.__audit.micCalls++;const s=await original(c);window.__audit.tracks.push(...s.getTracks());return s}
  const Worklet=window.AudioWorkletNode
  window.AudioWorkletNode=class extends Worklet {
   constructor(...args){super(...args);this.port.addEventListener('message',event=>{if(event.data?.event==='consumed')window.__audit.consumed+=event.data.samples||0})}
  }
 })
 const page=await context.newPage(), events=[], sent=[], pageErrors=[]
 let audioFrames=0, sessionId
 page.on('pageerror',e=>pageErrors.push(e.message))
 function wire(payload){
  const b=Buffer.from(payload), offset=b.indexOf(Buffer.from('{"label"'))
  if(offset>=0){try{return JSON.parse(b.subarray(offset).toString('utf8'))}catch{}}
 }
 page.on('websocket',socket=>{
  socket.on('framereceived',({payload})=>{const b=Buffer.from(payload);if(b[0]===18)audioFrames++;const e=wire(payload);if(e)events.push(e)})
  socket.on('framesent',({payload})=>{const e=wire(payload);if(e)sent.push(e)})
 })
 page.on('response',async r=>{if(r.url().endsWith('/api/sessions') && r.request().method()==='POST')sessionId=(await r.json()).id})
 const wait=async(test,label,timeout=30000)=>{
  const end=Date.now()+timeout;while(Date.now()<end){if(await test())return;await delay(100)}throw Error(label)
 }
 const api=async(path,init)=>{const r=await fetch(base+path,init);if(!r.ok)throw Error(`${path}: HTTP ${r.status}`);return r.json()}
 const ready=()=>page.waitForFunction(()=>document.querySelector('.mic-btn')?.disabled===false,null,{timeout:30000})
 const settings=async()=>{if(!await page.locator('.drawer').isVisible())await page.getByRole('button',{name:'设置',exact:true}).click()}
 const select=(title)=>page.locator('label').filter({hasText:new RegExp('^'+title)}).locator('select')
 const input=(title)=>page.locator('label').filter({hasText:new RegExp('^'+title)}).locator('input')
 async function configure({mode,model,conversation='duplex',preview=false,url}){
  await settings()
  await select('语音对话方式').selectOption(conversation)
  if(conversation!=='moss_live'){
   if(mode)await select('语音合成模式').selectOption(mode)
   if(model)await select('GPU 语音模型').selectOption(model)
   if(url)await input('GPU 语音服务地址').fill(url)
  }
  await page.getByRole('checkbox',{name:'更快响应插话（实验）',exact:true}).setChecked(preview)
  await page.getByRole('button',{name:'保存设置',exact:true}).click()
  await page.locator('.drawer').waitFor({state:'hidden'})
  if(conversation!=='moss_live')await ready()
 }
 async function health(port){try{return await (await fetch(`http://127.0.0.1:${port}/health`)).json()}catch{return null}}
 async function gpu(name){let h;await wait(async()=>{h=await health(8770);if(h?.state==='error')throw Error(h.detail);return h?.ready&&h.model_name===name},'GPU did not prepare '+name,200000);return h}
 async function speak(label,{expectError=false,timeout=180000}={}){
  const at=Date.now(), i=events.length, j=sent.length, before=audioFrames
  const previousIds=new Set((await api(`/api/sessions/${sessionId}/messages`)).map(m=>m.id))
  const consumed=await page.evaluate(()=>window.__audit.consumed)
  await page.getByPlaceholder('说点什么，或开启语音...').fill('功能检查：'+label)
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await wait(()=>events.slice(i).some(e=>e.type==='error'||e.data?.type==='voice.playback.boundary'),'No playback or diagnostic for '+label,timeout)
  const newEvents=()=>events.slice(i)
  const errors=newEvents().filter(e=>e.type==='error')
  if(expectError){await delay(500);return {audioFrames:audioFrames-before,errors:newEvents().filter(e=>e.type==='error').map(e=>e.data)}}
  assert.equal(errors.length,0,JSON.stringify(errors.map(e=>e.data)))
  await wait(()=>sent.slice(j).some(e=>e.data?.t==='voice.playback'),'No actual playback receipt for '+label,20000)
  const after=await page.evaluate(()=>({consumed:window.__audit.consumed,maxMouth:window.__audit.maxMouth}))
  assert(audioFrames>before,'No protobuf audio frames')
  assert(after.consumed>consumed,'Worklet did not consume PCM')
  let saved
  await wait(async()=>{saved=(await api(`/api/sessions/${sessionId}/messages`)).find(m=>m.role==='assistant'&&!previousIds.has(m.id));return !!saved},'Playback receipt did not persist assistant history',10000)
  return {elapsedMs:Date.now()-at,audioFrames:audioFrames-before,consumedSamples:after.consumed-consumed,maxMouth:after.maxMouth,savedAssistantId:saved.id,boundaries:newEvents().filter(e=>e.data?.type==='voice.playback.boundary').map(e=>e.data)}
 }
 async function check(name,fn){
  if(process.env.AUDIT_CASE_FILTER && !new RegExp(process.env.AUDIT_CASE_FILTER,'i').test(name))return
  console.log('CHECK '+name)
  const at=Date.now();try{const detail=await fn();report.cases.push({name,status:'passed',elapsedMs:Date.now()-at,detail});console.log('PASS '+name)}
  catch(e){report.cases.push({name,status:'failed',elapsedMs:Date.now()-at,error:String(e),detail:e.auditDetail});console.log('FAIL '+name+': '+e.message);await page.screenshot({path:out+'/failure-'+report.cases.length+'.png'}).catch(()=>{})}
  save()
 }
 try{
  await wait(async()=>{try{return (await api('/api/health')).status==='ok'}catch{return false}},'Isolated acceptance gateway unavailable',30000)
  await page.goto(base);await ready()
  await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({timeout:90000})
  await page.evaluate(()=>{
   const proto=window.PIXI.utils.EventEmitter.prototype,original=proto.emit
   proto.emit=function(...args){const result=original.apply(this,args);if(args[0]==='beforeModelUpdate'&&this.coreModel)window.__audit.maxMouth=Math.max(window.__audit.maxMouth,this.coreModel.getParameterValueById('ParamMouthOpenY'));return result}
  })
  await check('GPU GPT-SoVITS preload, frontend playback and history ACK',async()=>{
   const h=await gpu('GPT-SoVITS-v5-turbo');assert(h.device==='cuda'&&h.warmed_up&&h.cuda_graph_active)
   return {health:h,playback:await speak('GPU 预热后播放')}
  })
  await check('Both acoustic lip profiles initialize and play GPU audio',async()=>{
   await configure({})
   const profiles=[]
   for(const value of ['airi','local-vits']){
    await settings();await page.getByLabel('口型声线',{exact:true}).selectOption(value);await ready()
    await wait(async()=>{const text=await page.locator('.drawer').innerText();return text.includes(value==='airi'?'通用元音模板':'旧 VITS 专用')},'Lip profile did not initialize')
    await page.getByRole('button',{name:'关闭',exact:true}).click()
    profiles.push({value,...await speak('口型 '+value)})
   }
   return {profiles,calibrationAccuracy:'Not measured for GPT-SoVITS voice; original local profile was VITS-specific.'}
  })
  await check('CPU MOSS ONNX frontend save, model load, audio and ACK',async()=>{
   await configure({mode:'cpu'})
   await wait(async()=>!!(await health(8772))?.configured,'CPU sidecar unavailable',30000)
   const result=await speak('CPU 语音');const h=await health(8772);assert(h.ready&&h.device==='cpu'&&h.backend==='onnx')
   assert.equal(await health(8770),null,'GPU service should stop in CPU mode')
   return {health:h,playback:result}
  })
  await check('Pipeline (half duplex) selectable and actual output works',async()=>{
   await configure({mode:'cpu',conversation:'pipeline'})
   return {saved:(await api('/api/settings')).conversation_mode,playback:await speak('轮流说话')}
  })
  await check('Early ASR preview toggle, synthetic microphone, real ASR and PCM reply',async()=>{
   await configure({mode:'cpu',preview:true})
   const i=events.length,before=audioFrames
   await page.getByRole('button',{name:'开启语音',exact:true}).click()
   await page.getByRole('button',{name:'正在聆听',exact:true}).waitFor()
   await wait(()=>events.slice(i).some(e=>e.type==='user-transcription'),'File-backed microphone produced no transcription',25000)
   await wait(()=>audioFrames>before,'Recognized microphone input produced no audio',30000)
   await page.getByRole('button',{name:'正在聆听',exact:true}).click()
   await wait(async()=>{const h=await health(8766);return h?.streaming_asr?.loaded},'Online ASR was not actually loaded',10000)
   return {speechHealth:await health(8766),events:events.slice(i).filter(e=>['user-transcription','user-started-speaking','bot-started-speaking'].includes(e.type)),input:'File-backed synthetic speech, not human acoustic validation'}
  })
  await check('Owner voice frontend upload/enroll/enable/delete with isolated profile',async()=>{
   await configure({mode:'cpu',preview:false})
   await settings()
   const toggle=page.getByRole('checkbox',{name:'仅回应本人声音',exact:true})
   if((await api('/api/voice/owner/status')).enrolled){
    await page.getByRole('button',{name:'删除本人声音',exact:true}).click()
    await wait(async()=>!(await api('/api/voice/owner/status')).enrolled,'Could not reset isolated owner profile')
   }
   await wait(()=>toggle.isDisabled(),'Owner toggle should require enrollment')
   assert(await toggle.isDisabled())
   await page.locator('input[type="file"]').setInputFiles([out+'/enroll-one.wav',out+'/enroll-two.wav'])
   await page.getByRole('button',{name:'提交 2 段',exact:true}).click()
   await page.getByText('本人声音已录入。',{exact:true}).waitFor({timeout:30000})
   // React updates this checkbox only after the HTTP save, not synchronously.
   await toggle.click();await wait(async()=>(await api('/api/settings')).owner_voice_only,'Owner toggle did not persist')
   await wait(()=>toggle.isChecked(),'Owner enabled state did not reach frontend')
   await ready();await toggle.click();await wait(async()=>!(await api('/api/settings')).owner_voice_only,'Owner toggle did not disable')
   await ready();await page.getByRole('button',{name:'删除本人声音',exact:true}).click()
   await wait(async()=>!(await api('/api/voice/owner/status')).enrolled,'Owner profile not deleted')
   await page.getByRole('button',{name:'关闭',exact:true}).click()
   return {profile:'isolated E: profile only',status:await api('/api/voice/owner/status'),identityAccuracy:'Not measured; synthesized fixtures only'}
  })
  await check('API TTS missing credentials is diagnosed at frontend',async()=>{
   await configure({mode:'api'})
   const playback=await speak('API 空密钥',{expectError:true,timeout:15000})
   assert(playback.errors.some(e=>JSON.stringify(e).includes('TTS API 密钥')))
   return {externalProviderUsable:false,reason:'No independent TTS API credentials configured',playback}
  })
  await check('API SDK to controlled PCM provider through frontend playback',async()=>{
   await settings();await page.getByLabel('TTS API 服务',{exact:true}).selectOption('openai_compatible');await input('TTS API 基础地址').fill('http://127.0.0.1:8874/v1')
   await input('TTS 模型').fill('controlled-tts-fixture');await input('API 音色').fill('fixture')
   await input('TTS API 密钥').fill('audit-tts-only')
   await page.getByRole('button',{name:'保存设置',exact:true}).click();await ready()
   return {playback:await speak('API 协议测试'),externalProviderValidation:false,method:'Test-only loopback protocol fixture, not a paid provider'}
  })
  await check('MOSS-Live frontend mode and missing-credential boundary',async()=>{
   if((await api('/api/settings')).owner_voice_only){
    await settings();await page.getByRole('checkbox',{name:'仅回应本人声音',exact:true}).click()
    await wait(async()=>!(await api('/api/settings')).owner_voice_only,'Must disable incompatible owner filtering')
   }
   await configure({conversation:'moss_live'})
   await page.getByPlaceholder('MOSS-Live 模式请使用麦克风对话').waitFor()
   assert(await page.getByRole('button',{name:'发送',exact:true}).isDisabled())
   // Missing credentials are rejected before an RTVI pipeline is created:
   // the transport close reason, not an RTVI error event, is the contract here.
   await wait(async()=>/语音连接失败.*MOSS-Live.*密钥/.test(await page.locator('body').innerText()),'MOSS missing-key diagnostic absent from frontend',15000)
   assert(await page.getByRole('button',{name:'开启语音',exact:true}).isDisabled())
   return {featureUsable:false,reason:'No independent MOSS API key; actual cloud voice/delegation not tested',frontendNotice:await page.locator('.notice').innerText(),status:(await api('/api/status')).tts}
  })
  await check('Auto mode really plays CPU when GPU address is unavailable',async()=>{
   await configure({mode:'auto',model:'gpt_sovits',url:'http://127.0.0.1:18770'})
   await wait(async()=>!!(await health(8772))?.configured,'CPU unavailable',30000)
   const result=await speak('自动模式 CPU 路由');const status=await api('/api/status');assert.equal(status.voice_policy.predicted,'cpu')
   return {policy:status.voice_policy,playback:result,cpu:await health(8772)}
  })
  await check('Auto mode GPU routing, no paid fallback',async()=>{
   await configure({mode:'auto',model:'gpt_sovits',url:'http://127.0.0.1:8770'})
   await wait(async()=>!!(await health(8770))?.configured,'GPU sidecar absent',30000)
   const result=await speak('自动模式 GPU 路由');const h=await health(8770);assert(h.ready&&h.device==='cuda')
   return {playback:result,health:h}
  })
  await check('IndexTTS GPU frontend model switch, preload and PCM playback',async()=>{
   await configure({mode:'gpu',model:'index_tts'})
   const h=await gpu('IndexTTS-2.5');assert(h.device==='cuda'&&h.warmed_up)
   return {health:h,playback:await speak('IndexTTS 本地 GPU')}
  })
  await check('Stop GPU before first PCM and immediately send again',async()=>{
   await configure({mode:'gpu',model:'gpt_sovits',url:'http://127.0.0.1:8770'})
   await gpu('GPT-SoVITS-v5-turbo')
   const before=audioFrames,j=sent.length
   await page.getByPlaceholder('说点什么，或开启语音...').fill('停止时序检查')
   await page.getByRole('button',{name:'发送',exact:true}).click()
   await wait(async()=>!!(await health(8770))?.busy,'GPU request never became busy',15000)
   assert.equal(audioFrames,before,'Must interrupt before the first PCM frame')
   await page.getByRole('button',{name:'停止',exact:true}).click()
   await wait(()=>sent.slice(j).some(e=>e.data?.t==='voice.stop'),'Stop was not sent')
   await delay(150)
   const afterStop=await health(8770)
   const immediate=await speak('停止后立即提问',{expectError:true,timeout:25000})
   await gpu('GPT-SoVITS-v5-turbo')
   const recovered=await speak('恢复就绪后再问')
   const detail={afterStop,immediate,recovered}
   if(immediate.errors.length||!immediate.audioFrames){const e=Error('Immediate next turn failed after cancelling GPU inference');e.auditDetail=detail;throw e}
   return detail
  })
  await check('Stop during actual playback and continue from frontend',async()=>{
   await configure({mode:'gpu',model:'gpt_sovits'})
   await gpu('GPT-SoVITS-v5-turbo')
   const before=await page.evaluate(()=>window.__audit.consumed),j=sent.length
   await page.getByPlaceholder('说点什么，或开启语音...').fill('播放中停止检查')
   await page.getByRole('button',{name:'发送',exact:true}).click()
   await wait(async()=>(await page.evaluate(()=>window.__audit.consumed))>before,'No actual playback',15000)
   await page.getByRole('button',{name:'停止',exact:true}).click()
   await page.getByRole('button',{name:'继续刚才的回答',exact:true}).waitFor()
   const i=events.length,audioBefore=audioFrames
   await page.getByRole('button',{name:'继续刚才的回答',exact:true}).click()
   await wait(()=>events.slice(i).some(e=>e.type==='error'||e.data?.type==='voice.playback.boundary'),'Continue had no result',30000)
   const errors=events.slice(i).filter(e=>e.type==='error').map(e=>e.data)
   const detail={errors,audioFrames:audioFrames-audioBefore,stopCommands:sent.slice(j).filter(e=>['voice.stop','voice.playback.stopped'].includes(e.data?.t)),health:await health(8770)}
   if(errors.length||audioFrames<=audioBefore){const e=Error('Frontend continue failed after playback stop');e.auditDetail=detail;throw e}
   await wait(()=>sent.slice(j).some(e=>e.data?.t==='voice.playback'),'Continue playback was not acknowledged',15000)
   return detail
  })
  await check('CPU stop before first PCM and immediately send again',async()=>{
   await configure({mode:'cpu'})
   await speak('CPU 停止检查前准备')
   const before=audioFrames
   await page.getByPlaceholder('说点什么，或开启语音...').fill('CPU 停止时序检查')
   await page.getByRole('button',{name:'发送',exact:true}).click()
   await wait(async()=>!!(await health(8772))?.busy,'CPU request never became busy',15000)
   assert.equal(audioFrames,before,'Must interrupt before the first PCM frame')
   await page.getByRole('button',{name:'停止',exact:true}).click()
   await delay(150)
   const afterStop=await health(8772)
   return {afterStop,playback:await speak('CPU 停止后立即提问',{timeout:70000}),caveat:'Cancellation may reload the model; not a low-latency guarantee'}
  })
 }finally{
  report.pageErrors=pageErrors;save()
  // Restore the isolated fixture only. Primary settings/profile were never edited.
  await api('/api/settings',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({tts_mode:'api',gpu_tts_model:'gpt_sovits',conversation_mode:'duplex',owner_voice_only:false,streaming_asr_preview:false,index_tts_url:'http://127.0.0.1:8770',clear_tts_api_key:true})}).catch(()=>{})
  await context.close();await browser.close()
 }
 console.log(JSON.stringify(report.cases.map(({name,status,error})=>({name,status,error})),null,2))
 if(!report.cases.length||report.cases.some(c=>c.status==='failed'))process.exitCode=1
})().catch(e=>{report.fatal=String(e);save();console.error(e);process.exitCode=1})
