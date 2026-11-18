/* Real browser + local server handshake. No microphone, LLM turn or TTS request. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8765'

;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext()
  const checks = [], pageErrors = []
  let dropReady = false
  await context.addInitScript(() => {
    window.__connectionTest = { sockets: [], contexts: [], micCalls: 0 }
    const Socket = window.WebSocket, NativeContext = window.AudioContext
    window.WebSocket = class extends Socket {
      constructor(...args) { super(...args); window.__connectionTest.sockets.push(this) }
    }
    window.AudioContext = class extends NativeContext {
      constructor(...args) { super(...args); window.__connectionTest.contexts.push(this) }
    }
    navigator.mediaDevices.getUserMedia = async () => {
      window.__connectionTest.micCalls++
      throw new Error('Connection tests must not acquire a microphone')
    }
  })
  await context.routeWebSocket('**/ws/voice?*', socket => {
    const server = socket.connectToServer()
    server.onMessage(message => {
      if (!dropReady || !message.toString().includes('bot-ready')) socket.send(message)
    })
  })
  const ready = page => page.waitForFunction(() => document.querySelector('.mic-btn')?.disabled === false, null, { timeout: 30000 })
  const openCount = page => page.evaluate(() => window.__connectionTest.sockets.filter(socket => socket.readyState === WebSocket.OPEN).length)
  const newPage = async session => {
    const page = await context.newPage()
    page.on('pageerror', error => pageErrors.push(error.message))
    if (session) await page.route('**/api/sessions', async route => {
      if (route.request().method() === 'POST') await route.fulfill({ json: { id: session } })
      else await route.continue()
    })
    return page
  }
  try {
    const session = (await (await context.request.post(base + '/api/sessions')).json()).id
    const page = await newPage(session)
    const start = Date.now()
    await page.goto(base); await ready(page)
    checks.push({ case: 'initial handshake', elapsedMs: Date.now() - start })
    assert.equal(await openCount(page), 1)
    const duplicate = await newPage(session), rejectedAt = Date.now()
    await duplicate.goto(base)
    await duplicate.getByText(/语音连接失败：.*该会话已在另一个窗口使用/).waitFor({ timeout: 6000 })
    checks.push({ case: 'duplicate session reports original reason without waiting for timeout', elapsedMs: Date.now() - rejectedAt })
    const other = await newPage()
    await other.goto(base); await ready(other)
    checks.push({ case: 'another session connects while duplicate peer is rejected', passed: true })
    await other.close(); await duplicate.close()
    await page.reload(); await ready(page)
    assert.equal(await openCount(page), 1)
    for (const profile of ['airi', 'local-vits', 'airi']) {
      await page.getByRole('button', { name: '设置', exact: true }).click()
      await page.getByRole('combobox', { name: '口型声线', exact: true }).selectOption(profile)
      await ready(page)
      await page.getByRole('button', { name: '关闭', exact: true }).click()
      assert.equal(await openCount(page), 1)
    }
    checks.push({ case: 'reload and three session reconnects retain one live socket', passed: true })
    const interruptMs = await page.evaluate(async () => {
      const player = new window.WavStreamPlayer({ sampleRate: 24000 })
      await player.connect(); await player.context.suspend()
      player.add16BitPCM(new Int16Array(2400))
      const start = performance.now()
      await player.interrupt()
      const elapsed = performance.now() - start
      await player.context.close()
      return elapsed
    })
    assert(interruptMs < 1000)
    checks.push({ case: 'suspended official player interrupt is bounded', elapsedMs: interruptMs })
    const noReceiptMs = await page.evaluate(async () => {
      const player = new window.WavStreamPlayer({ sampleRate: 24000 })
      player.context = { state: 'running' }
      player.stream = { port: { postMessage() {} }, disconnect() {} }
      const start = performance.now()
      const result = await player.interrupt()
      if (result !== null || player.stream !== null || player.offsetRequests.size) throw new Error('Unanswered receipt must be discarded without fabricated playback confirmation')
      return performance.now() - start
    })
    assert(noReceiptMs < 1500)
    checks.push({ case: 'missing worklet receipt times out without confirming playback', elapsedMs: noReceiptMs })
    dropReady = true
    const stalled = await newPage(), timeoutStart = Date.now()
    await stalled.goto(base)
    await stalled.getByText(/语音连接失败：.*语音连接超时：等待语音服务就绪/).waitFor({ timeout: 26000 })
    await stalled.waitForFunction(() => window.__connectionTest.sockets[0]?.readyState === WebSocket.CLOSED)
    dropReady = false
    await ready(stalled)
    assert.equal(await openCount(stalled), 1)
    checks.push({ case: 'dropped bot-ready closes timed-out socket and reconnects successfully', elapsedMs: Date.now() - timeoutStart })
    for (const target of [page, stalled]) {
      assert.equal(await target.evaluate(() => window.__connectionTest.micCalls), 0)
      const contexts = await target.evaluate(() => window.__connectionTest.contexts.map(context => ({ state: context.state, sampleRate: context.sampleRate })))
      assert(contexts.filter(context => context.state !== 'closed').length <= 1, `Audio contexts leaked: ${JSON.stringify(contexts)}`)
    }
    assert.deepEqual(pageErrors, [])
    const report = { checks, pageErrors, microphoneOpened: false, llmOrTtsRequested: false }
    if (process.env.VOICE_CONNECTION_OUTPUT) fs.writeFileSync(process.env.VOICE_CONNECTION_OUTPUT, JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report, null, 2))
  } finally { await context.close(); await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
