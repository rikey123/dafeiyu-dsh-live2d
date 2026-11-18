import { randomUUID } from 'node:crypto';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import { createHarnessAdapter } from './harness.mjs';
import { screenImages } from './screen.mjs';

export const VOICE_BACKGROUND = '你正在通过一个带有数字人形象的界面，与用户进行一对一实时语音交流。用户既可以说话，也可以输入文字；语音转写和文字输入都属于这段对话。你的回复会显示在聊天窗口，并可由数字人朗读。聊天窗口也能展示图片、文件和其他内容。对于搜索视频、浏览网页、查询资料或操作等需要等待的请求，先自然地简短回应一句，让用户知道你听见了，再开始调用工具，不要一直无声地工作。用户在语音中提出的查询和操作与文字请求一样需要实际处理；决定执行时就调用相应工具，而不只口头承诺。较耗时或包含多个步骤的查询和操作优先交给子智能体处理，便于你在等待期间继续与用户交流。短小的事情可以直接做，不必为了委派而委派。任务进展、结果或遇到的问题根据实际执行情况在这段对话里告诉用户，等待较久时适时说说真实进展，不要等全部做完才出声，也不编造进展。';
const validId = value => typeof value === 'string' && value.length > 0 && value.length <= 200 && !/[\u0000-\u001f]/u.test(value);
const fail = (code, status = 400) => Object.assign(new Error(code), {code, status});
const publicText = content => Array.isArray(content) ? content.filter(x => x?.type === 'text' && typeof x.text === 'string').map(x => x.text).join('') : '';
const SCREEN_STATES = new Set(['not_shared','shared_not_requested','request_disabled','intent_unavailable','snapshot_timeout','attached']);

/** Transport and presentation adapter, not an Agent owner or a task scheduler. */
export async function createNativeAdapter(ctx, config = {}) {
  if (!ctx.sessionController) throw fail('DSH_UNAVAILABLE', 503);
  const require = createRequire(config.runtimeModulesRoot ? join(config.runtimeModulesRoot,'@deepseek-ai/dsh/package.json') : import.meta.url);
  const {createUserMessage} = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm/message')).href);
  const {isAppendSurfaceEvent, deriveEventMessage} = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-session/surface')).href);
  const {renderPrompt, PERSONA_PREFIX_SECTION, PERSONA_SUFFIX_SECTION} = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-system-prompt')).href);
  const {assembleContextFor} = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-agent')).href);
  let disposed = false;
  const channels = new Map(), voice = new Map(), sections = new Map(), screenRequests = new Map(), screenTurns = new Set(), screenStates = new Map();
  const epoch = randomUUID();
  let sequence = 0;
  const announced = new Map();
  async function messages(id, {observations = false} = {}) {
    const live = ctx.agents.get(id);
    if (live && !await ctx.sessions.flush(live.session)) throw fail('PERSISTENCE_UNAVAILABLE', 503);
    const reader = await ctx.sessionPersistence.open(id, 'read');
    try {
      const {events} = await reader.read();
      const transcript = events.flatMap(event => {
        // Human transcript uses append-origin events, not the compacted model
        // surface or its replacement copies. DSH owns both interpretations.
        if (!isAppendSurfaceEvent(event)) return [];
        const user = event.type === 'user/message' && event.data?.source?.kind === 'user';
        const assistant = event.type === 'assistant/message';
        if (!user && !assistant) return [];
        const message = deriveEventMessage(event);
        const content = publicText(message?.content);
        return content ? [{id:message.id, role:user ? 'user' : 'assistant', content, interrupted:false, created_at:new Date(event.time ?? Date.now()).toISOString()}] : [];
      });
      if (!observations) return transcript;
      // Read back DSH's own playback notices, including its not-yet-consumed
      // inbox. No parallel conversation/memory is kept. Cumulative ACKs replace
      // the same generation, so a co-watching preview sees what was really said
      // once instead of repeating it or treating its unplayed text as heard.
      const notices = new Map();
      const remember = (message, time) => {
        const source = message?.source;
        if (source?.kind !== 'dafeiyu-voice' || source.form !== 'notice' || !source.externalEventId) return;
        const content = publicText(message.content);
        if (!content) return;
        const previous = notices.get(source.externalEventId);
        if (previous && previous.playedChars > (source.playedChars ?? 0)) return;
        notices.set(source.externalEventId, {id:source.externalEventId, role:'assistant', content,
          playedChars:source.playedChars ?? 0, interrupted:!!source.interrupted,
          created_at:previous?.created_at ?? new Date(time ?? Date.now()).toISOString()});
      };
      for (const event of events) {
        if (isAppendSurfaceEvent(event) && event.type === 'user/message') remember(deriveEventMessage(event), event.time);
      }
      for (const message of live?.inbox?.nextStep ?? []) remember(message);
      return [...transcript, ...notices.values()].sort((a,b) => a.created_at.localeCompare(b.created_at)).slice(-40);
    } finally { await reader.close(); }
  }
  // Isolated screen/ASR comments do not own the ordinary conversation. Their
  // confirmed observations enter DSH's native inbox, not a second chat history.
  const legacy = await createHarnessAdapter(ctx, {...config, nativeHistory:id => messages(id,{observations:true}),
    voiceEnvironment:id => activeVoice(id) ? VOICE_BACKGROUND : '',
    previewPersona:async (id,signal) => (await voiceContext(id,signal)).persona});
  const requireSession = async id => {
    if (disposed) throw fail('DISPOSED', 503);
    if (!validId(id)) throw fail('INVALID_SESSION');
    if (!(await legacy.sessions()).some(row => row.id === id)) throw fail('SESSION_NOT_FOUND', 404);
  };
  const activeVoice = id => [...voice.values()].some(state => state.session_id === id && state.active);
  function attachBackground(agent) {
    if (sections.has(agent)) return;
    const releases = [];
    const release = agent.ctx.systemPrompt.section({name:'dafeiyu_voice_environment', order:10000, interpolate:false,
      text:() => (activeVoice(agent.id) ? VOICE_BACKGROUND : '') +
        (screenTurns.has(agent.id) ? '\n本轮问题附有用户当前共享屏幕的截图，可结合画面回应用户的请求。' : '') +
        (screenStates.has(agent.id) && !screenTurns.has(agent.id) ? '\n本轮没有附带新的屏幕截图，先前的截图是历史画面。' : '')});
    releases.push(release);
    releases.push(agent.ctx.on('dispose', () => { sections.delete(agent); screenTurns.delete(agent.id); screenStates.delete(agent.id); }));
    sections.set(agent, () => { for (const dispose of releases.reverse()) if (typeof dispose === 'function') dispose(); });
  }
  async function resolve(id) {
    const result = await ctx.sessionController.resolveAgent(id);
    if (!result.agent) throw fail('DSH_UNAVAILABLE', 503);
    attachBackground(result.agent);
    return result.agent;
  }
  // A channel exists only while a voice connection listens. No task leases,
  // replayed text history or pending-work queue are maintained here.
  const publish = (id, event) => {
    const channel = channels.get(id);
    if (!channel) return;
    const frame = {...event, event_id:`${epoch}:${++sequence}`};
    channel.recent.push(frame); channel.bytes += JSON.stringify(frame).length * 2;
    while (channel.recent.length > 4096 || channel.bytes > 2 * 1024 * 1024) {
      const removed = channel.recent.shift();
      channel.bytes -= JSON.stringify(removed).length * 2;
      channel.floor = Number(removed.event_id.slice(epoch.length + 1));
    }
    for (const listener of channel.listeners) listener(frame);
  };
  function finishAttempt(id, attempt, transportError = false) {
    if (!attempt.started) return;
    publish(id, {type:transportError ? 'response.error' : 'response.end', generation_id:attempt.id, kind:'normal', ...(transportError ? {code:'VOICE_STREAM_GAP'} : {})});
  }
  const offStream = ctx.on('agent/assistant-stream', ({agent, frame}) => {
    const channel = channels.get(agent.id);
    if (!channel) return; // child sessions are never spoken as parent output
    if (frame.type === 'start') {
      channel.attempts.set(frame.attemptId, {id:String(frame.attemptId), requestId:channel.requestId, revision:frame.revision, next:0, started:false});
      return;
    }
    const attempt = channel.attempts.get(frame.attemptId);
    if (!attempt || frame.revision <= attempt.revision) return;
    attempt.revision = frame.revision;
    if (frame.type === 'end') {
      finishAttempt(agent.id, attempt);
      channel.attempts.delete(frame.attemptId); return;
    }
    if (frame.type !== 'chunk' || frame.index < attempt.next) return;
    if (frame.index !== attempt.next++) { finishAttempt(agent.id, attempt, true); channel.attempts.delete(frame.attemptId); return; }
    if (frame.chunk?.type !== 'text-delta' || typeof frame.chunk.text !== 'string' || !frame.chunk.text) return;
    if (!attempt.started) {
      attempt.started = true;
      publish(agent.id, {type:'response.start', generation_id:attempt.id, kind:'normal', request_id:attempt.requestId});
    }
    publish(agent.id, {type:'response.text', generation_id:attempt.id, kind:'normal', text:frame.chunk.text});
  }, {global:true});
  const offError = ctx.on('agent/error', ({agent}) => {
    const channel = channels.get(agent.id);
    if (!channel) return;
    const spoken = [...channel.attempts.values()].filter(attempt => attempt.started);
    // Task/provider/tool diagnostics belong to DSH. Close only actual speech;
    // never invent an audio failure or a spoken explanation for an Agent error.
    for (const attempt of spoken) finishAttempt(agent.id, attempt);
    channel.attempts.clear();
  }, {global:true});
  const offSession = ctx.on('session/event', (session, event) => {
    if (event.type === 'user/message' && event.data?.source?.kind === 'user') {
      const requests = screenRequests.get(session.id), requestId = event.data.source.rpcId;
      const state = requests?.get(requestId); requests?.delete(requestId);
      if (requests && !requests.size) screenRequests.delete(session.id);
      if (state) screenStates.set(session.id,state); else screenStates.delete(session.id);
      if (state === 'attached') screenTurns.add(session.id); else screenTurns.delete(session.id);
    }
    if (event.type === 'turn/end') { screenTurns.delete(session.id); screenStates.delete(session.id); }
    const channel = channels.get(session.id);
    if (!channel) return;
    if (event.type === 'turn/start') channel.requestId = undefined;
    if (event.type === 'user/message' && event.data?.source?.kind === 'user') {
      channel.requestId = event.data.source.rpcId;
      const text = publicText(event.data.content);
      if (text) publish(session.id, {type:'conversation.user', message_id:event.data.id, text, request_id:channel.requestId});
    }
    if (event.type === 'turn/end') {
      for (const attempt of channel.attempts.values()) finishAttempt(session.id,attempt);
      channel.attempts.clear();
      publish(session.id, {type:'turn.end',request_id:channel.requestId});
    }
  }, {global:true});
  async function* events(id, signal, cursor) {
    await requireSession(id);
    signal?.throwIfAborted();
    let channel = channels.get(id);
    if (!channel) {
      if (channels.size >= 64) throw fail('OUTPUT_LIMIT', 503);
      channels.set(id, channel = {listeners:new Set(), attempts:new Map(), recent:[], bytes:0, floor:sequence});
    }
    clearTimeout(channel.expiry);
    const queue = []; let wake, overflow = false;
    const notify = () => { wake?.(); wake = undefined; };
    const listener = event => { if (queue.length >= 4096) overflow = true; else queue.push(event); notify(); };
    const abort = () => notify();
    channel.listeners.add(listener);
    signal?.addEventListener('abort', abort, {once:true});
    const heartbeat = setInterval(() => { queue.push({type:'heartbeat', event_id:channel.recent.at(-1)?.event_id ?? `${epoch}:${sequence}`}); notify(); }, 15000);
    heartbeat.unref?.();
    try {
      // Wire readiness before acknowledging a connection; input cannot outrun
      // the subscriber. No model invocation is needed to observe this Session.
      let openingCursor = `${epoch}:${sequence}`;
      if (cursor) {
        const suffix = typeof cursor === 'string' && cursor.startsWith(`${epoch}:`) ? cursor.slice(epoch.length + 1) : '';
        const position = /^\d{1,16}$/.test(suffix) ? Number(suffix) : NaN;
        if (!Number.isSafeInteger(position) || position < channel.floor || position > sequence) yield {type:'reset', event_id:openingCursor};
        else { openingCursor = cursor; queue.push(...channel.recent.filter(frame => Number(frame.event_id.slice(epoch.length + 1)) > position)); }
      }
      yield {type:'ready', event_id:openingCursor};
      while (!disposed && !signal?.aborted) {
        if (overflow) throw fail('OUTPUT_LIMIT', 503);
        while (queue.length && !signal?.aborted) yield queue.shift();
        if (!signal?.aborted && !disposed) await new Promise(resolveWake => { wake = resolveWake; });
      }
    } finally {
      clearInterval(heartbeat);
      channel.listeners.delete(listener); signal?.removeEventListener('abort', abort);
      if (!channel.listeners.size) {
        channel.expiry = setTimeout(() => {
          if (channels.get(id) !== channel || channel.listeners.size) return;
          channels.delete(id);
          for (const [key, state] of voice) if (state.session_id === id) voice.delete(key);
        }, 60000);
        channel.expiry.unref?.();
      }
    }
  }
  async function voiceState(state) {
    await requireSession(state?.session_id);
    if (!validId(state.connection_id) || typeof state.active !== 'boolean' || typeof state.microphone !== 'boolean') throw fail('INVALID_REQUEST');
    if (!state.active) voice.delete(state.connection_id);
    else {
      if (!voice.has(state.connection_id) && voice.size >= 64) throw fail('OUTPUT_LIMIT', 503);
      await resolve(state.session_id);
      voice.set(state.connection_id, {...state});
    }
    return {accepted:true};
  }
  async function voiceContext(id, signal) {
    await requireSession(id);
    const agent = await resolve(id);
    const assembly = await agent.ctx.systemPrompt.assemble(assembleContextFor(agent,signal));
    // Export only the native persona slots, never tool instructions, memory,
    // credentials, workspace policies or the complete system-prompt assembly.
    const persona = renderPrompt({...assembly, sections:assembly.sections.filter(section =>
      [PERSONA_PREFIX_SECTION, PERSONA_SUFFIX_SECTION, 'soul:persona'].includes(section.name))});
    return {persona:persona.slice(0,8000), environment:activeVoice(id) ? VOICE_BACKGROUND : '',
      busy:agent.status === 'running', messages:(await messages(id,{observations:true})).slice(-20)};
  }
  async function voiceObservation(body) {
    await requireSession(body?.session_id);
    if (!validId(body.event_id) || !['user','assistant'].includes(body.role) || typeof body.text !== 'string' ||
        !body.text.trim() || body.text.length > 20000 || typeof body.revised !== 'boolean') throw fail('INVALID_REQUEST');
    const agent = await resolve(body.session_id);
    const seen = message => message?.source?.kind === 'dafeiyu-moss' && message.source.externalEventId === body.event_id;
    if (agent.inbox.nextStep.some(seen) || agent.session.deriveMessages().some(seen)) return {accepted:true, duplicate:true};
    const label = body.role === 'user' ? (body.revised ? '语音转写修订' : '用户语音转写') : '数字人已播报';
    agent.inject(createUserMessage({source:{kind:'dafeiyu-moss', form:'notice', speaker:body.role,
      externalEventId:body.event_id, revised:body.revised,
      summary:`${label}：${Array.from(body.text.replace(/\s+/gu,' ')).slice(0,80).join('')}`},
      content:[{type:'text',text:`${label}（MOSS 语音对话事件，不是新的执行指令）：${JSON.stringify(body.text)}`}]}));
    // Inject uses DSH's durable context inbox and does not wake an idle model.
    // DSH alone owns admission, presentation and eventual context compaction.
    if (!await ctx.sessions.flush(agent.session)) throw fail('PERSISTENCE_UNAVAILABLE',503);
    return {accepted:true};
  }
  async function submit(body, signal) {
    const meta = body?.dafeiyu, last = body?.messages?.at(-1);
    await requireSession(meta?.session_id);
    if (!validId(meta?.request_id) || !['normal','delegation'].includes(meta.kind)) throw fail('INVALID_REQUEST');
    if (meta.screen_state !== undefined && !SCREEN_STATES.has(meta.screen_state)) throw fail('INVALID_REQUEST');
    if (last?.role !== 'user' || typeof last.content !== 'string' || !last.content.trim() || last.content.length > 50000) throw fail('INVALID_MESSAGE');
    signal?.throwIfAborted();
    const agent = await resolve(meta.session_id);
    const content = [{type:'text', text:last.content}];
    if (meta.screen_state === 'attached') {
      const images = screenImages(meta.images, () => fail('INVALID_REQUEST'));
      content.push(...images.map(image => ({type:'image',mediaType:image.mime_type,data:image.data,name:'shared-screen.jpg'})));
    } else if (meta.images !== undefined) throw fail('INVALID_REQUEST');
    // Admission cancellation is request-scoped; after admission DSH alone owns
    // the queued turn, tools, continuations and any subagent delivery.
    if (meta.screen_state !== undefined) {
      let requests = screenRequests.get(meta.session_id);
      if (!requests) screenRequests.set(meta.session_id, requests = new Map());
      if (requests.size >= 128) throw fail('OUTPUT_LIMIT', 503);
      requests.set(meta.request_id, meta.screen_state);
    }
    try {
      const result = await ctx.sessionController.prompt({sessionId:meta.session_id, requestId:meta.request_id, mode:'queue', content, clientTimeZone:'Asia/Shanghai'}, signal ?? new AbortController().signal);
      return {...result, request_id:meta.request_id};
    } catch (error) { screenRequests.get(meta.session_id)?.delete(meta.request_id); throw error; }
  }
  return {
    status:async () => ({...await legacy.status(), native_conversation:true, voice_events:true}),
    async sessions() {
      const rows = await legacy.sessions();
      const {items} = await ctx.sessionController.list({}, new AbortController().signal);
      const byId = new Map(items.map(item => [item.sessionId,item]));
      return rows.filter(row => byId.has(row.id)).map(row => {
        const item = byId.get(row.id);
        return {...row, title:item.projections?.values?.title || row.title};
      });
    },
    async session(id) {
      if (id !== undefined) {
        if (!validId(id)) throw fail('INVALID_SESSION');
        const existing = (await legacy.sessions()).find(row => row.id === id);
        if (existing) return existing;
        if (ctx.agents.get(id) || await ctx.sessionPersistence.stat(id)) throw fail('SESSION_IN_USE', 409);
      }
      const created = await ctx.sessionController.create({sessionId:id ?? `dafeiyu-${randomUUID()}`, cwd:config.workspacePath});
      return legacy.registerNativeSession(created.sessionId);
    },
    async messages(id) { await requireSession(id); return messages(id); },
    deleteSession:legacy.deleteSession,
    async playback(receipt) {
      const result = await legacy.playback(receipt);
      if (!result.accepted) return result; // ordinary native messages need no projection write
      const preview = legacy.confirmedPreview(receipt.session_id, receipt.generation_id);
      const previous = announced.get(receipt.generation_id);
      const previousText = previous?.text ?? '';
      if (!preview?.text || !preview.text.startsWith(previousText)) return result;
      if (preview.text === previousText && preview.ending === previous?.ending && preview.interrupted === previous?.interrupted) return result;
      const agent = await resolve(receipt.session_id);
      const playedChars = Array.from(preview.text).length;
      const seen = message => message?.source?.kind === 'dafeiyu-voice' &&
        message.source.externalEventId === receipt.generation_id && message.source.playedChars === playedChars &&
        message.source.ending === preview.ending && message.source.interrupted === preview.interrupted;
      const duplicate = agent.inbox.nextStep.some(seen) || agent.session.deriveMessages().some(seen);
      const label = preview.kind === 'idle' ? '安静后的主动搭话' : preview.kind === 'screen' ? '屏幕主动评论' : '说话中的主动接话';
      const observation = preview.observation;
      const content = [{type:'text', text:`${label}的交流记录（不是用户新提出的任务）：\n` +
        (observation ? `发生时间：${observation.observedAt}\n当时的交流场景：${observation.input}\n` : '') +
        `截至此时实际已播报的内容：${JSON.stringify(preview.text)}\n` +
        `生成结束状态：${preview.ending}；播放${preview.interrupted ? '已打断' : '未标记打断'}。` +
        (!previousText && observation?.images?.length ? '\n所附图片是触发这次主动评论时的历史屏幕画面。' : '')}];
      if (!previousText && observation?.images) content.push(...observation.images);
      // This is an observed speech event, not a fabricated human turn, a new
      // task, or a second memory. DSH's native context inbox consumes it without
      // waking the model; its standard notice renderer owns the presentation.
      if (!duplicate) agent.inject(createUserMessage({source:{kind:'dafeiyu-voice',form:'notice', externalEventId:receipt.generation_id,
        playedChars, ending:preview.ending, interrupted:preview.interrupted,
        summary:`${label}：${Array.from(preview.text.replace(/\s+/gu,' ')).slice(0,80).join('')}`},content}));
      if (!await ctx.sessions.flush(agent.session)) throw fail('PERSISTENCE_UNAVAILABLE',503);
      announced.set(receipt.generation_id,{text:preview.text,ending:preview.ending,interrupted:preview.interrupted});
      if (announced.size > 256) announced.delete(announced.keys().next().value);
      return result;
    },
    events, voiceState, voiceContext, voiceObservation, submit,
    chat(body, signal) {
      if (['screen','initiative','idle'].includes(body?.dafeiyu?.kind)) {
        return (async function* () {
          try {
            // Optional companionship must not compete with already running
            // native work. This never stops or cancels that work.
            if (body.dafeiyu.kind === 'idle' || body.dafeiyu.screen_mode === 'direct') {
              await requireSession(body.dafeiyu.session_id);
              if ((await resolve(body.dafeiyu.session_id)).status === 'running') return;
            }
            yield* legacy.chat({...body, dafeiyu:{...body.dafeiyu,persona:''}}, signal);
          }
          catch (error) {
            // Compatibility SSE distinguishes a DSH task outcome from a broken
            // audio bridge; no raw provider/tool errors enter the speech path.
            if (['AGENT_ERROR','ACTION_REQUIRED','EMPTY_RESPONSE'].includes(error.code)) throw fail('AGENT_ERROR',503);
            throw error;
          }
        })();
      }
      // Compatibility for non-realtime callers. Closing this reader never
      // cancels the admitted native turn or its delegated work.
      return (async function* () {
        const reader = new AbortController();
        const abort = () => reader.abort();
        signal?.addEventListener('abort', abort, {once:true});
        if (signal?.aborted) abort();
        const stream = events(body?.dafeiyu?.session_id, reader.signal);
        try {
          await stream.next();
          await submit(body, signal);
          let generation;
          let received = false;
          for await (const event of stream) {
            if (event.type === 'turn.end' && event.request_id === body.dafeiyu.request_id) {
              if (!received) throw fail('AGENT_ERROR',503);
              return;
            }
            if (event.type === 'response.start' && event.request_id === body.dafeiyu.request_id) generation = event.generation_id;
            if (event.generation_id !== generation) continue;
            if (event.type === 'response.text') { received = true; yield event.text; }
            if (event.type === 'response.error' && event.code === 'VOICE_STREAM_GAP') throw fail('VOICE_STREAM_GAP', 503);
          }
        } finally { reader.abort(); await stream.return(); signal?.removeEventListener('abort', abort); }
      })();
    },
    async dispose() {
      if (disposed) return;
      disposed = true; offStream(); offError(); offSession();
      for (const channel of channels.values()) {
        clearTimeout(channel.expiry);
        for (const listener of channel.listeners) listener({type:'closed'});
      }
      channels.clear(); voice.clear(); screenRequests.clear(); screenTurns.clear(); screenStates.clear();
      announced.clear();
      for (const release of sections.values()) release(); sections.clear();
      await legacy.dispose();
      // Native Agent handles are neither cancelled nor disposed here.
    },
  };
}
