import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { Readable } from 'node:stream'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { join, resolve, dirname, basename } from 'node:path'
import { tmpdir } from 'node:os'
import { downloadFile, ensureUv } from '../src/install-download.mjs'

const data = Buffer.from('fixture payload')
const sha256 = createHash('sha256').update(data).digest('hex')
async function fixture(t) {
  const parent = resolve(process.env.DAFEIYU_TEST_TMP || tmpdir())
  await mkdir(parent, { recursive: true })
  const dir = await mkdtemp(join(parent, 'dafeiyu-download-test-'))
  t.after(async () => {
    if (dirname(dir) !== parent || !basename(dir).startsWith('dafeiyu-download-test-')) throw new Error('Unsafe test cleanup')
    await rm(dir, { recursive: true, force: true })
  })
  return join(dir, 'download')
}
function mock(responses) {
  let calls = 0
  const request = (_url, _options, callback) => {
    const req = new EventEmitter()
    req.setTimeout = () => req
    req.destroy = error => req.emit('error', error)
    req.end = () => queueMicrotask(() => {
      const next = responses[Math.min(calls++, responses.length - 1)]
      if (next.error) return req.emit('error', new Error(next.error))
      const response = Readable.from(next.body ?? data)
      response.statusCode = next.status ?? 200
      response.headers = next.headers ?? {}
      callback(response)
    })
    return req
  }
  return { request, calls: () => calls }
}
const opts = destination => ({ url: 'https://example.test/file?secret=value', destination, sha256, retries: 0 })

test('retries safely and caches verified files offline', async t => {
  const destination = await fixture(t), net = mock([{ error: 'secret URL' }, {}])
  const result = await downloadFile({ ...opts(destination), request: net.request, retries: 1 })
  assert.equal(result.cached, false); assert.equal(net.calls(), 2)
  assert.deepEqual(await readFile(destination), data)
  assert.equal((await downloadFile({ ...opts(destination), offline: true })).cached, true)
})
test('bad hash is rejected and existing file never overwritten', async t => {
  const destination = await fixture(t), net = mock([{ body: Buffer.from('bad') }])
  await assert.rejects(downloadFile({ ...opts(destination), request: net.request }), /SHA-256/)
  await writeFile(destination, 'existing')
  await assert.rejects(downloadFile({ ...opts(destination), request: net.request }), /already exists/)
  assert.equal(await readFile(destination, 'utf8'), 'existing')
  await assert.rejects(downloadFile({ ...opts(destination), offline: true }), /already exists/)
})
test('rejects unsafe URLs, redirect and oversized responses without leaking secrets', async t => {
  const destination = await fixture(t)
  for (const url of ['http://example.test', 'https://u:p@example.test/', 'https://example.test/#secret']) await assert.rejects(downloadFile({ ...opts(destination), url }), /URL/)
  await assert.rejects(downloadFile({ ...opts(destination), request: mock([{ status: 302, headers: { location: 'http://example.test/?secret=x' } }]).request }), e => !e.message.includes('secret'))
  await assert.rejects(downloadFile({ ...opts(destination), maxBytes: 2, request: mock([{}]).request }), /failed/)
  await assert.rejects(downloadFile({ ...opts(destination), request: mock([{ error: 'https://example.test/?secret=x' }]).request }), e => !e.message.includes('secret'))
})
test('offline missing file and cancellation fail', async t => {
  const destination = await fixture(t)
  await assert.rejects(downloadFile({ ...opts(destination), offline: true }), /offline/)
  const controller = new AbortController(); controller.abort()
  await assert.rejects(downloadFile({ ...opts(destination), signal: controller.signal }), { name: 'AbortError' })
  await assert.rejects(ensureUv({ homeDir: join(destination, 'uv-missing'), offline: true }), /offline/)
})

test('in-flight cancellation removes partial file and rejects', async t => {
  const destination = await fixture(t), controller = new AbortController()
  const request = (_url, _options, callback) => {
    const req = new EventEmitter(); req.setTimeout = () => req; req.end = () => {
      const stream = new Readable({ read() { this.push(Buffer.from('chunk')); controller.abort(); this.push(null) } })
      stream.statusCode = 200; stream.headers = {}; callback(stream)
    }; return req
  }
  await assert.rejects(downloadFile({ ...opts(destination), signal: controller.signal, request }), { name: 'AbortError' })
  await assert.rejects(readFile(destination), { code: 'ENOENT' })
})
test('rejects a directory as the destination', async t => {
  const destination = await fixture(t); await mkdir(destination)
  await assert.rejects(downloadFile({ ...opts(destination), offline: true }), /regular file/)
})

test('refuses unsafe destination and too many redirects', async t => {
  const destination = await fixture(t)
  await assert.rejects(downloadFile({ ...opts(destination + '/'), request: mock([{}]).request }), /destination/)
  const redirect = mock([{ status: 302, headers: { location: 'https://example.test/again' } }])
  await assert.rejects(downloadFile({ ...opts(destination), request: redirect.request, maxRedirects: 1 }), /failed/)
  assert.equal(redirect.calls(), 2)
})


test('header deadline destroys a stalled request', async t => {
  const destination = await fixture(t); let destroyed = false
  const request = () => {
    const req = new EventEmitter()
    req.setTimeout = () => req; req.end = () => {}
    req.destroy = error => { destroyed = true; req.emit('error', error) }
    return req
  }
  await assert.rejects(downloadFile({ ...opts(destination), request, timeoutMs: 20 }), /failed/)
  assert.equal(destroyed, true)
})
test('body inactivity destroys a stalled response', async t => {
  const destination = await fixture(t); let response
  const request = (_url, _options, callback) => {
    const req = new EventEmitter(); req.setTimeout = () => req
    req.end = () => { response = new Readable({ read() {} }); response.statusCode = 200; response.headers = {}; callback(response) }
    req.destroy = error => req.emit('error', error); return req
  }
  await assert.rejects(downloadFile({ ...opts(destination), request, timeoutMs: 20 }), /failed/)
  assert.equal(response.destroyed, true)
})
test('concurrent downloads reuse the winner without overwriting', async t => {
  const destination = await fixture(t), net = mock([{}])
  const results = await Promise.all(Array.from({ length: 8 }, () => downloadFile({ ...opts(destination), request: net.request })))
  assert.equal(results.filter(x => !x.cached).length, 1)
  assert.deepEqual(await readFile(destination), data)
})
