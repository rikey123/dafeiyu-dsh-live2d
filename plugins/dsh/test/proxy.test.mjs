import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request } from 'node:http';
import { once } from 'node:events';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createGatewayProxy, serveStatic, staticFile, ownerRejection } from '../src/proxy.mjs';

test('HTTP and upgrade admission delegates to DSH and refuses non-owner peers', () => {
  const req = {headers:{cookie:'never-decoded-by-plugin'}};
  for (const rejection of [401,403]) assert.equal(ownerRejection({admit:r => {assert.equal(r,req); return {rejection};}},req),rejection);
  assert.equal(ownerRejection({admit:() => ({peer:{principal:{kind:'owner'}}})},req),undefined);
  assert.equal(ownerRejection({admit:() => ({peer:{principal:{kind:'restricted'}}})},req),403);
});

async function listen(server, t) {
  const connections = new Set();
  server.on('connection', socket => {connections.add(socket); socket.once('close', () => connections.delete(socket));});
  server.listen(0,'127.0.0.1'); await once(server,'listening');
  t.after(() => new Promise(resolve => { for (const socket of connections) socket.destroy(); server.closeAllConnections(); server.close(resolve); }));
  return `http://127.0.0.1:${server.address().port}`;
}
test('same-origin proxy strips browser credentials, injects private token and streams the complete route', async t => {
  const upstream = createServer((req,res) => {
    assert.equal(req.headers.cookie,undefined); assert.equal(req.headers.authorization,undefined);
    assert.equal(req.headers['x-dafeiyu-plugin-token'],'host-private'); assert.equal(req.url,'/api/settings?voice=1');
    res.writeHead(200,{'set-cookie':'bad=1','content-type':'application/json'}); res.end('{"ready":true}');
  });
  const gatewayUrl = await listen(upstream,t);
  const proxy = createGatewayProxy({gatewayUrl, token:'host-private'}); t.after(() => proxy.dispose());
  const front = await listen(createServer((req,res) => proxy.http(req,res,req.url)),t);
  const result = await fetch(`${front}/api/settings?voice=1`,{headers:{cookie:'dsh=secret',authorization:'Bearer secret','x-dafeiyu-plugin-token':'forged'}});
  assert.equal(result.status,200); assert.equal(result.headers.get('set-cookie'),null); assert.deepEqual(await result.json(),{ready:true});
});

test('only fixed loopback gateway routes are forwarded; startup failure stays explicit', async t => {
  assert.throws(() => createGatewayProxy({gatewayUrl:'http://example.com',token:'x'}),/loopback/);
  const proxy = createGatewayProxy({gatewayUrl:'http://127.0.0.1:1',token:'x',ensure:async () => {throw new Error('secret');}});
  const url = await listen(createServer((req,res) => proxy.http(req,res,req.url)),t);
  assert.equal((await fetch(`${url}/admin`)).status,404);
  const failed = await fetch(`${url}/api/settings`); assert.equal(failed.status,503); assert.doesNotMatch(await failed.text(),/secret/);
});

test('runtime failure codes explain the stage without exposing exception text or posting the body', async t => {
  let forwarded=0, failure;
  const gatewayUrl=await listen(createServer((req,res)=>{forwarded++;res.end('{}');}),t);
  const proxy=createGatewayProxy({gatewayUrl,token:'private',ensure:async()=>{throw failure;}});
  t.after(()=>proxy.dispose());
  const front=await listen(createServer((req,res)=>proxy.http(req,res,req.url)),t);
  for(const [code,phrase] of [['gateway_busy','暂时繁忙'],['gateway_auth_mismatch','鉴权不一致'],['gateway_port_occupied','端口被其他服务占用'],['supervisor_failed','进程已退出']]){
    failure=Object.assign(new Error('provider-private-key must never be echoed'),{code});
    const response=await fetch(front+'/api/settings',{method:'PUT',headers:{'content-type':'application/json'},body:'{"tts_api_key":"secret-input"}'});
    assert.equal(response.status,503);const body=await response.json();
    assert.equal(body.code,code);assert(body.detail.includes(phrase));
    assert.doesNotMatch(JSON.stringify(body),/provider-private-key|secret-input/);
  }
  assert.equal(forwarded,0,'failed preflight must not forward, persist or replay a settings body');
});

test('a delayed readiness gate forwards a complete settings request exactly once', async t => {
  let release, calls=0;
  const gate=new Promise(resolve=>release=resolve);
  const gatewayUrl=await listen(createServer(async(req,res)=>{
    calls++;let body='';for await(const chunk of req)body+=chunk;
    assert.equal(req.method,'PUT');assert.equal(body,'{"tts_api_voice":"tide"}');
    res.writeHead(200,{'content-type':'application/json'});res.end('{"saved":true}');
  }),t);
  const proxy=createGatewayProxy({gatewayUrl,token:'private',ensure:()=>gate});t.after(()=>proxy.dispose());
  const front=await listen(createServer((req,res)=>proxy.http(req,res,req.url)),t);
  const pending=fetch(front+'/api/settings',{method:'PUT',headers:{'content-type':'application/json'},body:'{"tts_api_voice":"tide"}'});
  await new Promise(resolve=>setTimeout(resolve,20));assert.equal(calls,0);release();
  const response=await pending;assert.equal(response.status,200);assert.deepEqual(await response.json(),{saved:true});assert.equal(calls,1);
});

test('static assets support WASM, ranges, HEAD and ETag without path traversal', async t => {
  const directory = await mkdtemp(join(process.env.TEMP ?? tmpdir(),'dafeiyu-dsh-test-')); t.after(() => rm(directory,{recursive:true,force:true}));
  await mkdir(join(directory,'public')); await writeFile(join(directory,'public/test.wasm'),'abcdefgh'); await writeFile(join(directory,'secret.txt'),'private');
  const roots = [{directory:join(directory,'public')}];
  assert.equal(await staticFile(roots,'../secret.txt'),null); assert.equal(await staticFile(roots,'..\\secret.txt'),null); assert.equal(await staticFile(roots,'.env'),null);
  const url = await listen(createServer((req,res) => serveStatic(req,res,roots,req.url.slice(1))),t);
  const range = await fetch(`${url}/test.wasm`,{headers:{range:'bytes=2-4'}}); assert.equal(range.status,206); assert.equal(await range.text(),'cde'); assert.equal(range.headers.get('content-type'),'application/wasm');
  const head = await fetch(`${url}/test.wasm`,{method:'HEAD'}); assert.equal(head.headers.get('content-length'),'8'); assert.equal(await head.text(),'');
  assert.equal((await fetch(`${url}/test.wasm`,{headers:{'if-none-match':head.headers.get('etag')}})).status,304);
  assert.equal((await fetch(`${url}/test.wasm`,{headers:{range:'bytes=90-'}})).status,416);
});

test('WebSocket upgrade retains speech protocol and strips DSH credentials', async t => {
  let upgraded, upstreamSocket;
  const ready = new Promise(resolve => {upgraded=resolve;});
  const upstream = createServer();
  upstream.on('upgrade', (req,socket) => {
    upstreamSocket = socket;
    assert.equal(req.url,'/ws/voice?session_id=owned');
    assert.equal(req.headers.cookie,undefined); assert.equal(req.headers['x-dafeiyu-plugin-token'],'private');
    const accept = createHash('sha1').update(req.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    socket.on('error',() => {}); t.after(() => socket.destroy());
    const data = Buffer.from('{"type":"voice.ready"}'); socket.write(Buffer.concat([Buffer.from([0x81,data.length]),data])); upgraded();
  });
  const gatewayUrl=await listen(upstream,t), proxy=createGatewayProxy({gatewayUrl,token:'private'}); t.after(() => proxy.dispose());
  const frontend=createServer(); frontend.on('upgrade',(req,socket,head) => proxy.upgrade(req,socket,head,req.url));
  const url=await listen(frontend,t);
  const ws=new WebSocket(url.replace('http:','ws:')+'/ws/voice?session_id=owned'); t.after(() => ws.close());
  const received=await new Promise((resolve,reject) => {ws.onmessage=e=>resolve(e.data); ws.onerror=reject;});
  await ready; assert.equal(received,'{"type":"voice.ready"}');
  const closed = new Promise(resolve => ws.addEventListener('close',resolve,{once:true}));
  upstreamSocket.resetAndDestroy();
  await closed; // ECONNRESET must be owned by the proxy, not DSH's fail-loud process handler.
});

test('byte-tunnel preserves negotiated permessage-deflate and compressed frames', async t => {
  const compressed = Buffer.from([0xc2, 3, 0x62, 0x00, 0x00]);
  const upstream = createServer();
  upstream.on('upgrade', (req, socket) => {
    assert.equal(req.headers['sec-websocket-extensions'], 'permessage-deflate; client_max_window_bits');
    socket.on('error', () => {});
    t.after(() => socket.destroy());
    const accept = createHash('sha1').update(req.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n`);
    socket.write(compressed);
  });
  const gatewayUrl = await listen(upstream, t);
  const proxy = createGatewayProxy({gatewayUrl, token: 'private'});
  t.after(() => proxy.dispose());
  const frontend = createServer();
  frontend.on('upgrade', (req, socket, head) => proxy.upgrade(req, socket, head, req.url));
  const front = await listen(frontend, t);
  const req = request(front+'/ws/voice', {headers: {
    connection: 'Upgrade', upgrade: 'websocket', 'sec-websocket-version': '13',
    'sec-websocket-key': 'dGhlIHNhbXBsZSBub25jZQ==',
    'sec-websocket-extensions': 'permessage-deflate; client_max_window_bits',
  }});
  const upgraded = once(req, 'upgrade');
  req.end();
  const [response, socket, head] = await upgraded;
  t.after(() => socket.destroy());
  assert.equal(response.headers['sec-websocket-extensions'], 'permessage-deflate');
  let received = head;
  while (received.length < compressed.length) {
    const [part] = await once(socket, 'data');
    received = Buffer.concat([received, part]);
  }
  assert.deepEqual(received, compressed, 'the proxy must not decode or reframe negotiated bytes');
});
