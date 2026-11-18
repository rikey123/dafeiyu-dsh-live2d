/* Real CosyVoice3, official player and DeepSeek-chan; no microphone. */
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const base = process.env.VOICE_TEST_URL
if (!base || !['127.0.0.1', 'localhost', '[::1]', '::1'].includes(new URL(base).hostname)) throw Error('VOICE_TEST_URL must point to an isolated loopback gateway')
const expected = process.env.VOICE_EXPECTED_REPLY
if (!expected) throw Error('VOICE_EXPECTED_REPLY is required')
const decode = payload => { const b = Buffer.from(payload), i = b.indexOf(Buffer.from('{"label"')); try { return i < 0 ? undefined : JSON.parse(b.subarray(i).toString()) } catch {} }
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--mute-audio'] })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.addInitScript(() => {
    window.__consumed = []; window.__epoch = ''; window.__clock = {}; window.__micCalls = 0
    const Native = window.AudioWorkletNode
    window.AudioWorkletNode = class extends Native { constructor(...args) { super(...args); if (args[1] === 'stream_processor') this.port.addEventListener('message', e => { if (e.data?.event === 'consumed') { window.__epoch = e.data.epoch; window.__clock[e.data.epoch] = (window.__clock[e.data.epoch] || 0) + e.data.samples; window.__consumed.push({ ...e.data, at: performance.now() }) } }) } }
    navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('QA must not access microphone') }
  })
  const page = await context.newPage(), received = [], sent = [], errors = [], sessions = new Set(); let session
  page.on('pageerror', e => errors.push(e.message))
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') { session = (await r.json()).id; sessions.add(session) } })
  page.on('websocket', ws => { ws.on('framereceived', f => { const v = decode(f.payload); if (v) received.push(v) }); ws.on('framesent', f => { const v = decode(f.payload); if (v) sent.push(v) }) })
  const wait = async (fn, message, timeout = 600000) => { const end = Date.now() + timeout; while (!await fn()) { if (Date.now() > end) throw Error(message); await page.waitForTimeout(100) } }
  const messages = (from, type) => received.slice(from).filter(x => x.data?.type === type).map(x => x.data)
  const send = async text => { await page.getByPlaceholder('说点什么，或开启语音...').fill(text); await page.getByRole('button', { name: '发送', exact: true }).click() }
  const status = async () => (await (await fetch(`${base}/api/status`)).json()).optional?.cosyvoice
  const history = async () => (await (await fetch(`${base}/api/sessions/${session}/messages`)).json())
  try {
    await page.goto(base, { waitUntil: 'networkidle' }); await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 600000 }); await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 600000 })
    let service = await status(); assert.equal(service?.model_version, '3'); assert.match(service?.model_name || '', /Fun-CosyVoice3-0\.5B/i)
    await page.evaluate(() => { window.__shapes = []; const p = window.PIXI.utils.EventEmitter.prototype, emit = p.emit; p.emit = function (...args) { const result = emit.apply(this, args); if (args[0] === 'beforeModelUpdate' && this.coreModel) window.__shapes.push({ at: performance.now(), epoch: window.__epoch, samples: window.__clock[window.__epoch] || 0, open: this.coreModel.getParameterValueById('ParamMouthOpenY'), form: this.coreModel.getParameterValueById('ParamMouthForm') }); return result } })
    const from = received.length, sentFrom = sent.length, question = '你好。'; await send(question)
    await wait(() => messages(from, 'voice.playback.start').length > 0, 'missing playback start')
    const start = messages(from, 'voice.playback.start')[0]; assert.equal(start.sample_rate, 24000)
    await wait(() => page.evaluate(epoch => window.__consumed.some(x => x.epoch === epoch), start.epoch), 'no worklet consumption')
    await wait(() => page.evaluate(epoch => window.__shapes.some(x => x.epoch === epoch && x.samples > 0 && (x.open > .02 || Math.abs(x.form) > .02)), start.epoch), 'mouth did not change after consumption')
    await wait(() => messages(from, 'voice.playback.boundary').some(x => x.epoch === start.epoch), 'missing playback boundary')
    const boundary = messages(from, 'voice.playback.boundary').find(x => x.epoch === start.epoch)
    await wait(() => sent.slice(sentFrom).some(x => x.data?.t === 'voice.playback' && x.data?.d?.epoch === start.epoch && x.data.d.consumed_samples === boundary.samples), 'missing exact playback ACK')
    await wait(async () => { const h = await history(), i = h.findLastIndex(x => x.role === 'user' && x.content === question); return i >= 0 && h[i + 1]?.role === 'assistant' && h[i + 1].content === expected }, 'database reply differs from expected full reply')
    const loadedService = await status(); assert.equal(loadedService?.ready, true); assert(loadedService.device && loadedService.precision)
    const cancelFrom = received.length, cancelSent = sent.length; await send('请再说一句。')
    await page.getByRole('button', { name: '停止', exact: true }).waitFor({ timeout: 600000 }); await page.getByRole('button', { name: '停止', exact: true }).click()
    await wait(() => sent.slice(cancelSent).some(x => x.data?.t === 'voice.stop'), 'stop message missing')
    await page.getByText('等待开始', { exact: true }).waitFor({ timeout: 600000 })
    await wait(async () => !(await status())?.busy, 'CosyVoice3 remained busy after stop')
    const count = await page.evaluate(() => window.__consumed.length); await page.waitForTimeout(3000)
    assert.equal(await page.evaluate(() => window.__consumed.length), count, 'audio was consumed after stop')
    assert((await page.evaluate(() => window.__shapes.slice(-5))).every(x => x.open < .03), 'mouth did not close after stop')
    assert.equal(await page.evaluate(() => window.__micCalls), 0); assert.deepEqual(errors, [])
    service = await status()
    console.log(JSON.stringify({ passed: true, model: service.model_name, model_version: service.model_version, device: loadedService.device, precision: loadedService.precision, epoch: start.epoch, cancelled_epochs: messages(cancelFrom, 'voice.playback.start').map(x => x.epoch), audio_sha256: boundary.audio_sha256 || start.audio_sha256 || null, samples: boundary.samples, expected_reply: expected, no_late_consumption: true }, null, 2))
  } finally { await browser.close(); for (const id of sessions) await fetch(`${base}/api/sessions/${id}`, { method: 'DELETE' }).catch(() => {}) }
})().catch(error => { console.error(error); process.exitCode = 1 })
