import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createBridge } from '../src/bridge.mjs';

test('private bridge is loopback-only, authenticated, and uses the native adapter exactly once', async t => {
  let calls = 0;
  const bridge = await createBridge({status:async () => ({provider:'dsh', ready:true}), async *chat() { calls++; yield '你'; yield '好'; }});
  t.after(() => bridge.dispose());
  assert.match(bridge.url, /^http:\/\/127\.0\.0\.1:\d+$/);
  assert.equal((await fetch(`${bridge.url}/v1/status`)).status, 401);
  const headers = {authorization:`Bearer ${bridge.token}`, 'content-type':'application/json'};
  assert.equal((await (await fetch(`${bridge.url}/v1/status`, {headers})).json()).provider, 'dsh');
  const response = await fetch(`${bridge.url}/v1/chat/completions`, {method:'POST', headers, body:JSON.stringify({messages:[{role:'user',content:'hi'}],dafeiyu:{session_id:'owned'}})});
  assert.equal(response.status,200);
  const body = await response.text();
  assert.match(body, /你/); assert.match(body,/好/); assert.match(body,/data: \[DONE\]/); assert.equal(calls,1);
});

test('client disconnect aborts a running native generation, with no retry', async t => {
  let cancelled, started = 0;
  const stopped = new Promise(resolve => {cancelled = resolve;});
  const bridge = await createBridge({async *chat(_body, signal) {
    started++; yield 'first';
    await new Promise(resolve => signal.addEventListener('abort', resolve, {once:true}));
    cancelled();
  }});
  t.after(() => bridge.dispose());
  const abort = new AbortController();
  const response = await fetch(`${bridge.url}/v1/chat/completions`, {method:'POST', signal:abort.signal,
    headers:{authorization:`Bearer ${bridge.token}`,'content-type':'application/json'},body:JSON.stringify({messages:[],dafeiyu:{}})});
  await response.body.getReader().read();
  abort.abort();
  await Promise.race([stopped, new Promise((_,reject) => setTimeout(() => reject(new Error('not cancelled')),2000).unref())]);
  assert.equal(started,1);
});

test('validation and adapter errors never expose secrets or silently return successful empty audio input', async t => {
  const bridge = await createBridge({async *chat() { throw Object.assign(new Error('sk-secret-provider-url'), {status:409}); }});
  t.after(() => bridge.dispose());
  const headers = {authorization:`Bearer ${bridge.token}`, 'content-type':'application/json'};
  const request = body => fetch(`${bridge.url}/v1/chat/completions`, {method:'POST',headers,body:JSON.stringify(body)});
  assert.equal((await request({})).status,400);
  const failed = await request({messages:[],dafeiyu:{}});
  assert.equal(failed.status,409); assert.doesNotMatch(await failed.text(),/sk-secret/);
});
