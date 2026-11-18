/* Actual supplied Cubism model. Controlled WAV replay tests the avatar/audio bridge;
   it is not a cloud-model conversation test and uses no physical microphone. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const root = path.resolve(__dirname, '..'), out = path.join(root, 'artifacts/deepseek-avatar')
fs.mkdirSync(out, { recursive: true })
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.addInitScript(() => {
    const NativeAudio = window.AudioContext
    window.AudioContext = class extends NativeAudio { constructor(...args) { super(...args); window.__avatarAudio = this } }
    const Native = window.WebSocket
    window.WebSocket = class extends Native { constructor(...args) { super(...args); window.__avatarTestSocket = this } }
    localStorage.setItem('avatar-model-url', '/models/haru/Haru.model3.json')
    localStorage.setItem('avatar-motion-enabled', 'false')
  })
  const page = await context.newPage(), errors = [], failures = [], textures = new Map(), sent = []
  let sessionId
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', msg => { if (msg.type() === 'error' && /Avatar update failed|Audio playback failed/.test(msg.text())) errors.push(msg.text()) })
  page.on('response', response => {
    if (response.status() >= 400) failures.push({ url: response.url(), status: response.status() })
    const url = decodeURIComponent(new URL(response.url()).pathname)
    const texture = url.match(/\/models\/deepseek\/大肥鱼\.4096\/(texture_0[0-4]\.png)$/)
    if (texture) textures.set(texture[1], response.status())
  })
  page.on('websocket', socket => {
    socket.on('framereceived', event => {
      try { const value = JSON.parse(String(event.payload)); if (value.type === 'session') sessionId = value.session_id } catch {}
    })
    socket.on('framesent', event => { try { sent.push(JSON.parse(String(event.payload))) } catch {} })
  })
  try {
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' })
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
    await page.waitForTimeout(700)
    assert(await page.evaluate(() => performance.getEntriesByType('resource').some(r => decodeURI(r.name).includes('大肥鱼.moc3'))))
    for (let index = 0; index < 5; index++) {
      const name = `texture_0${index}.png`
      assert.equal(textures.get(name), 200, `${name} must be loaded successfully from the actual model directory`)
    }
    const frameIntervals = await page.evaluate(() => new Promise(resolve => {
      const intervals = []; let last; const start = performance.now()
      const frame = now => { if (last !== undefined) intervals.push(now - last); last = now; if (now - start < 3000) requestAnimationFrame(frame); else resolve(intervals) }
      requestAnimationFrame(frame)
    }))
    frameIntervals.sort((a, b) => a - b)
    const frameTiming = { samples: frameIntervals.length, median_ms: frameIntervals[Math.floor(frameIntervals.length * .5)], p95_ms: frameIntervals[Math.floor(frameIntervals.length * .95)] }
    await page.screenshot({ path: path.join(out, 'desktop.png'), fullPage: true })
    const select = page.getByRole('combobox', { name: '角色表情' })
    // Compare the heart-eye expression to its neutral state over several idle frames.
    // This bounds ordinary breathing/blinking variation without using model internals.
    const canvas = page.locator('.avatar-canvas canvas')
    async function snapshot() {
      const buffer = await canvas.screenshot()
      return page.evaluate(async bytes => {
        const image = await createImageBitmap(new Blob([new Uint8Array(bytes)], { type: 'image/png' }))
        const copy = document.createElement('canvas'); copy.width = image.width; copy.height = image.height
        const ctx = copy.getContext('2d'); ctx.drawImage(image, 0, 0); image.close()
        const x = Math.floor(copy.width * .39), y = Math.floor(copy.height * .42)
        const width = Math.floor(copy.width * .22), height = Math.floor(copy.height * .09)
        return { width, height, pixels: Array.from(ctx.getImageData(x, y, width, height).data) }
      }, [...buffer])
    }
    function difference(a, b) {
      assert.equal(a.width, b.width); assert.equal(a.height, b.height)
      let changed = 0
      for (let i = 0; i < a.pixels.length; i += 4) {
        if (Math.abs(a.pixels[i] - b.pixels[i]) + Math.abs(a.pixels[i + 1] - b.pixels[i + 1]) + Math.abs(a.pixels[i + 2] - b.pixels[i + 2]) > 45) changed++
      }
      return changed / (a.width * a.height)
    }
    await select.selectOption(''); await page.waitForTimeout(700)
    const neutralA = await snapshot(); await page.waitForTimeout(400); const neutralB = await snapshot()
    await select.selectOption('爱心眼'); await page.waitForTimeout(700)
    const heartA = await snapshot(); await page.waitForTimeout(400); const heartB = await snapshot()
    const idleDiff = difference(neutralA, neutralB), expressionDiff = Math.min(difference(neutralA, heartA), difference(neutralB, heartB))
    assert(expressionDiff > 0.001 && expressionDiff > idleDiff * 1.1, `heart-eye expression must alter canvas beyond idle motion (idle=${idleDiff}, expression=${expressionDiff})`)
    for (const expression of ['爱心眼', '圈圈眼', '流泪', '']) {
      await select.selectOption(expression); await page.waitForTimeout(700)
      await page.locator('.stage-scene').screenshot({ path: path.join(out, `expression-${expression || 'natural'}.png`) })
    }
    const wav = fs.readFileSync(path.join(root, 'artifacts/live-smoke/input.wav')).toString('base64')
    await page.evaluate(() => {
      window.__mouthSamples = []; window.__avatarFrames = []
      const emitter = window.PIXI.utils.EventEmitter.prototype
      const original = emitter.emit
      window.__restoreMouthSampler = () => { emitter.emit = original }
      emitter.emit = function (...args) {
        const started = performance.now(); const result = original.apply(this, args)
        if (args[0] === 'beforeModelUpdate' && this.coreModel) {
          const value = this.coreModel.getParameterValueById('ParamMouthOpenY')
          if (Number.isFinite(value)) window.__mouthSamples.push(value)
          window.__avatarFrames.push({ headX: this.coreModel.getParameterValueById('ParamAngleX'), noseOpacity: this.coreModel.getPartOpacityById('Part46'), handlerMs: performance.now() - started })
        }
        return result
      }
    })
    await page.getByRole('button', { name: '设置', exact: true }).first().click()
    await page.getByRole('checkbox', { name: '自然动作', exact: true }).check()
    assert.equal(await page.evaluate(() => localStorage.getItem('avatar-motion-enabled')), 'true')
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.waitForTimeout(1800)
    const idleFrames = await page.evaluate(() => window.__avatarFrames.slice())
    assert(idleFrames.length > 10, 'AIRI motion must update on actual model frames')
    const naturalMotion = {
      idleHeadRange: Math.max(...idleFrames.map(f => f.headX)) - Math.min(...idleFrames.map(f => f.headX)),
      noseOpacityMin: Math.min(...idleFrames.map(f => f.noseOpacity)),
      maxUpdateHandlerMs: Math.max(...idleFrames.map(f => f.handlerMs)),
    }
    assert(naturalMotion.idleHeadRange > .005, 'enabled AIRI motion must change the actual head parameter')
    assert(naturalMotion.noseOpacityMin > .99, 'original nose must remain visible; do not hide Part46')
    await page.locator('.stage-scene').screenshot({ path: path.join(out, 'airi-idle.png') })
    const replay = audio => page.evaluate(payload => {
      window.__avatarTestSocket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type: 'audio', epoch: 0, segment_id: 0, format: 'wav', emotion: 'neutral', text: '受控音频回放', audio: payload }) }))
    }, audio)
    await replay(wav)
    await page.locator('.stop-btn').waitFor()
    assert(await page.getByText('正在回应', { exact: true }).isVisible(), 'controlled WAV must enter playing state')
    await page.waitForFunction(() => window.__mouthSamples.some(value => value > .03), null, { timeout: 15000 })
    await page.waitForTimeout(250)
    const speakingSamples = await page.evaluate(() => window.__mouthSamples.slice())
    assert(speakingSamples.length > 0 && Math.max(...speakingSamples) > .03, `real WAV must drive mouth parameter above rest (samples=${speakingSamples.length}, peak=${Math.max(0, ...speakingSamples)})`)
    await page.locator('.stage-scene').screenshot({ path: path.join(out, 'speaking.png') })
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.waitForTimeout(150)
    assert(sent.some(frame => frame.type === 'interrupt'), 'stop must send an interrupt to the server')
    assert.equal(await page.locator('.stop-btn').count(), 0, 'stop must immediately clear playback state')
    await page.waitForTimeout(400)
    const afterStop = await page.evaluate(() => window.__mouthSamples.slice(-10))
    assert(afterStop.length && Math.max(...afterStop) < .03, 'mouth must close after interrupted audio')
    await page.evaluate(() => window.__restoreMouthSampler())
    assert(!sent.some(frame => frame.type === 'playback.ack' && frame.epoch === 0 && frame.segment_id === 0), 'interrupted audio must not be acknowledged as fully played')
    await replay(wav)
    await page.waitForTimeout(500)
    assert.equal(await page.locator('.stop-btn').count(), 0, 'interrupted old audio must stay discarded')
    await page.locator('.stage-scene').screenshot({ path: path.join(out, 'interrupted.png') })
    await page.setViewportSize({ width: 1080, height: 1920 })
    await page.getByRole('button', { name: '全屏', exact: true }).click()
    await page.waitForTimeout(700)
    await page.screenshot({ path: path.join(out, 'portrait-stage.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: path.join(out, 'mobile-stage.png'), fullPage: true })
    await page.getByRole('button', { name: '退出全屏' }).click()
    await page.locator('.app:not(.stage-mode)').waitFor()
    assert(await page.getByPlaceholder('说点什么，或开启语音...').isVisible(), 'chat input must be visible after leaving fullscreen')
    assert(await page.getByRole('button', { name: '设置' }).first().isVisible(), 'settings must be accessible after leaving fullscreen')
    await page.waitForTimeout(500)
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.screenshot({ path: path.join(out, 'mobile.png'), fullPage: true })
    await page.getByRole('button', { name: '全屏', exact: true }).click()
    await page.locator('.app.stage-mode').waitFor()
    await page.keyboard.press('Escape')
    await page.locator('.app:not(.stage-mode)').waitFor()
    assert.deepEqual(errors, [], 'runtime errors')
    assert.deepEqual(failures, [], 'missing model resources')
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ passed: true, model: 'DeepSeek-chan（大肥鱼）', checks: ['actual moc and five successful texture HTTP responses', 'old default migration', 'heart-eye canvas pixels differ from idle', 'controlled local WAV drives mouth parameter and closes after interruption', 'interrupt event and stale audio rejection', 'AIRI natural motion on actual model with original nose visible', 'portrait fullscreen', '390px layout'], naturalMotion, expressionDiff, idleDiff, mouthPeak: Math.max(...speakingSamples), mouthAfterStop: Math.max(...afterStop), frameTiming, textures: Object.fromEntries(textures), errors, failures, limitations: 'Controlled injected WAV; no physical microphone, audio-output measurement, or cloud-model conversation. Headless requestAnimationFrame intervals do not measure physical display or completed GPU frames.' }, null, 2))
    for (const name of ['failure.json', 'failure.png']) fs.rmSync(path.join(out, name), { force: true })
    console.log(JSON.stringify({ passed: true, out }))
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true }).catch(() => {})
    fs.writeFileSync(path.join(out, 'failure.json'), JSON.stringify({ error: String(error), errors, failures, audioState: await page.evaluate(() => ({ state: window.__avatarAudio?.state, time: window.__avatarAudio?.currentTime, mouth: window.__mouthSamples?.slice(-12) })) }, null, 2))
    throw error
  } finally {
    if (sessionId) await context.request.delete(`http://127.0.0.1:8765/api/sessions/${sessionId}`).catch(() => {})
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
