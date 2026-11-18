import { request } from 'node:http';
import { createReadStream } from 'node:fs';
import { realpath, stat } from 'node:fs/promises';
import { resolve, relative, sep, extname } from 'node:path';
import { pipeline } from 'node:stream';
import { json } from './bridge.mjs';

const HOP = new Set(['connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'proxy-authorization', 'proxy-authenticate', 'te', 'trailer']);
const MIME = {'.js':'text/javascript; charset=utf-8', '.mjs':'text/javascript; charset=utf-8', '.css':'text/css; charset=utf-8', '.json':'application/json', '.wasm':'application/wasm', '.png':'image/png', '.webp':'image/webp', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.svg':'image/svg+xml', '.ico':'image/x-icon', '.wav':'audio/wav', '.mp3':'audio/mpeg', '.ogg':'audio/ogg', '.mp4':'video/mp4', '.webm':'video/webm', '.woff2':'font/woff2', '.woff':'font/woff', '.txt':'text/plain; charset=utf-8', '.moc3':'application/octet-stream'};
const RUNTIME_FAILURES = Object.freeze({
  setup_required:'语音运行环境尚未安装或正在安装，请打开大肥鱼面板完成自动安装向导后重试。',
  gateway_busy:'本地语音服务暂时繁忙，本次请求尚未转发，请稍后重试。',
  gateway_auth_mismatch:'插件与本地语音服务的鉴权不一致，请重启大肥鱼插件；无需重填 TTS 密钥。',
  gateway_port_occupied:'本地语音网关端口被其他服务占用，插件未停止或接管该进程。',
  gateway_start_timeout:'本地语音服务启动超时，请查看 data/logs/dsh-plugin-runner.log。',
  supervisor_failed:'本地语音服务进程已退出，请查看 data/logs/dsh-plugin-runner.log。',
  supervisor_start_failed:'无法启动本地语音服务，请查看 data/logs/dsh-plugin-runner.log。',
  external_gateway_unavailable:'所配置的外部语音服务不可用，请先启动该服务。',
  plugin_disposed:'大肥鱼插件已关闭或正在重新加载，请刷新面板后重试。',
});
function runtimeFailure(error) {
  const code = typeof error?.code === 'string' && Object.hasOwn(RUNTIME_FAILURES, error.code) ? error.code : 'gateway_unavailable';
  return {code, detail:RUNTIME_FAILURES[code] ?? '本地语音服务尚未就绪，请查看 data/logs/dsh-plugin-runner.log'};
}
const within = (root, file) => { const name = relative(root, file); return name === '' || (!name.startsWith(`..${sep}`) && name !== '..' && !resolve(name).startsWith('\\\\') && !/^[A-Za-z]:/.test(name)); };

/** Use DSH's own signed-cookie and Host/Origin fence; never reimplement it. */
export function ownerRejection(connection, request) {
  const admission = connection.admit(request);
  if ('rejection' in admission) return admission.rejection;
  return admission.peer.principal?.kind === 'owner' ? undefined : 403;
}

/** Canonical roots are explicit, so a model-directory junction can live on E: without arbitrary file access. */
export async function staticFile(roots, path) {
  if (path.includes('\0') || path.includes('\\') || path.split('/').some(x => x.startsWith('.'))) return null;
  for (const {directory, prefix = ''} of roots) {
    if (prefix && !(path === prefix || path.startsWith(`${prefix}/`))) continue;
    try {
      const root = await realpath(directory);
      const candidate = resolve(root, path.slice(prefix.length).replace(/^\/+/, ''));
      if (!within(root, candidate)) continue;
      const actual = await realpath(candidate);
      if (!within(root, actual)) continue;
      const info = await stat(actual);
      if (info.isFile()) return {path: actual, info};
    } catch (error) { if (!['ENOENT', 'ENOTDIR', 'EACCES'].includes(error.code)) throw error; }
  }
  return null;
}

export async function serveStatic(req, res, roots, path) {
  if (!['GET', 'HEAD'].includes(req.method)) return json(res, 405, {detail:'Method not allowed'});
  const found = await staticFile(roots, path);
  if (!found) return json(res, 404, {detail:'Asset not found; run the DSH frontend build'});
  const {info} = found;
  const etag = `W/"${info.size.toString(16)}-${Math.floor(info.mtimeMs).toString(16)}"`;
  const headers = {'content-type': MIME[extname(found.path).toLowerCase()] ?? 'application/octet-stream', 'x-content-type-options':'nosniff', 'cache-control':'private, no-cache', 'accept-ranges':'bytes', etag};
  if (req.headers['if-none-match'] === etag) { res.writeHead(304, headers); return res.end(); }
  let start = 0, end = info.size - 1, code = 200;
  if (req.headers.range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
    if (!match || (!match[1] && !match[2])) { res.writeHead(416, {'content-range':`bytes */${info.size}`}); return res.end(); }
    if (!match[1]) start = Math.max(0, info.size - Number(match[2]));
    else { start = Number(match[1]); if (match[2]) end = Math.min(end, Number(match[2])); }
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= info.size) { res.writeHead(416, {'content-range':`bytes */${info.size}`}); return res.end(); }
    code = 206; headers['content-range'] = `bytes ${start}-${end}/${info.size}`;
  }
  headers['content-length'] = String(Math.max(0, end - start + 1));
  res.writeHead(code, headers);
  if (req.method === 'HEAD' || !info.size) return res.end();
  const stream = createReadStream(found.path, {start, end});
  res.once('close', () => stream.destroy());
  pipeline(stream, res, () => {});
}

function forwardedHeaders(req, token, gateway, upgrade = false) {
  const headers = {};
  for (const [key, value] of Object.entries(req.headers)) {
    if (HOP.has(key) || ['cookie','authorization','host','x-dafeiyu-plugin-token','forwarded'].includes(key) || key.startsWith('x-forwarded-')) continue;
    headers[key] = value;
  }
  headers.host = gateway.host;
  headers['x-dafeiyu-plugin-token'] = token;
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = 'websocket'; }
  return headers;
}

/** Only this fixed loopback upstream is reachable; no redirects, cookies, browser credentials or proxy env. */
export function createGatewayProxy({gatewayUrl, token, ensure = async () => {}, maxBodyBytes = 64 * 1024 * 1024}) {
  const gateway = new URL(gatewayUrl);
  if (gateway.protocol !== 'http:' || gateway.hostname !== '127.0.0.1' || gateway.username || gateway.password) throw new Error('Gateway must use IPv4 loopback HTTP');
  const sockets = new Set();
  return {
    async http(req, res, path) {
      if (!/^\/api(?:\/|$)/.test(path)) return json(res, 404, {detail:'Unknown gateway route'});
      const length = Number(req.headers['content-length'] ?? 0);
      if (!Number.isFinite(length) || length > maxBodyBytes) return json(res, 413, {detail:'Upload too large'});
      try { await ensure(); } catch (error) { return json(res, 503, runtimeFailure(error)); }
      if (req.destroyed || res.destroyed) return;
      const upstream = request({hostname:gateway.hostname, port:gateway.port, method:req.method, path, headers:forwardedHeaders(req, token, gateway), timeout:180_000});
      upstream.on('response', response => {
        const headers = {};
        for (const [key, value] of Object.entries(response.headers)) if (!HOP.has(key) && !['set-cookie','access-control-allow-origin','access-control-allow-credentials'].includes(key)) headers[key] = value;
        headers['cache-control'] = 'no-store';
        res.writeHead(response.statusCode, headers);
        pipeline(response, res, () => {});
      });
      upstream.once('timeout', () => upstream.destroy());
      upstream.on('error', () => { if (!res.headersSent) json(res, 502, {detail:'Local speech gateway unavailable'}); else res.destroy(); });
      req.once('aborted', () => upstream.destroy());
      res.once('close', () => upstream.destroy());
      let bytes = 0;
      req.on('data', chunk => { bytes += chunk.length; if (bytes > maxBodyBytes) { upstream.destroy(); if (!res.headersSent) json(res, 413, {detail:'Upload too large'}); } });
      req.pipe(upstream);
    },
    async upgrade(req, socket, head, path) {
      if (path.split('?')[0] !== '/ws/voice') return socket.destroy();
      try { await ensure(); } catch { socket.end('HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n'); return; }
      if (socket.destroyed) return;
      const upstream = request({hostname:gateway.hostname, port:gateway.port, path, headers:forwardedHeaders(req, token, gateway, true), timeout:30_000});
      upstream.on('upgrade', (response, target, upstreamHead) => {
        if (socket.destroyed) { target.destroy(); return; }
        // The HTTP negotiation deadline must not become an idle-session limit.
        upstream.setTimeout(0); target.setTimeout(0);
        sockets.add(socket); sockets.add(target);
        // An RST after the 101 is a socket error, not an HTTP request error.
        // DSH deliberately fails loud on unhandled errors, so both ends need owners.
        const fail = () => { socket.destroy(); target.destroy(); };
        socket.on('error', fail); target.on('error', fail);
        socket.once('close', () => { sockets.delete(socket); sockets.delete(target); target.destroy(); });
        target.once('close', () => socket.destroy());
        let handshake = 'HTTP/1.1 101 Switching Protocols\r\n';
        // This is a byte tunnel, not a WebSocket endpoint: preserve negotiated
        // extensions too. Dropping permessage-deflate makes Chromium reject the
        // first compressed bot-ready frame (RSV1), immediately closing with 1006.
        for (const [key,value] of Object.entries(response.headers)) if (['upgrade','connection','sec-websocket-accept','sec-websocket-protocol','sec-websocket-extensions'].includes(key)) handshake += `${key}: ${value}\r\n`;
        socket.write(`${handshake}\r\n`);
        if (upstreamHead.length) socket.write(upstreamHead);
        if (head.length) target.write(head);
        socket.pipe(target).pipe(socket);
      });
      upstream.once('response', response => { socket.end(`HTTP/1.1 ${response.statusCode} Gateway Rejected\r\nConnection: close\r\n\r\n`); response.resume(); });
      upstream.once('timeout', () => upstream.destroy());
      upstream.on('error', () => socket.destroy());
      socket.once('error', () => upstream.destroy());
      socket.once('close', () => upstream.destroy());
      upstream.end();
    },
    dispose() { for (const socket of sockets) socket.destroy(); sockets.clear(); },
  };
}
