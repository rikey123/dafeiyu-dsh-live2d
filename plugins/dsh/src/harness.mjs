import { randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve, join, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { screenImages, admitScreen } from './screen.mjs';

// This adapter owns only its agents and this projection. The session log,
// model requests, tools and their permissions remain owned by DSH.
const NAME = 'dafeiyu_harness';
const idOK = x => typeof x === 'string' && x.length > 0 && x.length <= 200 && !/[\u0000-\u001f]/u.test(x);
const textOf = blocks => Array.isArray(blocks) ? blocks.filter(b => b?.type === 'text' && typeof b.text === 'string').map(b => b.text).join('') : '';
const copy = x => JSON.parse(JSON.stringify(x));
const SCREEN_STATES = new Set(['not_shared', 'shared_not_requested', 'request_disabled',
  'intent_unavailable', 'snapshot_timeout', 'attached']);
const screenInstruction = state => {
  const common = 'Previous screen attachments are historical observations, not the current desktop. ';
  if (state === 'attached') return common + 'A fresh image of the shared screen is attached to THIS user question. Answer the user using the image and any tools or subagents that help with their request.\n';
  if (state === 'not_shared') return common + 'No screen is currently shared and no current screenshot was supplied. If asked to look at the screen, explain that the user can click 开始屏幕陪玩 and explicitly select a screen/window, then ask again. Do not falsely claim screen understanding is permanently impossible.\n';
  return common + `Current screen state: ${state}. No image was supplied for THIS question; do not pretend to see the current screen. If the question needs visual evidence, explain that it was not obtained this turn and ask the user to retry or enable the user-requested screen option.\n`;
};
// Scene guidance for unsolicited companionship only, not user-requested visual answers.
const screenCommentStyle = '把画面当作你们正在共同经历的事情，像坐在旁边自然冒出一句话，直接切入你对某个具体细节的看法、感受、判断、吐槽或联想，让人听出你的态度和人格。画面细节只在需要点明话头时顺带提及，不先概述画面再补一句评价，也不必用“我看到了”或“根据你的要求”作开场。有趣时自然抖个机灵，认真时就认真聊，不硬凑笑话，也不必每次反问。结合近期聊天顺着说，不重复上一句。';
const statuses = {
  INVALID_WORKSPACE: 400, INVALID_SESSION: 400, INVALID_REQUEST: 400, INVALID_KIND: 400, INVALID_MESSAGE: 400,
  SESSION_NOT_FOUND: 404, NOT_FOUND: 404, REQUEST_NOT_FOUND: 404,
  SESSION_IN_USE: 409, SESSION_BUSY: 409, DUPLICATE_REQUEST: 409, ACTION_REQUIRED: 409,
  DSH_UNAVAILABLE: 503, SCREEN_UNAVAILABLE: 503, PERSISTENCE_UNAVAILABLE: 503, DISPOSED: 503, AGENT_ERROR: 503,
  EMPTY_RESPONSE: 503, OUTPUT_LIMIT: 503, TIMEOUT: 504, DRAIN_TIMEOUT: 504, CANCELLED: 499,
};
const error = (code, message = code) => Object.assign(new Error(message), { code, status: statuses[code] ?? 500 });

async function runtimeModules(root) {
  const req = createRequire(root ? join(resolve(root), '@deepseek-ai/dsh/package.json') : import.meta.url);
  const load = name => import(pathToFileURL(req.resolve(name)).href);
  const [agent, llm, storage, zod] = await Promise.all([
    load('@deepseek-ai/dsh-agent'), load('@deepseek-ai/dsh-llm/message'),
    load('@deepseek-ai/dsh-storage-domain'), load('zod'),
  ]);
  return { installModelSelection: agent.installModelSelection, createUserMessage: llm.createUserMessage,
    defineDomain: storage.defineDomain, z: zod.z };
}

/** Create a DSH-backed adapter. Methods that touch storage are asynchronous. */
export async function createHarnessAdapter(ctx, config = {}) {
  if (!config.workspacePath || !isAbsolute(config.workspacePath)) throw error('INVALID_WORKSPACE', 'workspacePath must be absolute');
  for (const key of ['agents', 'agentDefaultModel', 'sessionPersistence', 'workspaceRegistry', 'storageDomain', 'sessions']) {
    if (!ctx[key]) throw error('DSH_UNAVAILABLE', `missing DSH service: ${key}`);
  }
  if (typeof ctx.on !== 'function') throw error('DSH_UNAVAILABLE', 'missing Cordis event subscription');
  const { installModelSelection, createUserMessage, defineDomain, z } = await runtimeModules(config.runtimeModulesRoot);
  // Native attachment references only. The image bytes and canonical observation
  // remain in DSH storage, not a second screenshot store or memory engine.
  const observationSchema = z.object({
    observedAt:z.string(), input:z.string(),
    images:z.array(z.object({type:z.literal('image'), attachment:z.object({
      attachmentId:z.string(), mediaType:z.string(), bytes:z.number(), width:z.number(), height:z.number(),
    }).passthrough()}).passthrough()),
  });
  const projectionSchema = z.object({
    id: z.string(), title: z.string(), created_at: z.string(),
    requests: z.array(z.object({ id: z.string(), userId: z.string(), generated: z.string(),
      played: z.string(), interrupted: z.boolean(), sealed: z.boolean().default(false), kind: z.enum(['normal', 'initiative', 'delegation', 'screen', 'idle']).default('normal'), state: z.enum(['pending', 'done', 'failed']), created_at: z.string(),
      observation:observationSchema.optional(), ending:z.string().optional() })),
  });
  const domain = await ctx.storageDomain.open(defineDomain({ name: NAME, version: 1, tables: { sessions: { valueSchema: projectionSchema } } }));
  const table = domain.table('sessions');
  const owned = new Map();
  const active = new Map();
  const personas = new Map();
  let disposed = false;
  let disposal;
  let serial = Promise.resolve();
  let screenCapability;
  async function status() {
    const selection = ctx.agentDefaultModel.currentSelection();
    const base = { ready: !!(selection?.provider && selection?.model), provider: 'dsh', model: selection?.model ?? null, configured: true };
    const key = `${selection?.provider}\0${selection?.model}`;
    if (!screenCapability || screenCapability.key !== key || Date.now() - screenCapability.at > 60000) {
      const promise = (async () => {
        const llm = typeof ctx.get === 'function' ? ctx.get('llm') : ctx.llm;
        const attachments = typeof ctx.get === 'function' ? ctx.get('attachments') : ctx.attachments;
        if (!base.ready || !llm?.resolveModelInfo || !attachments?.admitPromptContent) return false;
        const signal = AbortSignal.timeout(1500);
        try {
          const model = await Promise.race([llm.resolveModelInfo(selection.provider, selection.model, signal),
            new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), {once:true}))]);
          return model?.inputModalities?.includes('image') === true;
        } catch { return false; }
      })();
      screenCapability = {key, at:Date.now(), promise};
    }
    const ready = await screenCapability.promise;
    return {...base, screen_ready:ready, screen_reason:ready ? 'image_model' : 'requires_image_capable_dsh_model'};
  }
  const exclusive = fn => {
    const next = serial.then(fn);
    serial = next.catch(() => {});
    return next;
  };
  const timeoutMs = Number.isInteger(config.timeoutMs) && config.timeoutMs > 0 ? Math.min(config.timeoutMs, 600000) : 120000;
  const drainMs = Number.isInteger(config.drainTimeoutMs) && config.drainTimeoutMs > 0 ? Math.min(config.drainTimeoutMs, 60000) : 5000;
  const initiativeMaxChars = Number.isInteger(config.initiativeMaxChars) && config.initiativeMaxChars > 0 ? Math.min(config.initiativeMaxChars, 80) : 48;
  const requireOpen = () => { if (disposed) throw error('DISPOSED'); };
  const rowFor = id => {
    const row = table.get(id);
    if (!row || ctx.workspaceRegistry.archivedSessionIds.includes(id)) throw error('SESSION_NOT_FOUND');
    return row;
  };
  const publicRow = row => ({ id: row.id, title: row.title, created_at: row.created_at });
  const bounded = (promise, ms, code) => {
    let timer;
    return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(error(code)), ms); })])
      .finally(() => clearTimeout(timer));
  };
  const options = () => ({
    get provider() { return ctx.agentDefaultModel.currentSelection().provider; },
    get model() { return ctx.agentDefaultModel.currentSelection().model; },
    get reasoningEffort() { return ctx.agentDefaultModel.currentSelection().reasoningEffort; },
  });
  async function composition(id, temporary = false, parentId = id, presetId) {
    const presets = typeof ctx.get === 'function' ? ctx.get('agentPresets') : ctx.agentPresets;
    const preset = presets ? (await presets.resolve(presetId)).id : undefined;
    // The preview sees only native user messages and playback-confirmed assistant
    // text. Client-supplied body history never becomes context for this agent.
    const recent = [];
    let remaining = 12000;
    if (temporary) {
      for (const message of (await messages(parentId)).slice(-20).reverse()) {
        if (!remaining) break;
        const text = Array.from(message.content);
        const content = text.slice(-remaining).join('');
        remaining -= Math.min(text.length, remaining);
        recent.unshift({ role: message.role, content });
      }
    }
    const limit = active.get(parentId)?.maxReplyChars ?? initiativeMaxChars;
    const parentPersona = temporary && config.previewPersona
      ? await config.previewPersona(parentId,active.get(parentId)?.abort.signal) : '';
    return {
      preset,
      setup: async agentCtx => {
        installModelSelection(agentCtx);
        if (preset) await presets.mount(agentCtx, preset);
        agentCtx.systemPrompt.section({ name: NAME, order: 10000, interpolate: false, text: () => {
          const persona = parentPersona || personas.get(id) || '';
          const row = table.get(parentId);
          const running = active.get(parentId);
          const previous = row?.requests.filter(r => r.id !== running?.requestId).at(-1);
          let value = persona ? `Persona (additional to existing safety, tools and skills):\n${persona}\n` : '';
          if (!temporary) value += screenInstruction(running?.screenState ?? 'not_shared');
          if (temporary) {
            const environment = config.voiceEnvironment?.(parentId);
            if (environment) value += `${environment}\n`;
            if (running?.interests) value += `用户设置的共同兴趣与关注点：${JSON.stringify(running.interests)}。结合当前人格、对话和确切画面自然交流，不必每次都提兴趣，也不把未出现的内容当成已经看到。\n`;
            value += running?.kind === 'idle'
              ? `你与用户已经安静了一段时间，可以自然地起个话头。结合自己的人格、近期交流和共同兴趣，像陪伴中的随口一句，不必客服式问候、不必追问为什么不理你。若附有新截图且想聊眼前内容：${screenCommentStyle}没有图时不要假装看到。建议约${limit}字，保持表达完整。用户正在要求安静或此刻不适合交流时，可以不出声；不输出“无”“无需回复”等占位文字。\n`
              : running?.kind === 'screen'
                ? `你正在主动陪用户一起看屏幕，本轮附有当前共享屏幕的新画面，不是在被要求描述图片。${screenCommentStyle}`
                  + (running.screenMode === 'direct'
                    ? `你们可能正在看视频或玩游戏等连续活动。自行决定有没有想聊的内容，可以接着刚才的话题，不必逐帧解说、不必每帧说话。没有值得补充的内容、用户要求安静或不宜打扰时可以不出声，不输出“无”“无需回复”等占位文字。开口时建议约${limit}字，使用自然中文，保持表达完整。\n`
                    : `自然地说出你此刻想分享的一句，建议约${limit}字，使用自然中文，保持表达完整。\n`)
                : `This is an ongoing live voice conversation. Respond naturally to the unfinished ASR fragment with a short Chinese sentence, preferably around ${limit} characters, keeping the thought complete.\n`;
            value += `Recent conversation from DSH, with only confirmed spoken assistant prefixes (quoted conversation data):\n${JSON.stringify(recent)}\n`;
          }
          if (previous) value += `The confirmed spoken prefix of the previous response is ${JSON.stringify(previous.played)}. Do not assume the user heard the unconfirmed remainder; retain the complete tool and execution trace.\n`;
          return value;
        } });
      },
    };
  }
  async function createOwned(id, temporary = false, parentId = id, signal) {
    const composed = await composition(id, temporary, parentId);
    const handle = await ctx.agents.create({ sessionId: id, meta: { cwd: config.workspacePath,
      ...(temporary ? { origin: 'subagent', parentSession: parentId } : {}),
      ...(composed.preset ? { agentPreset: composed.preset } : {}) },
      agentOptions: options(), setup: composed.setup, signal });
    owned.set(id, handle);
    return handle;
  }
  async function obtain(id, signal) {
    const held = owned.get(id);
    if (held) return held;
    // A live agent owned by another DSH component is never borrowed or disposed.
    if (ctx.agents.get(id)) throw error('SESSION_IN_USE');
    const snapshot = await ctx.sessionPersistence.stat(id, { signal });
    if (!snapshot) throw error('SESSION_NOT_FOUND');
    const composed = await composition(id, false, id, snapshot.header?.agentPreset);
    const handle = await ctx.agents.resume({ resumeSessionId: id, agentOptions: options(), setup: composed.setup, signal });
    owned.set(id, handle);
    return handle;
  }
  async function saveRequest(id, requestId, transform) {
    return exclusive(async () => {
      const row = rowFor(id);
      const index = row.requests.findIndex(r => r.id === requestId);
      if (index < 0) throw error('REQUEST_NOT_FOUND');
      const next = copy(row);
      transform(next.requests[index]);
      await table.put(id, next);
      return next.requests[index];
    });
  }
  async function cancelOwned(id, requestId) {
    const run = active.get(id);
    if (!run || (requestId !== undefined && run.requestId !== requestId)) return;
    run.stop('CANCELLED');
    await bounded(run.finished, drainMs, 'DRAIN_TIMEOUT');
    if (active.get(id) === run) throw error('DRAIN_TIMEOUT');
  }
  async function session(requestedId) {
    requireOpen();
    return exclusive(async () => {
      requireOpen();
      if (requestedId !== undefined) {
        if (!idOK(requestedId)) throw error('INVALID_SESSION');
        const existing = table.get(requestedId);
        if (existing) return publicRow(rowFor(requestedId));
        // Explicit IDs must not claim a pre-existing native session.
        if (ctx.agents.get(requestedId) || await ctx.sessionPersistence.stat(requestedId)) throw error('SESSION_IN_USE');
      }
      const id = requestedId ?? `dafeiyu-${randomUUID()}`;
      const handle = await createOwned(id);
      try {
        const flushed = await ctx.sessions.flush(handle.agent.session);
        if (!flushed) throw error('PERSISTENCE_UNAVAILABLE');
        const row = { id, title: '\u65b0\u4f1a\u8bdd', created_at: new Date().toISOString(), requests: [] };
        await table.put(id, row);
        return publicRow(row);
      } catch (e) { owned.delete(id); await handle.dispose(); throw e; }
    });
  }
  async function messages(id) {
    requireOpen();
    rowFor(id);
    if (config.nativeHistory) return config.nativeHistory(id);
    const handle = owned.get(id);
    if (handle) {
      const flushed = await ctx.sessions.flush(handle.agent.session);
      if (!flushed) throw error('PERSISTENCE_UNAVAILABLE');
    }
    const reader = await ctx.sessionPersistence.open(id, 'read');
    let events;
    try { ({ events } = await reader.read()); } finally { await reader.close(); }
    const row = rowFor(id);
    const byUser = new Map(events.filter(event => event.type === 'user/message').map(event => [event.data?.id, event]));
    const result = [];
    for (const req of row.requests) {
      const event = byUser.get(req.userId);
      if (event) {
        const content = textOf(event.data.content);
        if (content) result.push({ id: event.data.id, role: 'user', content, interrupted: false, created_at: new Date(event.time).toISOString() });
      }
      if (req.played) result.push({ id: req.id, role: 'assistant', content: req.played, interrupted: req.interrupted || req.state !== 'done' || req.played !== req.generated, created_at: req.created_at });
    }
    return result;
  }
  async function deleteSession(id) {
    // UI deletion is native archival. DSH keeps its canonical log permanently
    // until the user manages that log through DSH itself.
    requireOpen();
    if (!table.get(id) || ctx.workspaceRegistry.archivedSessionIds.includes(id)) return false;
    await cancelOwned(id);
    await ctx.workspaceRegistry.archiveSession(id, { stopActivity: true });
    const handle = owned.get(id);
    if (handle) { await handle.dispose(); owned.delete(id); }
    return true;
  }
  async function playback({ session_id, generation_id, text, interrupted = false } = {}) {
    requireOpen();
    if (!idOK(session_id) || !idOK(generation_id) || typeof text !== 'string' || typeof interrupted !== 'boolean') return { accepted: false };
    return exclusive(async () => {
      requireOpen();
      const row = table.get(session_id);
      if (!row || ctx.workspaceRegistry.archivedSessionIds.includes(session_id)) return { accepted: false };
      const idx = row.requests.findIndex(r => r.id === generation_id);
      if (idx < 0) return { accepted: false };
      const live = active.get(session_id);
      const request = row.requests[idx];
      const generated = live?.requestId === generation_id ? live.generated : request.generated;
      if (request.sealed || !generated.startsWith(text) || !text.startsWith(request.played)) return { accepted: false };
      const next = copy(row);
      next.requests[idx].generated = generated;
      next.requests[idx].played = text;
      next.requests[idx].interrupted ||= interrupted;
      next.requests[idx].sealed ||= interrupted;
      await table.put(session_id, next);
      return { accepted: true };
    });
  }
  function chat(body, signal) {
    let iterator;
    async function* iterate() {
      requireOpen();
      const meta = body?.dafeiyu;
      const id = meta?.session_id, requestId = meta?.request_id;
      if (!idOK(id) || !idOK(requestId)) throw error('INVALID_REQUEST');
      if (!['normal', 'initiative', 'delegation', 'screen', 'idle'].includes(meta.kind)) throw error('INVALID_KIND');
      const last = body.messages?.at(-1);
      if (last?.role !== 'user' || typeof last.content !== 'string' || !last.content.trim()) throw error('INVALID_MESSAGE');
      if (last.content.length > 50000 || (meta.persona !== undefined && (typeof meta.persona !== 'string' || meta.persona.length > 10000))) throw error('INVALID_MESSAGE');
      if (signal?.aborted) throw error('CANCELLED');
      const screen = meta.kind === 'screen';
      const idle = meta.kind === 'idle';
      if (meta.companion_interests !== undefined && (typeof meta.companion_interests !== 'string' || meta.companion_interests.length > 2000)) throw error('INVALID_REQUEST');
      if (meta.screen_mode !== undefined && (!screen || !['systemone','direct'].includes(meta.screen_mode))) throw error('INVALID_REQUEST');
      const requestedScreen = meta.kind === 'normal' && meta.screen_state === 'attached';
      if (meta.screen_state !== undefined && (meta.kind !== 'normal' || !SCREEN_STATES.has(meta.screen_state))) throw error('INVALID_REQUEST');
      const hasScreenInput = screen || requestedScreen || (idle && meta.images !== undefined);
      const images = hasScreenInput ? screenImages(meta.images, () => error('INVALID_REQUEST')) : undefined;
      if (!hasScreenInput && meta.images !== undefined) throw error('INVALID_REQUEST');
      const temporary = meta.kind === 'initiative' || screen || idle;
      if (temporary && meta.max_reply_chars !== undefined && (!Number.isInteger(meta.max_reply_chars) || meta.max_reply_chars < 8 || meta.max_reply_chars > (idle ? 240 : screen ? 120 : 80))) throw error('INVALID_REQUEST');
      const maxReplyChars = temporary ? (meta.max_reply_chars ?? (screen || idle ? 64 : initiativeMaxChars)) : undefined;
      const observedAt = new Date().toISOString();
      const agentId = temporary ? `dafeiyu-preview-${randomUUID()}` : id;
      let run, message;
      await exclusive(async () => {
        requireOpen();
        rowFor(id);
        if (active.has(id)) throw error('SESSION_BUSY');
        for (const [, row] of table.entries()) if (row.requests.some(r => r.id === requestId)) throw error('DUPLICATE_REQUEST');
        message = createUserMessage({ content: [{ type: 'text', text: last.content }], source: { kind: 'user' } });
        let finish;
        const finished = new Promise(resolve => { finish = resolve; });
        let signalStop;
        const stopped = new Promise(resolve => { signalStop = resolve; });
        run = { requestId, agentId, kind: meta.kind, hasScreenInput, screenState:meta.screen_state,
          screenMode:meta.screen_mode ?? 'systemone', interests:meta.companion_interests ?? '',
          maxReplyChars, generated: '', received: '', reason: undefined, finish, finished, stopped,
          abort: new AbortController(), approvals: new Set(),
          stop(reason) {
            if (!this.reason) { this.reason = reason; signalStop(reason); }
            this.abort.abort(error(this.reason));
            try { this.agent?.cancel({ kind: 'user' }); } catch { /* already disposed */ }
            this.notify?.();
            void iterator.return().catch(() => {});
          } };
        active.set(id, run);
        personas.set(agentId, meta.persona || '');
        {
          const row = copy(rowFor(id));
          row.requests.push({ id: requestId, userId: temporary ? '' : message.id, generated: '', played: '', interrupted: false, sealed: false, kind: meta.kind, state: 'pending', created_at: observedAt,
            ...(temporary ? {observation:{observedAt, input:last.content, images:[]}} : {}) });
          if (!temporary && row.title === '\u65b0\u4f1a\u8bdd') row.title = last.content.trim().slice(0, 40);
          try { await table.put(id, row); } catch (e) { active.delete(id); personas.delete(agentId); run.finish(); throw e; }
        }
      });
      let handle, offStream, offError, offSession, timer, abortListener, stopReason, wake;
      let factoryStarted = false;
      const queue = [];
      let done = false;
      const attempts = new Map();
      const notify = () => { if (wake) { const w = wake; wake = undefined; w(); } };
      run.notify = notify;
      const stopped = () => { stopReason ||= run.reason; return stopReason; };
      timer = setTimeout(() => run.stop(run.approvals.size ? 'ACTION_REQUIRED' : 'TIMEOUT'), timeoutMs);
      abortListener = () => run.stop('CANCELLED');
      signal?.addEventListener('abort', abortListener, { once: true });
      if (signal?.aborted) run.stop('CANCELLED');
      try {
        const screenSelection = hasScreenInput ? { ...ctx.agentDefaultModel.currentSelection() } : undefined;
        if (hasScreenInput) {
          const parts = await Promise.race([
            admitScreen(ctx, images, screenSelection, run.abort.signal, () => error('SCREEN_UNAVAILABLE')),
            run.stopped.then(reason => { throw error(reason); }),
          ]);
          // Keep the original native message ID recorded by the projection.
          // Recreating a user message here would orphan a normal visual turn.
          message = {...message, content:[{type:'text',text:last.content}, ...parts]};
          if (temporary) await saveRequest(id,requestId,request => { request.observation.images = copy(parts); });
        }
        factoryStarted = true;
        const opening = temporary ? createOwned(agentId, true, id, run.abort.signal) : obtain(id, run.abort.signal);
        try { handle = await Promise.race([opening, run.stopped.then(reason => { throw error(reason); })]); }
        catch (e) {
          // A late factory publication is disposed by its owner; quarantine this id until then.
          opening.then(async late => { try { await late.dispose(); } finally { owned.delete(agentId); active.delete(id); } }, () => active.delete(id)).catch(() => {});
          throw e;
        }
        run.agent = handle.agent;
        if (stopped()) throw error(stopReason);
        const agent = handle.agent;
        if (agent.status !== 'idle') throw error('SESSION_BUSY');
        // In rc1 a recorded request takes precedence over the live option getters.
        // Refresh the native session selection at the next request boundary.
        const selection = screenSelection ?? ctx.agentDefaultModel.currentSelection();
        if (!selection?.provider || !selection?.model) throw error('DSH_UNAVAILABLE', 'no default model selected');
        const current = agent.model.current();
        if (!current || current.provider !== selection.provider || current.model !== selection.model || current.reasoningEffort !== selection.reasoningEffort) {
          agent.model.select(selection);
        }
        offStream = ctx.on('agent/assistant-stream', ({ agent: subject, frame }) => {
          if (subject !== agent || active.get(id) !== run || stopped()) return;
          if (frame.type === 'start' && frame.turn === run.turn) attempts.set(frame.attemptId, { revision: frame.revision, next: 0 });
          if (frame.type !== 'chunk') return;
          const attempt = attempts.get(frame.attemptId);
          if (!attempt || frame.revision <= attempt.revision || frame.index < attempt.next) return;
          if (frame.index !== attempt.next++) { run.stop('AGENT_ERROR'); return; }
          attempt.revision = frame.revision;
          if (frame.chunk?.type !== 'text-delta') return;
          let token = frame.chunk.text;
          if (typeof token !== 'string') return;
          if (run.received.length + token.length > 200000 || queue.length >= 4096) { run.stop('OUTPUT_LIMIT'); return; }
          if (token) { run.received += token; queue.push(token); notify(); }
        }, { global: true });
        offError = ctx.on('agent/error', ({ agent: subject }) => { if (subject === agent) run.stop('AGENT_ERROR'); }, { global: true });
        offSession = ctx.on('session/event', (subject, event) => {
          if (subject !== agent.session) return;
          if (event?.type === 'turn/start' && run.turn === undefined) run.turn = event.data.turn;
          if (event?.type === 'approval/asked') run.approvals.add(event.data.id);
          if (event?.type === 'approval/decided') run.approvals.delete(event.data.id);
          if (event?.type !== 'turn/end') return;
          const kind = event.data?.reason?.kind;
          run.ending = kind;
          if (kind && !['completed', 'max-tokens'].includes(kind) && !run.reason) run.stop(kind === 'blocked' ? 'ACTION_REQUIRED' : 'AGENT_ERROR');
        }, { global: true });
        agent.followup(message);
        const worker = (async () => {
          try { await agent.whenIdle(); } catch { stopReason ||= 'AGENT_ERROR'; }
          done = true; notify();
        })();
        while (!done || queue.length) {
          while (queue.length && !stopped()) {
            const token = queue.shift();
            run.generated += token;
            yield token;
          }
          if (stopped()) queue.length = 0;
          if (done) break;
          if (stopped()) {
            try { await bounded(worker, drainMs, 'DRAIN_TIMEOUT'); } catch { stopReason = 'DRAIN_TIMEOUT'; }
            break;
          }
          await new Promise(resolveWake => { wake = resolveWake; });
        }
        stopped();
        if (stopReason) throw error(stopReason);
        if (!run.generated && !(idle || (screen && run.screenMode === 'direct'))) throw error('EMPTY_RESPONSE');
      } catch (failure) {
        const code = statuses[failure?.code] ? failure.code : 'AGENT_ERROR';
        stopReason ||= code;
        throw statuses[failure?.code] ? failure : error(code);
      } finally {
        stopped();
        clearTimeout(timer);
        signal?.removeEventListener('abort', abortListener);
        offStream?.(); offError?.(); offSession?.();
        if (handle && !done) {
          run.stop(stopReason || 'CANCELLED');
          stopped();
          try { await bounded(handle.agent.whenIdle(), drainMs, 'DRAIN_TIMEOUT'); done = true; } catch { stopReason = 'DRAIN_TIMEOUT'; }
        }
        try {
          await saveRequest(id, requestId, req => {
            req.generated = run.generated;
            req.interrupted ||= !!stopReason;
            req.state = stopReason ? 'failed' : 'done';
            req.ending = run.ending ?? stopReason ?? 'completed';
          });
          if (!temporary && handle && done && !(await ctx.sessions.flush(handle.agent.session))) throw error('PERSISTENCE_UNAVAILABLE');
        } finally {
          try {
            if (temporary && handle) {
              await bounded(handle.dispose(), drainMs, 'DRAIN_TIMEOUT');
              owned.delete(agentId);
            }
          } finally {
            personas.delete(agentId);
            // A non-drained agent remains quarantined until adapter disposal.
            if (done || !factoryStarted) active.delete(id);
            run.finish();
          }
        }
      }
    }
    iterator = iterate();
    return iterator;
  }
  return {
    status,
    async sessions() { requireOpen(); return [...table.entries()].map(([, row]) => row).filter(row => !ctx.workspaceRegistry.archivedSessionIds.includes(row.id)).map(publicRow); },
    session, messages, deleteSession, chat, playback,
    confirmedPreview(id, requestId) {
      const request = rowFor(id).requests.find(row => row.id === requestId);
      return request && ['screen','initiative','idle'].includes(request.kind)
        ? {text:request.played,kind:request.kind,observation:copy(request.observation ?? null),
          ending:request.ending ?? request.state,interrupted:request.interrupted} : undefined;
    },
    // Membership only. Native SessionController owns these actors and logs.
    async registerNativeSession(id) {
      return exclusive(async () => {
        requireOpen();
        if (!idOK(id)) throw error('INVALID_SESSION');
        if (!table.get(id)) await table.put(id, {id, title:'新会话', created_at:new Date().toISOString(), requests:[]});
        return publicRow(rowFor(id));
      });
    },
    async cancel(id, requestId) { requireOpen(); await cancelOwned(id, requestId); },
    dispose() {
      return disposal ??= (async () => {
        disposed = true;
        await serial;
        for (const run of active.values()) run.stop('CANCELLED');
        const drains = await Promise.allSettled([...active.values()].map(run => bounded(run.finished, drainMs, 'DRAIN_TIMEOUT')));
        const releases = await Promise.allSettled([...owned.values()].map(handle => bounded(handle.dispose(), drainMs, 'DRAIN_TIMEOUT')));
        await domain.close();
        if ([...drains, ...releases].some(result => result.status === 'rejected')) throw error('DRAIN_TIMEOUT');
      })();
    },
  };
}
