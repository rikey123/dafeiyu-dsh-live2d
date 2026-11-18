import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {join} from 'node:path';
import {createNativeAdapter, VOICE_BACKGROUND} from '../src/native.mjs';
import {createBridge} from '../src/bridge.mjs';

const root = process.env.DSH_RUNTIME_MODULES_ROOT || 'C:/Users/Administrator/AppData/Roaming/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules';
const check = (name, fn) => test(name, {skip:!existsSync(join(root,'@deepseek-ai/dsh/package.json'))}, fn);
function fixture() {
  const rows = new Map(), logs = new Map(), actors = new Map(), listeners = new Map(), sections = new Map(), admissions = [], guards = new Map(), notices=[];
  let cancellations = 0, disposals = 0;
  const emit = (name, ...args) => { for (const fn of listeners.get(name) ?? []) fn(...args); };
  function actor(id) {
    const inbox={nextStep:[]};
    const agent = {id, session:{id,deriveMessages:()=>[]},inbox,inject(message){notices.push(message);inbox.nextStep.push(message);},ctx:{tools:{guard(fn){guards.set(id,fn);}},systemPrompt:{async assemble(){return {sections:[{name:'deployment:persona-prefix',text:'native persona'},{name:'soul:persona',text:'active soul'},{name:'soul:memory',text:'PRIVATE MEMORY'},{name:'private-tool-guidance',text:'DO NOT EXPORT'}],contexts:[],variables:{},tools:[]};},section(value) {sections.set(id,value);return () => sections.delete(id);}},on(){return () => {}; }}, cancel(){cancellations++;}};
    actors.set(id, agent); return agent;
  }
  const ctx = {
    on(name, fn) { const set = listeners.get(name) ?? new Set(); listeners.set(name,set); set.add(fn); return () => set.delete(fn); },
    agents:{get:id=>actors.get(id), create(){throw Error('must not own a native actor');}, resume(){throw Error('must not own a native actor');}},
    agentDefaultModel:{currentSelection:()=>({provider:'fixture',model:'test'})},
    workspaceRegistry:{archivedSessionIds:[],async archiveSession(id){this.archivedSessionIds.push(id);}},
    sessions:{async flush(){return true;}},
    sessionPersistence:{async stat(id){return logs.has(id)?{}:undefined;},async open(id){return {async read(){return {events:logs.get(id)??[]};},async close(){}};}},
    storageDomain:{async open(){return {table:()=>({get:id=>rows.get(id),entries:()=>rows.entries(),async put(id,row){rows.set(id,row);}}), async close(){disposals++;}};}},
    sessionController:{
      async list(){return {items:[...logs.keys()].map(sessionId=>({sessionId}))};},
      async create({sessionId}) {logs.set(sessionId,[]);actor(sessionId);return {sessionId};},
      async resolveAgent(id){return {agent:actors.get(id)};},
      async prompt(request,signal){signal.throwIfAborted();admissions.push(request);return {accepted:true};},
    },
  };
  return {ctx,emit,rows,logs,actors,sections,admissions,guards,notices,get cancellations(){return cancellations;},get disposals(){return disposals;}};
}
const config = {runtimeModulesRoot:root,workspacePath:process.platform==='win32'?'G:/dafeiyu':'/tmp'};
const body = (id, request_id='req') => ({messages:[{role:'user',content:'帮我查一下'}],dafeiyu:{session_id:id,request_id,kind:'normal',persona:'MUST NOT OVERRIDE DSH SOUL'}});
function stream(f,id,attempt='attempt',text='你好',request='req') {
  const agent=f.actors.get(id);
  f.emit('session/event',agent.session,{type:'turn/start',data:{turn:1}});
  f.emit('session/event',agent.session,{type:'user/message',data:{source:{kind:'user',rpcId:request}}});
  f.emit('agent/assistant-stream',{agent,frame:{type:'start',attemptId:attempt,revision:1,turn:1,step:1}});
  f.emit('agent/assistant-stream',{agent,frame:{type:'chunk',attemptId:attempt,revision:2,index:0,chunk:{type:'reasoning-delta',text:'hidden'}}});
  f.emit('agent/assistant-stream',{agent,frame:{type:'chunk',attemptId:attempt,revision:3,index:1,chunk:{type:'text-delta',text}}});
  f.emit('agent/assistant-stream',{agent,frame:{type:'end',attemptId:attempt,revision:4,index:2,outcome:{kind:'committed',eventType:'assistant/message',seq:1}}});
}

check('native admission owns no Agent and reader disconnect never cancels DSH', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  const cancel=new AbortController(), reader=a.events(s.id,cancel.signal);
  assert.equal((await reader.next()).value.type,'ready');
  assert.deepEqual(await a.submit(body(s.id),new AbortController().signal),{accepted:true,request_id:'req'});
  assert.equal(f.admissions[0].mode,'queue'); assert.equal(f.admissions[0].content[0].text,'帮我查一下');
  cancel.abort();await reader.return();
  assert.equal(f.cancellations,0);await a.dispose();assert.equal(f.cancellations,0);assert(f.actors.has(s.id));
});
check('one Session subscription receives every step and late parent delivery but not child reasoning', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), cancel=new AbortController();
  const reader=a.events(s.id,cancel.signal);await reader.next();
  stream(f,s.id,'a','先等一下');
  assert.equal((await reader.next()).value.type,'response.start');
  assert.equal((await reader.next()).value.text,'先等一下');
  assert.equal((await reader.next()).value.type,'response.end');
  stream(f,s.id,'b','子智能体已完成');
  const first=(await reader.next()).value;assert.equal(first.generation_id,'b');
  assert.equal((await reader.next()).value.text,'子智能体已完成');
  assert.equal((await reader.next()).value.type,'response.end');
  cancel.abort();await reader.return();await a.dispose();assert.equal(f.cancellations,0);
});
check('native reconnect resumes only unconsumed wire frames without resubmitting a prompt', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), c=new AbortController();
  let reader=a.events(s.id,c.signal);await reader.next();stream(f,s.id);
  const start=(await reader.next()).value;c.abort();await reader.return();
  const c2=new AbortController();reader=a.events(s.id,c2.signal,start.event_id);
  assert.equal((await reader.next()).value.type,'ready');
  assert.equal((await reader.next()).value.type,'response.text');assert.equal((await reader.next()).value.type,'response.end');
  c2.abort();await reader.return();assert.equal(f.admissions.length,0);await a.dispose();
});
check('ready cursor survives a disconnect before the first assistant token', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), c=new AbortController();
  let reader=a.events(s.id,c.signal);const ready=(await reader.next()).value;
  c.abort();await reader.return();stream(f,s.id,'delayed','等待后完成');
  const c2=new AbortController();reader=a.events(s.id,c2.signal,ready.event_id);
  assert.equal((await reader.next()).value.type,'ready');
  assert.equal((await reader.next()).value.type,'response.start');
  assert.equal((await reader.next()).value.text,'等待后完成');
  c2.abort();await reader.return();await a.dispose();
});
check('silent Agent errors stay in DSH and later public replies still reach voice', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), c=new AbortController();
  const reader=a.events(s.id,c.signal);await reader.next();
  f.emit('agent/error',{agent:f.actors.get(s.id),error:Error('provider-secret')});
  f.emit('session/event',f.actors.get(s.id).session,{type:'turn/end',data:{reason:{kind:'blocked'}}});
  const end=(await reader.next()).value;assert.equal(end.type,'turn.end');assert.equal(end.code,undefined);
  stream(f,s.id,'explanation','查询遇到登录问题，需要你登录。');
  assert.equal((await reader.next()).value.type,'response.start');
  const event=(await reader.next()).value;assert.equal(event.type,'response.text');assert.match(event.text,/登录/);
  assert(!JSON.stringify(event).includes('provider-secret'));assert.equal((await reader.next()).value.type,'response.end');
  c.abort();await reader.return();await a.dispose();
});
check('legacy completion waits for the admitted native turn, including every tool-followup step', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  const reader=a.chat(body(s.id),new AbortController().signal);
  const waiting=reader.next();
  while(!f.admissions.length) await new Promise(resolve=>setImmediate(resolve));
  stream(f,s.id,'first','先查资料');
  assert.equal((await waiting).value,'先查资料');
  const next=reader.next();stream(f,s.id,'second','最终结果');assert.equal((await next).value,'最终结果');
  const end=reader.next();f.emit('session/event',f.actors.get(s.id).session,{type:'turn/end',data:{reason:{kind:'completed'}}});
  assert.equal((await end).done,true);assert.equal(f.cancellations,0);await a.dispose();
});
check('a silent task outcome is typed for compatibility readers, not a broken or empty voice transport', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  const reader=a.chat(body(s.id),new AbortController().signal), pending=reader.next();
  while(!f.admissions.length)await new Promise(resolve=>setImmediate(resolve));
  const agent=f.actors.get(s.id);
  f.emit('session/event',agent.session,{type:'user/message',data:{source:{kind:'user',rpcId:'req'}}});
  f.emit('agent/error',{agent,error:Error('private provider error')});
  f.emit('session/event',agent.session,{type:'turn/end',data:{reason:{kind:'blocked'}}});
  await assert.rejects(pending,error=>error.code==='AGENT_ERROR'&&!error.message.includes('private'));
  assert.equal(f.cancellations,0);await a.dispose();
});
check('canonical text history is not truncated to playback and voice background does not replace personality', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  f.logs.set(s.id,[{type:'user/message',surfaceOp:'append',data:{id:'u',source:{kind:'user'},content:[{type:'text',text:'你好'}]}},
    {type:'assistant/message',surfaceOp:'append',data:{message:{id:'a',content:[{type:'text',text:'完整回复'}, {type:'reasoning',text:'never expose'}]}}},
    {type:'assistant/message',surfaceOp:{op:'replace',start:0,end:1},data:{message:{id:'copy',content:[{type:'text',text:'model-only replacement'}]}}}]);
  assert.deepEqual((await a.messages(s.id)).map(x=>x.content),['你好','完整回复']);
  await a.voiceState({session_id:s.id,connection_id:'voice',active:true,microphone:false});
  assert.equal(f.sections.get(s.id).text(),VOICE_BACKGROUND);
  await a.voiceState({session_id:s.id,connection_id:'voice',active:false,microphone:false});
  assert.equal(f.sections.get(s.id).text(),'');await a.dispose();
});
check('requested screen preserves native attachments without a screen tool or step veto', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), request=body(s.id);
  request.dafeiyu.screen_state='attached';request.dafeiyu.images=[{mime_type:'image/jpeg',width:1,height:1,data:'/9j/2Q=='}];
  await a.submit(request,new AbortController().signal);
  assert.equal(f.admissions[0].content[1].type,'image');assert.equal(f.admissions[0].content[1].name,'shared-screen.jpg');
  assert.equal(f.guards.size,0);
  f.emit('session/event',f.actors.get(s.id).session,{type:'user/message',data:{source:{kind:'user',rpcId:'req'}}});
  assert.equal(f.guards.size,0);assert.match(f.sections.get(s.id).text(),/共享屏幕的截图/);
  assert.doesNotMatch(f.sections.get(s.id).text(),/不执行工具|不可信/);
  f.emit('session/event',f.actors.get(s.id).session,{type:'turn/end',data:{reason:{kind:'completed'}}});
  assert.equal(f.guards.size,0);await a.dispose();
});
check('failed or aborted text attempts close cleanly without inventing an audio error', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), c=new AbortController();
  const reader=a.events(s.id,c.signal);await reader.next();const agent=f.actors.get(s.id);
  f.emit('agent/assistant-stream',{agent,frame:{type:'start',attemptId:'failed',revision:1}});
  f.emit('agent/assistant-stream',{agent,frame:{type:'chunk',attemptId:'failed',revision:2,index:0,chunk:{type:'text-delta',text:'我查一下'}}});
  assert.equal((await reader.next()).value.type,'response.start');assert.equal((await reader.next()).value.type,'response.text');
  f.emit('agent/error',{agent,error:Error('tool-secret')});
  assert.equal((await reader.next()).value.type,'response.end');
  f.emit('session/event',agent.session,{type:'turn/end',data:{reason:{kind:'aborted'}}});
  assert.equal((await reader.next()).value.type,'turn.end');
  stream(f,s.id,'later','稍后给你结果');
  assert.equal((await reader.next()).value.type,'response.start');assert.equal((await reader.next()).value.text,'稍后给你结果');
  assert.equal((await reader.next()).value.type,'response.end');
  c.abort();await reader.return();assert.equal(f.cancellations,0);await a.dispose();
});
check('a text sequence gap remains a genuine voice transport error', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), c=new AbortController();
  const reader=a.events(s.id,c.signal);await reader.next();const agent=f.actors.get(s.id);
  f.emit('agent/assistant-stream',{agent,frame:{type:'start',attemptId:'gap',revision:1}});
  f.emit('agent/assistant-stream',{agent,frame:{type:'chunk',attemptId:'gap',revision:2,index:0,chunk:{type:'text-delta',text:'前缀'}}});
  f.emit('agent/assistant-stream',{agent,frame:{type:'chunk',attemptId:'gap',revision:3,index:2,chunk:{type:'text-delta',text:'丢帧后'}}});
  assert.equal((await reader.next()).value.type,'response.start');assert.equal((await reader.next()).value.type,'response.text');
  const error=(await reader.next()).value;assert.equal(error.type,'response.error');assert.equal(error.code,'VOICE_STREAM_GAP');
  c.abort();await reader.return();await a.dispose();
});
check('only acknowledged preview speech enters a native context notice without waking an Agent', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  f.rows.get(s.id).requests.push({id:'preview',userId:'',kind:'screen',generated:'你好。继续',played:'',interrupted:false,sealed:false,state:'done',created_at:new Date().toISOString()});
  assert.equal((await a.playback({session_id:s.id,generation_id:'preview',text:'fake'})).accepted,false);
  assert.equal(f.notices.length,0);
  assert.equal((await a.playback({session_id:s.id,generation_id:'preview',text:'你好。'})).accepted,true);
  assert.equal(f.notices.length,1);assert.equal(f.notices[0].source.kind,'dafeiyu-voice');assert.equal(f.notices[0].source.form,'notice');
  await a.playback({session_id:s.id,generation_id:'preview',text:'你好。'});assert.equal(f.notices.length,1);
  assert.equal(f.admissions.length,0);assert.equal(f.cancellations,0);await a.dispose();
});

check('idle playback is a labelled native notice and direct/idle opportunities never cancel running native work', async () => {
  const f=fixture(),a=await createNativeAdapter(f.ctx,config),s=await a.session();
  f.rows.get(s.id).requests.push({id:'idle-preview',userId:'',kind:'idle',generated:'一起歇一下',played:'',interrupted:false,sealed:false,state:'done',created_at:new Date().toISOString()});
  await a.playback({session_id:s.id,generation_id:'idle-preview',text:'一起歇一下'});
  assert.equal(f.notices.length,1);assert.match(f.notices[0].content[0].text,/安静后的主动搭话/);
  f.actors.get(s.id).status='running';
  for(const kind of ['idle','screen']){
    const req=body(s.id,'busy-'+kind);Object.assign(req.dafeiyu,{kind,...(kind==='screen'?{screen_mode:'direct'}:{})});
    let text='';for await(const chunk of a.chat(req,new AbortController().signal))text+=chunk;
    assert.equal(text,'');
  }
  assert.equal(f.cancellations,0);assert.equal(f.admissions.length,0);await a.dispose();
});
check('confirmed screen commentary brings its historical picture and scene into the native inbox', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  const image={type:'image',attachment:{attachmentId:'a'.repeat(64),mediaType:'image/jpeg',bytes:4,width:1,height:1}};
  f.rows.get(s.id).requests.push({id:'screen-context',userId:'',kind:'screen',generated:'这页在讨论新模型。后面还没有播报',played:'',interrupted:false,sealed:false,state:'done',ending:'completed',created_at:'2026-11-15T06:13:28.000Z',
    observation:{observedAt:'2026-11-15T06:13:28.000Z',input:'用户正在B站浏览首页',images:[image]}});
  await a.playback({session_id:s.id,generation_id:'screen-context',text:'这页在讨论新模型。'});
  const notice=f.notices[0];assert.equal(notice.source.kind,'dafeiyu-voice');
  assert.equal(notice.source.externalEventId,'screen-context');
  assert.match(notice.content[0].text,/屏幕主动评论/);assert.match(notice.content[0].text,/B站浏览首页/);
  assert.match(notice.content[0].text,/2026-11-15T06:13:28/);assert.match(notice.content[0].text,/completed/);
  assert.doesNotMatch(notice.content[0].text,/后面还没有播报/);assert.deepEqual(notice.content[1],image);
  assert.match(notice.content[0].text,/历史屏幕画面/);
  assert.equal(f.admissions.length,0);assert.equal(f.actors.get(s.id).inbox.nextStep.length,1);
  await a.playback({session_id:s.id,generation_id:'screen-context',text:'这页在讨论新模型。'});assert.equal(f.notices.length,1);
  await a.playback({session_id:s.id,generation_id:'screen-context',text:'这页在讨论新模型。后面',interrupted:true});
  assert.equal(f.notices.length,2);assert.equal(f.notices[1].content.length,1);assert.match(f.notices[1].content[0].text,/已打断/);
  await a.dispose();
});
check('unchanged confirmed text can still report interruption and failed flush retries do not duplicate context', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  f.rows.get(s.id).requests.push({id:'status',userId:'',kind:'screen',generated:'欸…屏',played:'',interrupted:false,sealed:false,state:'done',ending:'max-tokens',created_at:new Date().toISOString()});
  let flush=false;f.ctx.sessions.flush=async()=>flush;
  await assert.rejects(a.playback({session_id:s.id,generation_id:'status',text:'欸…屏'}),{code:'PERSISTENCE_UNAVAILABLE'});
  assert.equal(f.notices.length,1);assert.match(f.notices[0].content[0].text,/max-tokens/);
  flush=true;
  await a.playback({session_id:s.id,generation_id:'status',text:'欸…屏'});assert.equal(f.notices.length,1);
  await a.playback({session_id:s.id,generation_id:'status',text:'欸…屏',interrupted:true});
  assert.equal(f.notices.length,2);assert.match(f.notices[1].content[0].text,/已打断/);
  await a.dispose();
});
check('companionship context reuses the latest native ACK notice without polluting canonical chat', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  f.rows.get(s.id).requests.push({id:'remembered',userId:'',kind:'idle',generated:'一起歇一下。未播报的后半句',played:'',
    interrupted:false,sealed:false,state:'done',created_at:new Date().toISOString()});
  await a.playback({session_id:s.id,generation_id:'remembered',text:'一起'});
  // A prior cumulative ACK has already entered DSH's native persisted log.
  f.logs.set(s.id,[{type:'user/message',surfaceOp:'append',time:Date.now(),data:f.notices[0]}]);
  await a.playback({session_id:s.id,generation_id:'remembered',text:'一起歇一下。'});
  assert.deepEqual(await a.messages(s.id),[]);
  const context=await a.voiceContext(s.id,new AbortController().signal);
  assert.equal(context.messages.length,1);
  assert.equal(context.messages[0].id,'remembered');
  assert.match(context.messages[0].content,/一起歇一下。/);
  assert.doesNotMatch(context.messages[0].content,/未播报的后半句/);
  assert.equal(f.admissions.length,0);assert.equal(f.cancellations,0);
  await a.dispose();
});
check('HTTP voice SSE has cursor IDs and an admitted task survives closing its subscriber', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session(), b=await createBridge(a);
  const headers={Authorization:`Bearer ${b.token}`,'Content-Type':'application/json'};
  try {
    const cancel=new AbortController(), response=await fetch(b.url+`/v1/voice/events?session_id=${s.id}`,{headers,signal:cancel.signal});
    const reader=response.body.getReader();const first=new TextDecoder().decode((await reader.read()).value);
    assert.match(first,/id: [a-f0-9-]+:\d+/);assert.match(first,/"type":"ready"/);
    const admitted=await fetch(b.url+'/v1/voice/turns',{method:'POST',headers,body:JSON.stringify(body(s.id))});
    assert.equal(admitted.status,200);assert.equal((await admitted.json()).accepted,true);
    cancel.abort();await reader.cancel().catch(()=>{});assert.equal(f.cancellations,0);
  } finally {await b.dispose();await a.dispose();}
});

check('MOSS uses native persona only and observed speech is durable context without another model turn', async () => {
  const f=fixture(), a=await createNativeAdapter(f.ctx,config), s=await a.session();
  const context=await a.voiceContext(s.id,new AbortController().signal);
  assert.equal(context.persona,'native persona\n\nactive soul');assert.deepEqual(context.messages,[]);
  assert.equal(context.environment,'');
  assert.equal(context.busy,false);
  f.actors.get(s.id).status='running';
  assert.equal((await a.voiceContext(s.id,new AbortController().signal)).busy,true);
  f.actors.get(s.id).status='idle';
  await a.voiceState({session_id:s.id,connection_id:'moss',active:true,microphone:false});
  const speaking=await a.voiceContext(s.id,new AbortController().signal);
  assert.equal(speaking.persona,context.persona);
  assert.equal(speaking.environment,VOICE_BACKGROUND);
  assert.match(speaking.environment,/一对一实时语音/);
  assert.doesNotMatch(JSON.stringify(speaking),/PRIVATE MEMORY|DO NOT EXPORT/);
  await a.voiceState({session_id:s.id,connection_id:'moss',active:false,microphone:false});
  assert.equal((await a.voiceContext(s.id,new AbortController().signal)).environment,'');
  const observation={session_id:s.id,event_id:'moss-1',role:'assistant',text:'spoken',revised:false};
  assert.equal((await a.voiceObservation(observation)).accepted,true);
  assert.equal((await a.voiceObservation(observation)).duplicate,true);
  assert.equal(f.notices.length,1);assert.equal(f.notices[0].source.form,'notice');
  assert.equal(f.admissions.length,0);assert.equal(f.cancellations,0);await a.dispose();
});
