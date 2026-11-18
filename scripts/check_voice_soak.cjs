/* Sustained real browser/local CPU TTS regression with controlled local LLM.
 * Independent acceptance, not physical/human conversation or cloud inference.
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8875'
const minutes = Number(process.argv[2] || 30)
assert(Number.isFinite(minutes) && minutes >= 1 && minutes <= 60)
assert(new URL(base).port !== '8765', 'Use isolated controlled-model gateway')
const target = path.resolve(__dirname, '../artifacts/voice-soak')
const quantile = (values, q) => values.sort((a, b) => a - b)[Math.max(0, Math.ceil(q * values.length) - 1)]
;(async () => {
  fs.mkdirSync(target, { recursive: true })
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } }), page = await context.newPage()
  const sessions = new Set(), errors = [], turns = []
  let session
  await context.addInitScript(() => {
    window.__contexts = []; window.__micCalls = 0; window.__queue = null
    const Worklet = window.AudioWorkletNode
    window.AudioWorkletNode = class extends Worklet { constructor(...args) { super(...args); if (args[1] === 'stream_processor') this.port.addEventListener('message', e => { if (e.data?.event === 'telemetry') window.__queue = e.data }) } }
    const Native = window.AudioContext
    window.AudioContext = class extends Native { constructor(...args) { super(...args); window.__contexts.push(this) } }
    navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('No microphone in automated soak') }
  })
  page.on('pageerror', e => errors.push(e.message))
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') { session = (await r.json()).id; sessions.add(session) } })
  const wait = async (predicate, message) => {
    const deadline = Date.now() + 90000
    while (!await predicate()) { if (Date.now() > deadline) throw Error(message); await page.waitForTimeout(100) }
  }
  const history = async () => (await fetch(base + '/api/sessions/' + session + '/messages', { signal: AbortSignal.timeout(10000) })).json()
  const checkMouth = async () => {
    await page.getByRole('button', { name: '设置', exact: true }).first().click()
    await page.getByText(/口型：wLipSync 元音口型 · 本地中文声线/).waitFor({ timeout: 20000 })
    await page.getByRole('button', { name: '关闭', exact: true }).click()
  }
  try {
    await page.goto(base, { waitUntil: 'networkidle' })
    await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    await checkMouth()
    const start = Date.now()
    let expected = (await history()).filter(x => x.role === 'assistant').length
    while (Date.now() - start < minutes * 60000) {
      const at = Date.now(), index = turns.length
      const long = index % 9 === 8
      const expectedReply = long ? '你好，我是大肥鱼，很高兴和你聊天。我们可以慢慢聊今天发生的事情。你可以在我说话的时候随时插话。简单的附和不会让我重新开始回答。如果你想换个话题，直接告诉我就好。我会停下来认真听你的问题。' : '好的，我们换一个问题。你想聊些什么？'
      await page.getByPlaceholder('说点什么，或开启语音...').fill(long ? '请继续详细介绍。' : '换一个问题。')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      const cancelled = index % 7 === 6
      if (cancelled) {
        await page.getByRole('button', { name: '停止', exact: true }).waitFor({ timeout: 15000 })
        await page.waitForTimeout(700)
        await page.getByRole('button', { name: '停止', exact: true }).click()
        await page.waitForTimeout(600)
        assert.equal((await history()).filter(x => x.role === 'assistant').length, expected)
      } else {
        expected++
        await wait(async () => { const assistants = (await history()).filter(x => x.role === 'assistant'); return assistants.length === expected && assistants.at(-1).content === expectedReply }, 'Complete playback/history failed during sustained session')
      }
      const diagnostics = await page.evaluate(() => ({ audio_contexts: window.__contexts.length, live_contexts: window.__contexts.filter(x => x.state !== 'closed').length, mic_calls: window.__micCalls, queue: window.__queue, js_heap_bytes: performance.memory?.usedJSHeapSize ?? null }))
      assert(diagnostics.live_contexts <= 1, 'AudioContext leak')
      assert(diagnostics.queue, 'No official worklet telemetry')
      assert(diagnostics.queue.maxQueued <= 240000, 'Output queue exceeded cap')
      assert.equal(diagnostics.queue.overflows, 0, 'Unexpected output overflow')
      assert.equal(diagnostics.mic_calls, 0)
      assert.deepEqual(errors, [])
      turns.push({ index, long_reply: long, cancelled, milliseconds_to_confirm_or_stop: Date.now() - at, ...diagnostics })
      if (index && index % 20 === 0) {
        await page.reload({ waitUntil: 'networkidle' })
        await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
        await checkMouth()
        expected = (await history()).filter(x => x.role === 'assistant').length
      }
      fs.writeFileSync(path.join(target, 'progress.json'), JSON.stringify({ duration_seconds: (Date.now() - start) / 1000, turns, errors }, null, 2))
      if (index % 10 === 0) console.log(JSON.stringify({ turn: index, elapsed_seconds: Math.round((Date.now() - start) / 1000), ...diagnostics }))
      await page.waitForTimeout(Math.max(0, 8000 - (Date.now() - at)))
    }
    const metrics = await (await fetch(base + '/api/voice/metrics/' + session)).json()
    const latencies = turns.filter(x => !x.cancelled).map(x => x.milliseconds_to_confirm_or_stop)
    const report = { passed: true, requested_minutes: minutes, duration_seconds: (Date.now() - start) / 1000, turns, completed_turns: latencies.length, cancelled_turns: turns.filter(x => x.cancelled).length, latency_ms: { n: latencies.length, p50: quantile([...latencies], .5), p95: quantile([...latencies], .95), definition: 'Click to browser consumption ACK and database read; no physical speaker latency.' }, metrics, errors, limitations: 'Controlled local LLM, real local CPU TTS/official Edge player and cancellation, no physical microphone/AEC/human conversation. JS heap GC is nondeterministic; audio-context count is the resource gate. Reloads re-establish connection and metrics reset.' }
    fs.writeFileSync(path.join(target, 'results.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify({ passed: true, seconds: report.duration_seconds, turns: turns.length, latency_ms: report.latency_ms }))
  } catch (error) {
    fs.writeFileSync(path.join(target, 'failure.json'), JSON.stringify({ error: String(error), turns, errors }, null, 2))
    await page.screenshot({ path: path.join(target, 'failure.png') }).catch(() => {})
    throw error
  } finally {
    await browser.close()
    for (const id of sessions) await fetch(base + '/api/sessions/' + id, { method: 'DELETE', signal: AbortSignal.timeout(10000) }).catch(() => {})
  }
})().catch(e => { console.error(e); process.exitCode = 1 })
