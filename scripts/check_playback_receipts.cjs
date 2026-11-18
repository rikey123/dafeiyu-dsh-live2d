/* Real official player/worklet receipt acceptance against isolated QA only.
 * No microphone, production settings, user sessions or cloud inference.
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8875'
const out = path.resolve(__dirname, '../artifacts/playback-receipts')
const shortReply = '好的，我们换一个问题。你想聊些什么？'
const longReply = '你好，我是大肥鱼，很高兴和你聊天。我们可以慢慢聊今天发生的事情。你可以在我说话的时候随时插话。简单的附和不会让我重新开始回答。如果你想换个话题，直接告诉我就好。我会停下来认真听你的问题。'
function event(payload) {
  const bytes = Buffer.from(payload), start = bytes.indexOf(Buffer.from('{"label"'))
  if (start < 0) return undefined
  try { return JSON.parse(bytes.subarray(start).toString('utf8')) } catch { return undefined }
}
;(async () => {
  assert(new URL(base).port !== '8765', 'Use isolated gateway with controlled model')
  fs.mkdirSync(out, { recursive: true })
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.addInitScript(() => {
    window.__consumed = []; window.__micCalls = 0
    const Native = window.AudioWorkletNode
    window.AudioWorkletNode = class extends Native {
      constructor(...args) {
        super(...args)
        if (args[1] === 'stream_processor') this.port.addEventListener('message', e => {
          if (e.data?.event === 'consumed') window.__consumed.push({ ...e.data, at: performance.now() })
        })
      }
    }
    navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('No microphone in playback acceptance') }
  })
  const page = await context.newPage(), received = [], sent = [], errors = [], sessions = new Set(), turns = []
  let session
  page.on('pageerror', e => errors.push(e.message))
  page.on('response', async response => {
    if (response.url().endsWith('/api/sessions') && response.request().method() === 'POST') {
      session = (await response.json()).id; sessions.add(session)
    }
  })
  page.on('websocket', ws => {
    ws.on('framereceived', frame => { const value = event(frame.payload); if (value) received.push({ ...value, at: Date.now() }) })
    ws.on('framesent', frame => { const value = event(frame.payload); if (value) sent.push({ ...value, at: Date.now() }) })
  })
  const wait = async (predicate, message, timeout = 90000) => {
    const deadline = Date.now() + timeout
    while (!await predicate()) {
      if (Date.now() > deadline) throw Error(message)
      await page.waitForTimeout(50)
    }
  }
  const history = async () => (await fetch(base + '/api/sessions/' + session + '/messages', { signal: AbortSignal.timeout(10000) })).json()
  try {
    await page.goto(base, { waitUntil: 'networkidle' })
    await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
    for (const text of ['换一个问题。', '请继续详细介绍。']) {
      const from = received.length, sentFrom = sent.length, start = Date.now()
      const before = (await history()).filter(x => x.role === 'assistant').length
      await page.getByPlaceholder('说点什么，或开启语音...').fill(text)
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await wait(() => received.slice(from).some(e => e.type === 'server-message' && e.data?.type === 'voice.playback.boundary'), 'No output boundary')
      const expected = text.includes('换') ? shortReply : longReply
      await wait(async () => { const assistants = (await history()).filter(x => x.role === 'assistant'); return assistants.length === before + 1 && assistants.at(-1).content === expected }, 'Actual player consumption never persisted the complete confirmed reply')
      const boundaries = received.slice(from).filter(e => e.data?.type === 'voice.playback.boundary').map(e => e.data)
      const receipts = sent.slice(sentFrom).filter(e => e.type === 'client-message' && e.data?.t === 'voice.playback')
      assert.equal(receipts.length, boundaries.length, 'Must ACK once per native audio context')
      const contexts = []
      for (const boundary of boundaries) {
        const consumed = await page.evaluate(epoch => window.__consumed.filter(x => x.epoch === epoch).reduce((n, x) => n + x.samples, 0), boundary.epoch)
        assert.equal(consumed, boundary.samples, 'Browser must consume exactly the context samples including its final partial quantum')
        const matches = receipts.filter(e => e.data.d.epoch === boundary.epoch)
        assert.equal(matches.length, 1)
        assert.equal(matches[0].data.d.consumed_samples, boundary.samples)
        assert(matches[0].at >= start)
        contexts.push({ epoch: boundary.epoch, samples: boundary.samples, consumed, text: boundary.text ?? null })
      }
      turns.push({ text, contexts, receipt_count: receipts.length, milliseconds_to_receipt: receipts.at(-1).at - start, history_confirmed: true })
      await page.waitForTimeout(500)
    }
    // Interrupt a long third turn and immediately ask a new question. Its
    // earlier queued audio/consumption callback must never ACK the old epoch.
    const before = (await history()).filter(x => x.role === 'assistant').length
    const from = received.length, sentFrom = sent.length
    await page.getByPlaceholder('说点什么，或开启语音...').fill('再次详细介绍。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await wait(() => received.slice(from).some(e => e.data?.type === 'voice.playback.start'), 'No interruptible start')
    const interruptedEpoch = received.slice(from).find(e => e.data?.type === 'voice.playback.start').data.epoch
    await page.waitForTimeout(800)
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.waitForTimeout(500)
    assert.equal((await history()).filter(x => x.role === 'assistant').length, before, 'Interrupted unconfirmed output persisted')
    await page.getByPlaceholder('说点什么，或开启语音...').fill('换一个问题。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await wait(async () => { const assistants = (await history()).filter(x => x.role === 'assistant'); return assistants.length === before + 1 && assistants.at(-1).content === shortReply }, 'Next turn failed after cancellation')
    assert(!sent.slice(sentFrom).some(e => e.type === 'client-message' && e.data?.t === 'voice.playback' && e.data?.d?.epoch === interruptedEpoch), 'Interrupted epoch received completion ACK')
    const prefixFrom = received.length, prefixSentFrom = sent.length
    const prefixBefore = (await history()).filter(x => x.role === 'assistant').length
    await page.getByPlaceholder('说点什么，或开启语音...').fill('验证已播放部分，请继续介绍。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await wait(() => sent.slice(prefixSentFrom).filter(e => e.type === 'client-message' && e.data?.t === 'voice.playback').length >= 2, 'No two completed native segments')
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.waitForTimeout(700)
    const confirmedEpochs = new Set(sent.slice(prefixSentFrom).filter(e => e.type === 'client-message' && e.data?.t === 'voice.playback').map(e => e.data.d.epoch))
    const prefixBoundaries = received.slice(prefixFrom).filter(e => e.data?.type === 'voice.playback.boundary').map(e => e.data)
    const expectedPrefix = prefixBoundaries.filter(b => confirmedEpochs.has(b.epoch)).map(b => b.text).join('')
    const prefixHistory = (await history()).filter(x => x.role === 'assistant')
    assert.equal(prefixHistory.length, prefixBefore + 1)
    assert(expectedPrefix && expectedPrefix.length < longReply.length, 'Expected a strict heard prefix')
    assert.equal(prefixHistory.at(-1).content, expectedPrefix, 'Only contiguous completed segments may enter interrupted history')
    await page.getByPlaceholder('说点什么，或开启语音...').fill('换一个问题。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await wait(async () => { const assistants = (await history()).filter(x => x.role === 'assistant'); return assistants.length === prefixBefore + 2 && assistants.at(-1).content === shortReply }, 'Next reply failed after preserving heard prefix')
    assert.equal(await page.evaluate(() => window.__micCalls), 0)
    assert.deepEqual(errors, [])
    const report = { passed: true, turns, interrupted_epoch: interruptedEpoch, interruption_did_not_persist: true, next_turn_confirmed: true, heard_prefix: { text: expectedPrefix, confirmed_contexts: confirmedEpochs.size, persisted_once: true, next_turn_confirmed: true }, errors, limitation: 'Actual headless Edge official worklet consumption and isolated database, controlled LLM, CPU TTS. Native TTS context confirmation; a context can contain multiple sentences. Not word alignment or a physical speaker/hearing test.' }
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report, null, 2))
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png') }).catch(() => {})
    fs.writeFileSync(path.join(out, 'failure.json'), JSON.stringify({ received, sent, errors, consumed: await page.evaluate(() => window.__consumed).catch(() => []) }, null, 2))
    throw error
  } finally {
    await browser.close()
    for (const id of sessions) await fetch(base + '/api/sessions/' + id, { method: 'DELETE' }).catch(() => {})
  }
})().catch(e => { console.error(e); process.exitCode = 1 })
