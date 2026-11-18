/* Real browser against the running local services; fake microphone only. */
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const modulePath = process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright'
const { chromium } = require(modulePath)
const root = path.resolve(__dirname, '..')
const out = path.join(root, 'artifacts', 'ui')
fs.mkdirSync(out, { recursive: true })

;(async () => {
  const audio = path.join(root, 'artifacts', 'live-smoke', 'microphone.wav')
  const args = ['--autoplay-policy=no-user-gesture-required', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
  if (fs.existsSync(audio)) args.push(`--use-file-for-fake-audio-capture=${audio}`)
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['microphone'] })
  const page = await context.newPage()
  const errors = [], failed = [], external = [], events = []
  let sessionId
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => { if (response.status() >= 400) failed.push({ url: response.url(), status: response.status() }) })
  page.on('request', request => { if (/^https?:/.test(request.url()) && !request.url().startsWith('http://127.0.0.1:8765')) external.push(request.url()) })
  page.on('websocket', ws => ws.on('framereceived', event => {
    try { const data = JSON.parse(String(event.payload)); if (data.type === 'session') sessionId = data.session_id; events.push({ ...data, audio: data.audio ? '[omitted]' : undefined }) } catch {}
  }))
  try {
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' })
    await page.getByText('本地服务已连接', { exact: true }).waitFor()
    await page.locator('.avatar-canvas canvas').waitFor()
    // Wait for the actual Cubism model, not only an empty canvas.
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
    await page.getByRole('button', { name: '设置', exact: true }).first().click()
    await page.locator('.service-status').waitFor()
    // Inspect diagnostics without writing the user's provider, key, voice or model.
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByRole('button', { name: '关闭提示' }).click().catch(() => {})
    const input = page.getByPlaceholder('说点什么，或开启语音...')
    await input.fill('你好，请用一句话欢迎我。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.waitForFunction(() => { const msgs = [...document.querySelectorAll('.message.assistant .message-text')]; return msgs.some(x => x.textContent.length > 4 && x.textContent !== '...') }, null, { timeout: 60000 })
    const playbackDeadline = Date.now() + 60000
    while (!events.some(x => x.type === 'response.done') || !events.some(x => x.type === 'state' && x.state === 'listening' && x.epoch === 1)) {
      if (Date.now() > playbackDeadline) throw new Error('Browser playback did not finish and acknowledge within 60s')
      await page.waitForTimeout(100)
    }
    const stored = await context.request.get(`http://127.0.0.1:8765/api/sessions/${sessionId}/messages`)
    assert((await stored.json()).some(x => x.role === 'assistant' && x.content.length > 0), 'browser playback must acknowledge and persist spoken reply')
    await page.screenshot({ path: path.join(out, 'desktop.png'), fullPage: true })
    if (fs.existsSync(audio)) {
      const before = events.length
      await page.getByRole('button', { name: '开启语音', exact: true }).click()
      await page.getByRole('button', { name: '正在聆听', exact: true }).waitFor({ timeout: 30000 })
      const deadline = Date.now() + 45000
      while (!events.slice(before).some(x => x.type === 'transcript') && Date.now() < deadline) await page.waitForTimeout(250)
      assert(events.slice(before).some(x => x.type === 'transcript'), 'Silero/AudioWorklet fake-mic input must reach real ASR')
      await page.getByRole('button', { name: '正在聆听', exact: true }).click()
    }
    await page.setViewportSize({ width: 390, height: 844 })
    await page.waitForTimeout(500)
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile horizontal overflow')
    await page.screenshot({ path: path.join(out, 'mobile.png'), fullPage: true })
    assert.deepEqual(errors, [], 'browser runtime errors')
    assert.deepEqual(failed, [], 'failed HTTP resources')
    assert.deepEqual(external, [], 'runtime must use local assets only')
    const result = { checked: ['real local Live2D', 'settings diagnostics (read only)', 'real LLM reply', 'real WAV playback acknowledgement', 'Silero fake-mic ASR', 'mobile layout'], errors, failed, external, events }
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(result, null, 2))
    console.log(JSON.stringify({ passed: true, directory: out, transcript: events.filter(x => x.type === 'transcript').map(x => x.text) }, null, 2))
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true }).catch(() => {})
    fs.writeFileSync(path.join(out, 'failure.json'), JSON.stringify({ message: String(error), errors, failed, external, events }, null, 2))
    throw error
  } finally {
    if (sessionId) await context.request.delete(`http://127.0.0.1:8765/api/sessions/${sessionId}`).catch(() => {})
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
