import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { createHarnessAdapter } from '../src/harness.mjs';

const root = process.env.DSH_RUNTIME_MODULES_ROOT || 'C:/Users/Administrator/AppData/Roaming/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules';
const available = existsSync(join(root, '@deepseek-ai/dsh/package.json'));
const check = (name, fn) => test(name, { skip: !available && 'set DSH_RUNTIME_MODULES_ROOT to the DSH node_modules directory' }, fn);

function fixture() {
  const rows = new Map(), logs = new Map(), headers = new Map(), live = new Map(), created = new Map(), listeners = new Map();
  const archived = [], admitted = [], guards = [];
  let behavior = 'auto';
  let tokens = ['hello', ' world'];
  let selection = { provider: 'fake', model: 'fake-model' };
  let gate;
  let stuck = false;
  let recordSchema;
  const emit = (name, ...args) => { for (const fn of [...(listeners.get(name) || [])]) fn(...args); };
  const table = { get: id => rows.get(id), entries: () => rows.entries(), async put(id, row) { rows.set(id, recordSchema.parse(structuredClone(row))); } };
  const ctx = {
    agentDefaultModel: { currentSelection: () => selection },
    llm: { async resolveModelInfo() { return { inputModalities: ['text', 'image'] }; } },
    attachments: { async admitPromptContent(parts) {
      admitted.push(...parts);
      return parts.map(() => ({ type: 'image', attachment: {
        attachmentId: 'a'.repeat(64), mediaType: 'image/jpeg', bytes: 4, width: 1, height: 1,
      } }));
    } },
    storageDomain: { async open(spec) { recordSchema = spec.tables.sessions.valueSchema; return { table: () => table, async close() {} }; } },
    workspaceRegistry: { archivedSessionIds: archived, async archiveSession(id, options) { assert.equal(options.stopActivity, true); archived.push(id); } },
    sessions: { async flush() { return true; } },
    sessionPersistence: {
      async stat(id) { return logs.has(id) ? { header: headers.get(id) } : undefined; },
      async open(id) { return { async read() { return { events: structuredClone(logs.get(id) || []) }; }, async close() {} }; },
    },
    on(name, fn) { const set = listeners.get(name) || new Set(); listeners.set(name, set); set.add(fn); return () => set.delete(fn); },
    agents: {
      get: id => live.get(id)?.agent,
      async create(options) { return create(options.sessionId, options, false); },
      async resume(options) { return create(options.resumeSessionId, options, true); },
    },
  };
  async function create(id, options, resume) {
    if (gate) await gate;
    options.signal?.throwIfAborted();
    if (resume && !logs.has(id)) throw Error('not found');
    if (!logs.has(id)) { logs.set(id, []); headers.set(id, { ...options.meta, id }); }
    let section, idle = Promise.resolve(), finish, currentModel;
    let turn = logs.get(id).filter(event => event.type === 'turn/start').length;
    const scopedGuards = [];
    const scoped = { on() { return () => {}; }, tools: { guard(fn) { guards.push(fn); scopedGuards.push(fn); } },
      systemPrompt: { section(value) { section = value; return () => {}; } } };
    await options.setup(scoped);
    const agent = {
      id, session: { id }, status: 'idle', inputs: [], prompts: [], guardResults: [], creationOptions:options.agentOptions,
      model: { current: () => currentModel, select(value) { currentModel = { ...value }; } },
      followup(message) {
        this.inputs.push(message); this.prompts.push(section.text()); this.status = 'running';
        this.guardResults.push(scopedGuards.map(fn => fn({})));
        const start = { type: 'turn/start', data: { turn: ++turn }, time: Date.now() };
        logs.get(id).push(start); emit('session/event', this.session, start);
        const event = { type: 'user/message', data: message, time: Date.now() };
        logs.get(id).push(event); emit('session/event', this.session, event);
        idle = new Promise(resolve => { finish = () => { this.status = 'idle'; resolve(); }; });
        if (behavior !== 'hold') setImmediate(() => {
          if (this.status === 'idle') return;
          emit('agent/assistant-stream', { agent: this, frame: { type: 'start', attemptId: `attempt-${turn}`, turn, revision: turn * 100, step: 1 } });
          for (const [index, text] of tokens.entries()) emit('agent/assistant-stream', { agent: this, frame: { type: 'chunk', attemptId: `attempt-${turn}`, revision: turn * 100 + index + 1, index, chunk: { type: 'text-delta', text } } });
          const end = { type: 'turn/end', data: { reason: { kind: behavior === 'blocked' ? 'blocked' : 'completed' } } };
          logs.get(id).push(end); emit('session/event', this.session, end); finish();
        });
      },
      whenIdle() { return idle; },
      cancel() { if (!stuck) finish?.(); },
    };
    const handle = { agent, async dispose() { agent.cancel(); live.delete(id); } };
    live.set(id, handle);
    created.set(id, agent);
    return handle;
  }
  return { ctx, rows, logs, live, created, archived, admitted, guards, setModel(value) { selection = value; }, setBehavior(value) { behavior = value; }, setTokens(value) { tokens = value; },
    setGate(value) { gate = value; }, setStuck(value) { stuck = value; }, emit };
}
const config = { runtimeModulesRoot: root, workspacePath: process.platform === 'win32' ? 'G:/dafeiyu' : '/tmp', timeoutMs: 300, drainTimeoutMs: 100 };
const body = (session_id, request_id, kind = 'normal') => ({ messages: [{ role: 'assistant', content: 'old answer' }, { role: 'user', content: 'old input' }, { role: 'user', content: 'new input' }], dafeiyu: { session_id, request_id, kind, persona: 'companion' } });
async function collect(iterable) { let output = ''; for await (const value of iterable) output += value; return output; }
async function waitFor(predicate) {
  const deadline = Date.now() + 1000;
  while (!predicate()) { if (Date.now() >= deadline) throw Error('fixture did not reach expected state'); await new Promise(resolve => setTimeout(resolve, 1)); }
}

check('idle preview uses native parent personality, optional fresh image and configured interests without a human turn', async () => {
  const f=fixture();const personaCalls=[];
  const a=await createHarnessAdapter(f.ctx,{...config,previewPersona:async(id,signal)=>{signal.throwIfAborted();personaCalls.push(id);return '完整父会话人格：鲸鱼娘喜欢有趣的细节';}});
  const s=await a.session();
  const request=body(s.id,'idle-without-screen','idle');
  request.dafeiyu.max_reply_chars=240;request.dafeiyu.companion_interests='航天、独立游戏';
  assert.equal(await collect(a.chat(request)),'hello world');
  const preview=[...f.created.values()].find(agent=>agent.id.startsWith('dafeiyu-preview-'));
  assert.match(preview.prompts[0],/完整父会话人格/);assert(!preview.prompts[0].includes('Persona (additional to existing safety, tools and skills):\ncompanion'));
  assert.match(preview.prompts[0],/航天、独立游戏/);assert.match(preview.prompts[0],/安静了一段时间/);
  assert.match(preview.prompts[0],/没有图时不要假装看到/);assert.match(preview.prompts[0],/可以不出声/);
  assert.equal(preview.inputs[0].content.length,1);assert.deepEqual(personaCalls,[s.id]);
  assert.equal(f.rows.get(s.id).requests.at(-1).userId,'');
  assert.equal(f.rows.get(s.id).requests.at(-1).state,'done');assert.deepEqual(await a.messages(s.id),[]);
  await a.playback({session_id:s.id,generation_id:'idle-without-screen',text:'hello',interrupted:true});
  assert.equal(a.confirmedPreview(s.id,'idle-without-screen').kind,'idle');
  const withImage=body(s.id,'idle-with-screen','idle');withImage.dafeiyu.images=[{mime_type:'image/jpeg',width:1,height:1,data:'/9j/2Q=='}];
  await collect(a.chat(withImage));assert.equal(f.admitted.length,1);
  assert.equal(f.rows.get(s.id).requests.at(-1).observation.images[0].type,'image');
  const screenIdle=[...f.created.values()].filter(agent=>agent.id.startsWith('dafeiyu-preview-')).at(-1);
  assert.match(screenIdle.prompts[0],/若附有新截图且想聊眼前内容/);
  assert.match(screenIdle.prompts[0],/不先概述画面再补一句评价/);
  await a.dispose();
});

check('direct screen and idle previews may remain silent without a fabricated line or failed generation', async () => {
  const f=fixture();f.setTokens([]);const a=await createHarnessAdapter(f.ctx,config),s=await a.session();
  for(const kind of ['idle','screen']){
    const req=body(s.id,'silent-'+kind,kind);
    if(kind==='screen')Object.assign(req.dafeiyu,{screen_mode:'direct',images:[{mime_type:'image/jpeg',width:1,height:1,data:'/9j/2Q=='}]});
    assert.equal(await collect(a.chat(req)),'');
    const recorded=f.rows.get(s.id).requests.at(-1);assert.equal(recorded.state,'done');assert.equal(recorded.generated,'');assert.equal(recorded.played,'');assert.equal(recorded.interrupted,false);
  }
  const screen=[...f.created.values()].find(agent=>agent.prompts[0]?.includes('不必每帧说话'));
  assert(screen);assert.match(screen.prompts[0],/自行决定/);assert.match(screen.prompts[0],/不重复上一句/);
  const ordinary=body(s.id,'ordinary-empty','screen');ordinary.dafeiyu.images=[{mime_type:'image/jpeg',width:1,height:1,data:'/9j/2Q=='}];
  await assert.rejects(collect(a.chat(ordinary)),e=>e.code==='EMPTY_RESPONSE');
  await a.dispose();
});

check('new preview metadata remains structurally bounded, with no idle image requirement or mode confusion', async () => {
  const f=fixture();const a=await createHarnessAdapter(f.ctx,config),s=await a.session();
  const creations=f.created.size;
  const invalid=[{screen_mode:'other'},{kind:'idle',screen_mode:'direct'},{kind:'idle',max_reply_chars:241},
    {kind:'idle',companion_interests:'x'.repeat(2001)},{kind:'idle',companion_interests:[]},{kind:'idle',images:[]},
    {kind:'initiative',images:[{mime_type:'image/jpeg',width:1,height:1,data:'/9j/2Q=='}]}];
  for(const [index,patch] of invalid.entries()){
    const req=body(s.id,'invalid-'+index,'screen');Object.assign(req.dafeiyu,patch);
    await assert.rejects(collect(a.chat(req)),e=>e.code==='INVALID_REQUEST');
  }
  assert.equal(f.created.size,creations);await a.dispose();
});

check('screen capability preflight is metadata-only, cached, and fails closed on unknown routes', async () => {
  const f = fixture();
  let calls = 0;
  f.ctx.llm.resolveModelInfo = async () => { calls++; return {}; };
  const a = await createHarnessAdapter(f.ctx, config);
  assert.equal((await a.status()).screen_ready, false);
  assert.equal((await a.status()).screen_reason, 'requires_image_capable_dsh_model');
  assert.equal(calls, 1);
  assert.equal(f.created.size, 0);
  assert.equal(f.admitted.length, 0);
  f.setModel({provider:'fake',model:'vision-model'});
  f.ctx.llm.resolveModelInfo = async () => { calls++; return {inputModalities:['text','image']}; };
  assert.equal((await a.status()).screen_ready, true);
  assert.equal(calls, 2);
  assert.equal(f.created.size, 0);
  await a.dispose();
});

for (const mode of ['systemone', 'direct']) check(`${mode} screen previews express an unsolicited personal reaction without altering the persona or forcing tools`, async () => {
  const f = fixture();
  const a = await createHarnessAdapter(f.ctx, {...config, voiceEnvironment:() => 'VOICE ENVIRONMENT: real actions, not promises'});
  const s = await a.session();
  const request = body(s.id, 'screen-environment', 'screen');
  request.dafeiyu.screen_mode = mode;
  request.dafeiyu.images = [{mime_type:'image/jpeg',width:1,height:1,data:'/9j/2Q=='}];
  await collect(a.chat(request));
  const preview = [...f.created.values()].find(agent => agent.id.startsWith('dafeiyu-preview-'));
  assert.match(preview.prompts[0], /VOICE ENVIRONMENT: real actions, not promises/);
  assert.match(preview.prompts[0], /主动陪用户一起看屏幕/);
  assert.match(preview.prompts[0], /不是在被要求描述图片/);
  assert.match(preview.prompts[0], /看法、感受、判断、吐槽或联想/);
  assert.match(preview.prompts[0], /不先概述画面再补一句评价/);
  assert.match(preview.prompts[0], /不硬凑笑话/);
  assert.match(preview.prompts[0], /不重复上一句/);
  assert.match(preview.prompts[0], /Persona \(additional to existing safety, tools and skills\):\ncompanion\n/);
  assert.doesNotMatch(preview.prompts[0], /about what you notice/);
  assert.equal(f.guards.length,0);
  await a.dispose();
});

check('native helpers, only owned sessions, followup, confirmed projection, resume and archive', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config);
  const s = await a.session();
  assert.deepEqual(await a.status(), { ready: true, provider: 'dsh', model: 'fake-model', configured: true, screen_ready:true, screen_reason:'image_model' });
  assert.equal(await collect(a.chat(body(s.id, 'r1'))), 'hello world');
  const agent = f.live.get(s.id).agent;
  assert.equal(agent.inputs.length, 1); assert.equal(agent.inputs[0].content[0].text, 'new input');
  assert.equal((await a.messages(s.id)).length, 1);
  assert.deepEqual(await a.playback({ session_id: s.id, generation_id: 'r1', text: 'hello' }), { accepted: true });
  assert.equal((await a.messages(s.id))[1].content, 'hello');
  assert.equal((await a.messages(s.id))[1].interrupted, true);
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'r1', text: 'hell' })).accepted, false);
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'r1', text: 'hello forged' })).accepted, false);
  const other = await a.session();
  assert.equal((await a.playback({ session_id: other.id, generation_id: 'r1', text: 'hello' })).accepted, false);
  assert.equal(await collect(a.chat(body(s.id, 'r2'))), 'hello world');
  assert.match(agent.prompts[1], /"hello"/);
  await assert.rejects(collect(a.chat(body(s.id, 'r1'))), e => e.code === 'DUPLICATE_REQUEST' && e.status === 409);
  await a.dispose();
  const b = await createHarnessAdapter(f.ctx, config);
  assert.equal((await b.sessions()).length, 2);
  assert.equal((await b.messages(s.id))[1].content, 'hello');
  assert.equal(await collect(b.chat(body(s.id, 'r3'))), 'hello world');
  assert.equal(await b.deleteSession(s.id), true);
  assert.equal(await b.deleteSession(s.id), false);
  assert.equal((await b.sessions()).length, 1);
  await b.dispose();
});

check('only delivered prefix can be confirmed and acknowledgement is monotone', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  const iter = a.chat(body(s.id, 'r'));
  assert.equal((await iter.next()).value, 'hello');
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'r', text: 'hello world' })).accepted, false);
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'r', text: 'hello' })).accepted, true);
  assert.equal((await iter.next()).value, ' world');
  assert.equal((await iter.next()).done, true);
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'r', text: 'hello world', interrupted: true })).accepted, true);
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'r', text: 'hello world' })).accepted, false);
  await a.dispose();
});

check('initiative suggests brevity but never cuts punctuation or character count', async () => {
  const f = fixture(); f.setTokens(['First sentence. More', ' ignored']);
  const a = await createHarnessAdapter(f.ctx, { ...config, initiativeMaxChars: 20 }); const s = await a.session();
  const output = await collect(a.chat(body(s.id, 'preview', 'initiative')));
  assert.equal(output, 'First sentence. More ignored');
  const preview=[...f.created.values()].find(agent=>agent.id!==s.id);
  assert.equal(preview.creationOptions.maxTokens,undefined);
  assert.match(preview.prompts[0],/preferably around 20 characters/);
  assert.doesNotMatch(preview.prompts[0], /不先概述画面再补一句评价/);
  assert.equal(f.logs.get(s.id).filter(e => e.type === 'user/message').length, 0);
  assert.equal([...f.live.keys()].filter(id => id.startsWith('dafeiyu-preview-')).length, 0);
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'preview', text: output })).accepted, true);
  assert.equal((await a.messages(s.id))[0].content, output);
  await a.dispose();
});

// The fixture mocks native raster decoding: these tests verify the adapter's
// admission/capability contract, not JPEG decoder correctness.
const screenBody = (id, request) => {
  const value = body(id, request, 'screen');
  value.dafeiyu.images = [{ mime_type: 'image/jpeg', data: '/9j/2Q==', width: 1, height: 1 }];
  value.dafeiyu.max_reply_chars = 100;
  return value;
};
check('screen uses native attachments with no extra tool guard or forced truncation', async () => {
  const f = fixture(); f.setTokens(['看起来很精彩。后续不读']);
  const a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  const text = await collect(a.chat(screenBody(s.id, 'screen-one')));
  assert.equal(text, '看起来很精彩。后续不读');
  assert.equal(f.admitted.length, 1);
  const preview = [...f.created.values()].find(agent => agent.id !== s.id);
  assert.equal(preview.inputs[0].content[1].attachment.attachmentId, 'a'.repeat(64));
  assert.match(preview.prompts[0], /当前共享屏幕的新画面/);
  assert.match(preview.prompts[0], /建议约100字/);
  assert.doesNotMatch(preview.prompts[0], /This is an unfinished ASR/);
  assert.equal(f.guards.length, 0); assert.deepEqual(preview.guardResults[0],[]);
  assert.equal(preview.creationOptions.maxTokens,undefined);
  assert.equal(f.live.has(preview.id), false);
  assert.equal(f.logs.get(s.id).filter(event => event.type === 'user/message').length, 0);
  assert.equal((await a.playback({ session_id: s.id, generation_id: 'screen-one', text })).accepted, true);
  const context=a.confirmedPreview(s.id,'screen-one');
  assert.equal(context.observation.images[0].attachment.attachmentId,'a'.repeat(64));
  assert.equal(context.observation.input,'new input');assert.equal(context.ending,'completed');
  assert.deepEqual((await a.messages(s.id)).map(row => row.content), [text]);
  await a.dispose();
});

check('user-requested screen stays one native turn with unrestricted replies and tool calls', async () => {
  const f = fixture(); f.setTokens(['画面里有一个图表。', '这是正常完整回答，不受陪玩的一句话限制。'.repeat(8)]);
  const a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  const request = body(s.id, 'screen-requested');
  request.messages.at(-1).content = '看看我当前屏幕，帮我解释这个图表';
  request.dafeiyu.screen_state = 'attached';
  request.dafeiyu.images = screenBody(s.id, 'source').dafeiyu.images;
  const text = await collect(a.chat(request));
  assert(text.length > 120, 'an ordinary visual answer is not an initiative-length preview');
  assert.equal(f.created.size, 1);
  const agent = f.created.get(s.id);
  assert.equal(agent.inputs.length, 1);
  assert.equal(agent.inputs[0].content[1].type, 'image');
  assert.deepEqual(agent.guardResults[0],[]);
  assert.match(agent.prompts[0], /fresh image.*THIS user question/);
  assert.doesNotMatch(agent.prompts[0], /主动陪用户一起看屏幕|不先概述画面再补一句评价/);
  assert.equal(f.rows.get(s.id).requests[0].userId, agent.inputs[0].id);
  assert.deepEqual((await a.messages(s.id)).map(r => r.content), ['看看我当前屏幕，帮我解释这个图表']);
  await a.playback({session_id:s.id, generation_id:'screen-requested', text});
  assert.deepEqual((await a.messages(s.id)).map(r => r.content), ['看看我当前屏幕，帮我解释这个图表',text]);
  f.setTokens(['普通回答']);
  await collect(a.chat(body(s.id, 'normal-after-image')));
  assert.deepEqual(agent.guardResults[1],[], 'plugin does not add a guard on any normal turn');
  assert.match(agent.prompts[1], /No screen is currently shared/);
  assert.equal(f.admitted.length, 1, 'no old image is silently reattached');
  await a.dispose();
});

check('normal requested images enforce current capability, attachment admission and explicit state', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  for (const state of ['fabricated','shared_not_requested']) {
    const request = body(s.id, 'invalid-'+state);
    request.dafeiyu.images = screenBody(s.id, 'x').dafeiyu.images;
    request.dafeiyu.screen_state = state;
    await assert.rejects(collect(a.chat(request)),{code:'INVALID_REQUEST'});
  }
  const missing = body(s.id,'missing-image');missing.dafeiyu.screen_state='attached';
  await assert.rejects(collect(a.chat(missing)),{code:'INVALID_REQUEST'});
  const textOnly = body(s.id,'text-only');textOnly.dafeiyu.screen_state='attached';
  textOnly.dafeiyu.images=screenBody(s.id,'x').dafeiyu.images;
  f.ctx.llm.resolveModelInfo=async()=>({inputModalities:['text']});
  await assert.rejects(collect(a.chat(textOnly)),{code:'SCREEN_UNAVAILABLE'});
  assert.equal(f.admitted.length,0);assert.equal(f.created.get(s.id).inputs.length,0);
  await a.dispose();
});

check('text-only and unknown screen routes fail before storing bytes or following up and release lock', async () => {
  for (const inputModalities of [['text'], undefined]) {
    const f = fixture(); f.ctx.llm.resolveModelInfo = async () => ({ inputModalities });
    const a = await createHarnessAdapter(f.ctx, config), s = await a.session();
    await assert.rejects(collect(a.chat(screenBody(s.id, 'no-vision'))), { code: 'SCREEN_UNAVAILABLE' });
    assert.equal(f.admitted.length, 0); assert.equal(f.created.size, 1);
    assert.equal(await collect(a.chat(body(s.id, 'normal-after-screen-error'))), 'hello world');
    await a.dispose();
  }
});

check('screen rejects malformed, oversized, extra or unexpected image inputs before native writes', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  const cases = [[], Array(2).fill(screenBody(s.id, 'x').dafeiyu.images[0]),
    [{ mime_type: 'image/jpeg', data: 'bad', width: 1, height: 1 }],
    [{ mime_type: 'image/jpeg', data: '/9j/2Q==', width: 961, height: 1 }]];
  for (const [index, images] of cases.entries()) {
    const request = screenBody(s.id, `bad-${index}`); request.dafeiyu.images = images;
    await assert.rejects(collect(a.chat(request)), { code: 'INVALID_REQUEST' });
  }
  const ordinary = body(s.id, 'not-screen'); ordinary.dafeiyu.images = screenBody(s.id, 'x').dafeiyu.images;
  await assert.rejects(collect(a.chat(ordinary)), { code: 'INVALID_REQUEST' });
  assert.equal(f.admitted.length, 0); assert.equal(f.rows.get(s.id).requests.length, 0);
  await a.dispose();
});

check('screen native admission failure and timeout cannot invoke an agent or wedge next normal turn', async () => {
  for (const admission of [async () => { throw Error('private decoder failure'); }, () => new Promise(() => {})]) {
    const f = fixture(); f.ctx.attachments.admitPromptContent = admission;
    const a = await createHarnessAdapter(f.ctx, { ...config, timeoutMs: 20 }), s = await a.session();
    await assert.rejects(collect(a.chat(screenBody(s.id, 'admission-fail'))), error => ['AGENT_ERROR', 'TIMEOUT'].includes(error.code));
    assert.equal(f.created.size, 1);
    assert.equal(await collect(a.chat(body(s.id, 'after-admission'))), 'hello world');
    await a.dispose();
  }
});

check('cancel drains and a subsequent request starts only after old agent is idle', async () => {
  const f = fixture(); f.setBehavior('hold'); const a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  const iter = a.chat(body(s.id, 'hold')); const pending = iter.next();
  await new Promise(resolve => setTimeout(resolve, 20));
  await assert.rejects(collect(a.chat(body(s.id, 'parallel'))), e => e.code === 'SESSION_BUSY');
  await a.cancel(s.id, 'wrong');
  await a.cancel(s.id, 'hold');
  await assert.rejects(pending, e => e.code === 'CANCELLED');
  f.setBehavior('auto'); assert.equal(await collect(a.chat(body(s.id, 'next'))), 'hello world');
  await a.dispose();
});

check('blocked native turn reports explicit status', async () => {
  const f = fixture(); f.setBehavior('blocked'); f.setTokens([]);
  const a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  await assert.rejects(collect(a.chat(body(s.id, 'blocked'))), e => e.code === 'ACTION_REQUIRED' && e.status === 409);
  await a.dispose();
});

check('cancel releases a stream whose consumer paused after a token', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  const iter = a.chat(body(s.id, 'paused'));
  assert.equal((await iter.next()).value, 'hello');
  await a.cancel(s.id, 'paused');
  assert.equal((await iter.next()).done, true);
  assert.equal(await collect(a.chat(body(s.id, 'after-paused'))), 'hello world');
  await a.dispose();
});

check('existing owned agents follow changed native defaults at the next request', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  await collect(a.chat(body(s.id, 'model-a')));
  const original = f.live.get(s.id).agent;
  const next = { provider: 'another-native-provider', model: 'next-model', reasoningEffort: 'high' };
  f.setModel(next);
  await collect(a.chat(body(s.id, 'model-b')));
  assert.equal(f.live.get(s.id).agent, original);
  assert.deepEqual(original.model.current(), next);
  assert.equal((await a.status()).model, 'next-model');
  await a.dispose();
});

check('timeout and abort fail explicitly before any token and leave the agent idle', async () => {
  const f = fixture(); f.setBehavior('hold');
  const a = await createHarnessAdapter(f.ctx, { ...config, timeoutMs: 20 }), s = await a.session();
  await assert.rejects(collect(a.chat(body(s.id, 'timeout'))), e => e.code === 'TIMEOUT' && e.status === 504);
  assert.equal(f.live.get(s.id).agent.status, 'idle');
  const abort = new AbortController();
  const rejected = assert.rejects(collect(a.chat(body(s.id, 'aborted'), abort.signal)), e => e.code === 'CANCELLED' && e.status === 499);
  await waitFor(() => f.live.get(s.id).agent.inputs.length === 2);
  abort.abort(); await rejected;
  f.setBehavior('auto');
  assert.equal(await collect(a.chat(body(s.id, 'after-abort'))), 'hello world');
  await a.dispose();
});

check('native approval stays owned by DSH and reports ACTION_REQUIRED on bounded wait', async () => {
  const f = fixture(); f.setBehavior('hold');
  const a = await createHarnessAdapter(f.ctx, { ...config, timeoutMs: 30 }), s = await a.session();
  const rejected = assert.rejects(collect(a.chat(body(s.id, 'approval'))), e => e.code === 'ACTION_REQUIRED' && e.status === 409);
  await waitFor(() => f.live.get(s.id).agent.status === 'running');
  f.emit('session/event', f.live.get(s.id).agent.session, { type: 'approval/asked', data: { id: 'native-approval' } });
  await rejected;
  await a.dispose();
});

check('late frames and other agents cannot enter a new request', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  await collect(a.chat(body(s.id, 'old')));
  f.setBehavior('hold');
  const iter = a.chat(body(s.id, 'new'));
  const next = iter.next();
  await waitFor(() => f.live.get(s.id).agent.inputs.length === 2);
  const agent = f.live.get(s.id).agent;
  f.emit('agent/assistant-stream', { agent, frame: { type: 'start', attemptId: 'attempt-1', turn: 1, revision: 1 } });
  f.emit('agent/assistant-stream', { agent, frame: { type: 'chunk', attemptId: 'attempt-1', revision: 1, index: 0, chunk: { type: 'text-delta', text: 'late' } } });
  f.emit('agent/assistant-stream', { agent: {}, frame: { type: 'start', attemptId: 'foreign', turn: 2, revision: 2 } });
  f.emit('agent/assistant-stream', { agent, frame: { type: 'start', attemptId: 'current', turn: 2, revision: 2 } });
  f.emit('agent/assistant-stream', { agent, frame: { type: 'chunk', attemptId: 'current', revision: 3, index: 0, chunk: { type: 'text-delta', text: 'current' } } });
  assert.equal((await next).value, 'current');
  await a.cancel(s.id, 'new');
  await a.dispose();
});

check('non-draining requests stay quarantined and report drain failure', async () => {
  const f = fixture(); f.setBehavior('hold'); f.setStuck(true);
  const a = await createHarnessAdapter(f.ctx, { ...config, timeoutMs: 20, drainTimeoutMs: 20 }), s = await a.session();
  await assert.rejects(collect(a.chat(body(s.id, 'stuck'))), e => e.code === 'DRAIN_TIMEOUT' && e.status === 504);
  await assert.rejects(collect(a.chat(body(s.id, 'unsafe-replacement'))), e => e.code === 'SESSION_BUSY');
  f.setStuck(false); f.live.get(s.id).agent.cancel();
  await a.dispose();
});

check('factory cancellation cleans up late publication and never sends the partial to the main agent', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, { ...config, timeoutMs: 20 }), s = await a.session();
  let release;
  f.setGate(new Promise(resolve => { release = resolve; }));
  await assert.rejects(collect(a.chat(body(s.id, 'cancel-create', 'initiative'))), e => e.code === 'TIMEOUT');
  release();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal([...f.live.keys()].length, 1);
  assert.equal(f.live.get(s.id).agent.inputs.length, 0);
  await a.dispose();
});

check('missing model, empty output, foreign sessions and disposal expose stable errors', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, config), s = await a.session();
  await assert.rejects(a.messages('not-owned'), e => e.code === 'SESSION_NOT_FOUND' && e.status === 404);
  f.logs.set('foreign', []);
  await assert.rejects(a.session('foreign'), e => e.code === 'SESSION_IN_USE' && e.status === 409);
  assert.equal((await a.sessions()).length, 1);
  f.setModel({});
  await assert.rejects(collect(a.chat(body(s.id, 'missing-model'))), e => e.code === 'DSH_UNAVAILABLE' && e.status === 503);
  f.setModel({ provider: 'fake', model: 'fake-model' }); f.setTokens([]);
  await assert.rejects(collect(a.chat(body(s.id, 'empty'))), e => e.code === 'EMPTY_RESPONSE' && e.status === 503);
  await a.dispose();
  await assert.rejects(a.session(), e => e.code === 'DISPOSED' && e.status === 503);
});

check('initiative context comes from native history with per-request length guidance only', async () => {
  const f = fixture(), a = await createHarnessAdapter(f.ctx, { ...config, initiativeMaxChars: 48 }), s = await a.session();
  await collect(a.chat(body(s.id, 'context')));
  await a.playback({ session_id: s.id, generation_id: 'context', text: 'hello' });
  f.setTokens(['\u{1f600}'.repeat(100)]);
  const request = body(s.id, 'eighty', 'initiative');
  request.dafeiyu.max_reply_chars = 80;
  request.dafeiyu.confirmed_messages = [{ role: 'assistant', content: 'FORGED_CONFIRMED_BODY' }];
  request.messages[0].content = 'FORGED_HISTORY_BODY';
  const output = await collect(a.chat(request));
  assert.equal(Array.from(output).length, 100);
  const child = [...f.created.entries()].find(([id]) => id.startsWith('dafeiyu-preview-'))[1];
  const prompt = child.prompts[0];
  assert.match(prompt, /"role":"user","content":"new input"/);
  assert.match(prompt, /"role":"assistant","content":"hello"/);
  assert.match(prompt, /preferably around 80 characters/);
  assert.doesNotMatch(prompt, /hello world|FORGED_CONFIRMED_BODY|FORGED_HISTORY_BODY/);
  assert.equal(f.live.get(s.id).agent.inputs.length, 1);
  const normal = body(s.id, 'normal-limit'); normal.dafeiyu.max_reply_chars = 8;
  assert.equal(Array.from(await collect(a.chat(normal))).length, 100);
  for (const bad of [7, 81, 8.5, '48']) {
    const invalid = body(s.id, `bad-${bad}`, 'initiative'); invalid.dafeiyu.max_reply_chars = bad;
    await assert.rejects(collect(a.chat(invalid)), e => e.code === 'INVALID_REQUEST' && e.status === 400);
  }
  await a.dispose();
});
