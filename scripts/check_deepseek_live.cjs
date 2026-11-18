/* One real DeepSeek turn through the primary app. No secret output/config edit.
 * Creates and deletes only its own QA session; no microphone or real user data.
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = 'http://127.0.0.1:8765', out = path.resolve(__dirname, '../artifacts/deepseek-live')
;(async () => {
  const settings = await (await fetch(base + '/api/settings')).json()
  assert(settings.api_key_set && settings.llm_base_url === 'https://api.deepseek.com/v1' && settings.llm_model === 'deepseek-chat', 'Requires configured official DeepSeek; no credentials are modified')
  const voice_policy = (await (await fetch(base + '/api/status')).json()).voice_policy
  if (process.env.REQUIRE_GPU === '1') assert.equal(voice_policy.requested, 'gpu', 'GPU verification requires explicit GPU mode')
  fs.mkdirSync(out, { recursive: true })
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } }), page = await context.newPage()
  const sessions = new Set(), errors = [], events = [], sent = []; let session
  await context.addInitScript(() => {
    window.__pcm = []; window.__mouth = []; window.__micCalls = 0
    const Native = window.AudioWorkletNode
    window.AudioWorkletNode = class extends Native { constructor(...args) { super(...args); this.port.addEventListener('message', e => { if (args[1] === 'stream_processor') window.__pcm.push({ at: performance.now(), type: e.data?.event }) }) } }
    navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('No microphone in real cloud text test') }
  })
  page.on('pageerror', e => errors.push(e.message))
  const decode = (frame, target) => {
    const payload = Buffer.from(frame.payload), start = payload.indexOf(Buffer.from('{"label"'))
    if (start >= 0) { try { target.push(JSON.parse(payload.subarray(start).toString('utf8'))) } catch {} }
  }
  page.on('websocket', socket => { socket.on('framereceived', frame => decode(frame, events)); socket.on('framesent', frame => decode(frame, sent)) })
  page.on('response', async response => { if (response.url().endsWith('/api/sessions') && response.request().method() === 'POST') { session = (await response.json()).id; sessions.add(session) } })
  try {
    await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 90000 })
    await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
    await page.evaluate(() => {
      const proto = window.PIXI.utils.EventEmitter.prototype, original = proto.emit
      proto.emit = function(...args) {
        const value = original.apply(this, args)
        if (args[0] === 'beforeModelUpdate' && this.coreModel) window.__mouth.push({ at: performance.now(), open: this.coreModel.getParameterValueById('ParamMouthOpenY'), form: this.coreModel.getParameterValueById('ParamMouthForm') })
        return value
      }
    })
    await page.getByPlaceholder('说点什么，或开启语音...').fill('请只说一句简短的问候，不超过十五个字。')
    const start = await page.evaluate(() => performance.now())
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.waitForFunction(() => window.__mouth.some(x => x.open > .05), null, { timeout: 90000 })
    const deadline = Date.now() + 90000
    let playbackContexts = []
    while (true) {
      playbackContexts = events.filter(e => e.type === 'server-message' && e.data?.type === 'voice.playback.boundary').map(e => e.data)
      const starts = events.filter(e => e.type === 'server-message' && e.data?.type === 'voice.playback.start')
      const acceptedIds = new Set(events.filter(e => e.type === 'server-response' && e.data?.t === 'voice.playback' && e.data?.d?.accepted === true).map(e => e.id))
      const accepted = new Set(sent.filter(e => acceptedIds.has(e.id) && e.data?.t === 'voice.playback').map(e => e.data.d?.epoch))
      if (events.some(e => e.type === 'bot-llm-stopped') && playbackContexts.length > 0 && starts.length === playbackContexts.length && playbackContexts.every(c => accepted.has(c.epoch))) break
      if (Date.now() > deadline) throw Error('Complete multi-context cloud reply was not playback confirmed')
      await page.waitForTimeout(100)
    }
    const messages = await (await fetch(base + '/api/sessions/' + session + '/messages')).json()
    const assistant = messages.filter(x => x.role === 'assistant').map(x => x.content).join('')
    assert(assistant.trim(), 'No real assistant reply persisted')
    assert.equal(assistant, playbackContexts.map(c => c.text || '').join(''), 'Cloud history differs from all consumed contexts')
    const observed = await page.evaluate(start => ({ first_mouth_ms: window.__mouth.find(x => x.at >= start && x.open > .05)?.at - start, max_open: Math.max(...window.__mouth.map(x => x.open)), max_form: Math.max(...window.__mouth.map(x => Math.abs(x.form))), player_worklet_events: window.__pcm.length, mic_calls: window.__micCalls }), start)
    assert(observed.mic_calls === 0 && observed.max_open > .05 && observed.player_worklet_events > 0)
    assert.deepEqual(errors, [])
    const cosyvoice = await fetch('http://127.0.0.1:8770/health').then(response => response.json()).catch(() => null)
    if (process.env.REQUIRE_GPU === '1') assert(cosyvoice?.loaded && cosyvoice.device === 'cuda', 'Requires a loaded CUDA speech worker after browser playback')
    const result = { passed: true, model: 'deepseek-chat', assistant, observed, playback_contexts: playbackContexts.length, all_contexts_confirmed: true, voice_policy, cosyvoice, errors, limitation: 'One real cloud text turn, local TTS and actual browser/model; no microphone ASR or physical sound measurement. First mouth includes click/network/model/TTS/render and is not speaker latency.' }
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(result, null, 2))
    await page.screenshot({ path: path.join(out, 'reply.png') })
    console.log(JSON.stringify(result, null, 2))
  } finally {
    await browser.close()
    for (const id of sessions) await fetch(base + '/api/sessions/' + id, { method: 'DELETE' }).catch(() => {})
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
