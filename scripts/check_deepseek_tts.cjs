/* Real compiled browser/Pipecat/native WS adapter; provider and LLM are explicit
 * local fixtures, NOT evidence of paid DeepSeek TTS quality or latency. */
const assert = require('node:assert/strict'), fs = require('node:fs')
const { chromium } = require('../qa/node_modules/playwright')
const base = 'http://127.0.0.1:8875', provider = 'http://127.0.0.1:8874'
const output = 'E:/Dafeiyu/verification/deepseek-tts'
const report = { method: 'Real Edge + compiled UI + Pipecat + native WebSocket protocol; synthetic local PCM and controlled local LLM, no microphone or paid API', cases: [] }
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function wait(fn, label, timeout = 30000) {
  const end = Date.now() + timeout
  while (Date.now() < end) { if (await fn()) return; await delay(50) }
  throw Error(label)
}
async function api(path, init) {
  const r = await fetch(base + path, init); assert(r.ok, path + ': ' + r.status); return r.json()
}
async function records() { return (await fetch(provider + '/test/requests')).json() }
async function outcome(value) {
  const r = await fetch(provider + '/test/tts-outcome', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ outcome: value }) }); assert(r.ok)
}
function wire(payload) {
  const b = Buffer.from(payload), i = b.indexOf('{"label"')
  if (i >= 0) try { return JSON.parse(b.subarray(i).toString('utf8')) } catch {}
}
;(async () => {
  fs.mkdirSync(output, { recursive: true })
  const initial = await api('/api/settings')
  assert.equal(initial.tts_api_provider, 'deepseek')
  assert.equal(initial.tts_api_base_url, provider + '/v1', 'refuse production gateway')
  assert.equal(initial.llm_base_url, provider + '/v1', 'refuse real model calls')
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
  await page.addInitScript(() => {
    window.__tts = { micCalls: 0, consumed: 0 }
    navigator.mediaDevices.getUserMedia = async () => { window.__tts.micCalls++; throw Error('Microphone deliberately disabled') }
    const Worklet = window.AudioWorkletNode
    window.AudioWorkletNode = class extends Worklet {
      constructor(...args) { super(...args); this.port.addEventListener('message', e => { if (e.data?.event === 'consumed') window.__tts.consumed += e.data.samples || 0 }) }
    }
  })
  const errors = [], sent = [], received = [], pages = []
  let session, audioFrames = 0
  page.on('pageerror', e => pages.push(e.message))
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') session = (await r.json()).id })
  page.on('websocket', ws => {
    ws.on('framereceived', ({ payload }) => { if (Buffer.from(payload)[0] === 18) audioFrames++; const e = wire(payload); if (e) { received.push(e); if (e.type === 'error') errors.push(e) } })
    ws.on('framesent', ({ payload }) => { const e = wire(payload); if (e) sent.push(e) })
  })
  const ready = () => page.waitForFunction(() => document.querySelector('.mic-btn')?.disabled === false, null, { timeout: 30000 })
  const settings = () => page.getByRole('button', { name: '设置', exact: true }).click()
  const save = async () => { await page.getByRole('button', { name: '保存设置', exact: true }).click(); await page.locator('.drawer').waitFor({ state: 'hidden' }); await ready() }
  const send = async text => { await page.getByPlaceholder('说点什么，或开启语音...').fill(text); await page.getByRole('button', { name: '发送', exact: true }).click() }
  const snapshot = async () => ({ frames: audioFrames, sent: sent.length, received: received.length, errors: errors.length, consumed: await page.evaluate(() => window.__tts.consumed), calls: (await records()).filter(r => r.type === 'deepseek_tts_fixture').length })
  const history = () => api(`/api/sessions/${session}/messages`)
  const check = async (name, fn) => {
    const result = await fn(); report.cases.push({ name, status: 'passed', detail: result }); console.log('PASS', name)
    fs.writeFileSync(output + '/browser.json', JSON.stringify(report, null, 2))
  }
  try {
    await page.goto(base); await ready()
    await check('official voices, no fake model/speed controls, native settings persist', async () => {
      await settings()
      await page.getByLabel('DeepSeek 音色', { exact: true }).waitFor()
      const voices = await page.getByLabel('DeepSeek 音色', { exact: true }).locator('option').evaluateAll(xs => xs.map(x => x.value))
      assert.deepEqual(voices, ['stella', 'tide'])
      assert.equal(await page.getByLabel('TTS 模型', { exact: true }).count(), 0)
      assert.equal(await page.getByLabel('API 语速（0.25–4）', { exact: true }).count(), 0)
      await page.getByLabel('DeepSeek 音色', { exact: true }).selectOption('tide')
      await page.getByRole('checkbox', { name: '朗读前过滤 Markdown', exact: true }).uncheck()
      await save(); await page.reload(); await ready()
      const saved = await api('/api/settings')
      assert.equal(saved.tts_api_voice, 'tide'); assert.equal(saved.tts_api_filter_markdown, false)
      assert.equal(saved.tts_api_key, undefined)
      return { voices, savedVoice: saved.tts_api_voice }
    })
    await check('native WS -> PCM worklet consumption -> playback ACK -> confirmed history', async () => {
      const before = await snapshot()
      await send('测试原生 TTS 协议')
      await wait(() => sent.slice(before.sent).some(e => e.data?.t === 'voice.playback' && e.data?.d?.completed), 'no completed playback ACK')
      await wait(async () => (await history()).some(m => m.role === 'assistant' && m.content), 'no confirmed history')
      const after = await snapshot(), calls = (await records()).filter(r => r.type === 'deepseek_tts_fixture').slice(before.calls)
      assert(after.frames > before.frames && after.consumed > before.consumed)
      assert.equal(after.errors, before.errors)
      assert(calls.length > 0 && calls.every(c => c.voice === 'tide' && c.filter_markdown === 'false' && c.closed))
      return { consumedSamples: after.consumed - before.consumed, wireCalls: calls.length, audioQuality: 'synthetic fixture, not evaluated' }
    })
    await check('manual interruption cancels upstream and does not reconnect or replay', async () => {
      await outcome('slow')
      const before = await snapshot()
      await send('测试中途停止')
      await wait(() => audioFrames > before.frames, 'no initial PCM')
      await page.getByRole('button', { name: '停止', exact: true }).click()
      await wait(async () => (await records()).filter(r => r.type === 'deepseek_tts_fixture').slice(before.calls).every(r => r.closed), 'upstream not closed')
      await delay(600)
      const calls = (await records()).filter(r => r.type === 'deepseek_tts_fixture').slice(before.calls)
      assert.equal(calls.length, 1); assert.equal(errors.length, before.errors)
      return { closed: calls[0].closed, noRetry: true }
    })
    await check('provider content-filter error reaches frontend without private body or retry', async () => {
      await outcome('content_filter')
      const before = await snapshot()
      await send('测试服务拒绝')
      await wait(() => errors.length > before.errors, 'no surfaced provider error')
      const messages = JSON.stringify(errors.slice(before.errors))
      assert(messages.includes('内容审核')); assert(!messages.includes('provider-private-body'))
      await delay(500)
      assert.equal((await records()).filter(r => r.type === 'deepseek_tts_fixture').length - before.calls, 1)
      assert.equal(audioFrames, before.frames)
      return { sanitized: true, noRetry: true }
    })
    assert.equal(await page.evaluate(() => window.__tts.micCalls), 0)
    assert.deepEqual(pages, [])
    await page.screenshot({ path: output + '/browser.png' })
  } catch (e) {
    report.failure = String(e); await page.screenshot({ path: output + '/failure.png' }).catch(() => {}); throw e
  } finally {
    fs.writeFileSync(output + '/browser.json', JSON.stringify(report, null, 2)); await browser.close()
  }
})().catch(e => { console.error(e.message); process.exitCode = 1 })
