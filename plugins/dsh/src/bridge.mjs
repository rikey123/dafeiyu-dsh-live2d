/** Private, authenticated transport only; the actual loop lives in DSH's Agents service. */
import { createServer } from 'node:http';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { once } from 'node:events';

export function secretEquals(actual, expected) {
  if (typeof actual !== 'string' || typeof expected !== 'string') return false;
  const a = Buffer.from(actual), b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function json(res, code, body) {
  if (res.destroyed || res.writableEnded) return;
  res.writeHead(code, {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store'});
  res.end(JSON.stringify(body));
}

export async function readJson(req, limit = 2 * 1024 * 1024) {
  if (!/^application\/json(?:;|$)/i.test(req.headers['content-type'] ?? '')) {
    throw Object.assign(new Error('JSON required'), {status: 415});
  }
  const parts = []; let bytes = 0;
  for await (const part of req) {
    bytes += part.length;
    if (bytes > limit) throw Object.assign(new Error('Request too large'), {status: 413});
    parts.push(part);
  }
  let value;
  try { value = JSON.parse(Buffer.concat(parts).toString('utf8')); }
  catch { throw Object.assign(new Error('Invalid JSON'), {status: 400}); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw Object.assign(new Error('Object required'), {status: 400});
  }
  return value;
}

async function write(res, text, signal) {
  if (signal.aborted || res.destroyed) throw new DOMException('Disconnected', 'AbortError');
  if (!res.write(text)) await once(res, 'drain', {signal});
}

export async function createBridge(adapter, {token = randomBytes(32).toString('base64url')} = {}) {
  const jobs = new Set();
  const server = createServer(async (req, res) => {
    if (!secretEquals(req.headers.authorization, `Bearer ${token}`)) {
      json(res, 401, {error: {message: 'Unauthorized'}}); return;
    }
    const controller = new AbortController(); jobs.add(controller);
    const abort = () => controller.abort();
    req.on('aborted', abort);
    res.on('close', abort);
    try {
      const url = new URL(req.url, 'http://127.0.0.1');
      const path = url.pathname;
      if (req.method === 'GET' && path === '/v1/status') return json(res, 200, await adapter.status());
      if (req.method === 'GET' && path === '/v1/sessions') return json(res, 200, await adapter.sessions());
      if (req.method === 'POST' && path === '/v1/sessions') {
        const body = await readJson(req);
        return json(res, 200, await adapter.session(body.session_id));
      }
      const match = /^\/v1\/sessions\/([^/]+)(\/messages)?$/.exec(path);
      if (match) {
        const id = decodeURIComponent(match[1]);
        if (req.method === 'GET' && match[2]) return json(res, 200, await adapter.messages(id));
        if (req.method === 'DELETE' && !match[2]) return json(res, 200, {deleted: await adapter.deleteSession(id)});
      }
      if (req.method === 'POST' && path === '/v1/playback') {
        return json(res, 200, await adapter.playback(await readJson(req)));
      }
      if (req.method === 'POST' && path === '/v1/voice/turns') {
        return json(res, 200, await adapter.submit(await readJson(req), controller.signal));
      }
      if (req.method === 'POST' && path === '/v1/voice/state') {
        return json(res, 200, await adapter.voiceState(await readJson(req)));
      }
      if (req.method === 'GET' && path === '/v1/voice/context') {
        return json(res, 200, await adapter.voiceContext(url.searchParams.get('session_id'),controller.signal));
      }
      if (req.method === 'POST' && path === '/v1/voice/observations') {
        return json(res, 200, await adapter.voiceObservation(await readJson(req)));
      }
      if (req.method === 'GET' && path === '/v1/voice/events') {
        const stream = adapter.events(url.searchParams.get('session_id'), controller.signal, req.headers['last-event-id']);
        for await (const event of stream) {
          if (!res.headersSent) res.writeHead(200, {'content-type':'text/event-stream; charset=utf-8', 'cache-control':'no-store', 'x-accel-buffering':'no'});
          const {event_id, ...data} = event;
          await write(res, `id: ${event_id}\ndata: ${JSON.stringify(data)}\n\n`, controller.signal);
        }
        return res.end();
      }
      if (req.method === 'POST' && path === '/v1/chat/completions') {
        const body = await readJson(req);
        if (!Array.isArray(body.messages) || !body.dafeiyu || typeof body.dafeiyu !== 'object') {
          return json(res, 400, {error: {message: 'DSH session and messages required'}});
        }
        const id = `chatcmpl-${randomBytes(10).toString('hex')}`;
        const stream = adapter.chat(body, controller.signal);
        if (body.stream === false) {
          let content = '';
          for await (const delta of stream) content += delta;
          return json(res, 200, {id, object: 'chat.completion', choices: [{index: 0, message: {role: 'assistant', content}, finish_reason: 'stop'}]});
        }
        // Headers are sent only after the adapter accepts the operation. Errors before its first token remain JSON.
        for await (const delta of stream) {
          if (!res.headersSent) res.writeHead(200, {'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-store', 'x-accel-buffering': 'no'});
          await write(res, `data: ${JSON.stringify({id, object: 'chat.completion.chunk', choices: [{index: 0, delta: {content: delta}, finish_reason: null}]})}\n\n`, controller.signal);
        }
        if (!res.headersSent) res.writeHead(200, {'content-type': 'text/event-stream', 'cache-control': 'no-store'});
        await write(res, `data: ${JSON.stringify({id, choices: [{index: 0, delta: {}, finish_reason: 'stop'}]})}\n\ndata: [DONE]\n\n`, controller.signal);
        return res.end();
      }
      json(res, 404, {error: {message: 'Not found'}});
    } catch (error) {
      if (controller.signal.aborted) return;
      // Never expose upstream provider credentials, prompts, stack traces or URLs.
      const status = Number.isInteger(error.status) && error.status >= 400 && error.status < 600 ? error.status : 502;
      const safe = new Set(['INVALID_SESSION','INVALID_REQUEST','INVALID_KIND','INVALID_MESSAGE','SESSION_NOT_FOUND','SESSION_IN_USE','SESSION_BUSY','DUPLICATE_REQUEST','ACTION_REQUIRED','DSH_UNAVAILABLE','SCREEN_UNAVAILABLE','PERSISTENCE_UNAVAILABLE','DISPOSED','AGENT_ERROR','EMPTY_RESPONSE','OUTPUT_LIMIT','TIMEOUT','DRAIN_TIMEOUT','CANCELLED']);
      const code = safe.has(error.code) ? error.code : 'DSH_UNAVAILABLE';
      if (!res.headersSent) json(res, status, {error: {code, message: `DSH operation failed (${status})`}});
      else { res.write(`data: ${JSON.stringify({error: {code, message: 'DSH operation failed'}})}\n\n`); res.end(); }
    } finally {
      jobs.delete(controller); req.off('aborted', abort); res.off('close', abort);
    }
  });
  server.requestTimeout = 30_000;
  server.headersTimeout = 10_000;
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return {
    url: `http://127.0.0.1:${server.address().port}`, token,
    async dispose() {
      for (const job of jobs) job.abort();
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    },
  };
}
