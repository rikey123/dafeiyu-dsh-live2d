/* Local, silent observation of the real DeepSeek Cubism model. No microphone,
   audio or cloud interaction; video and measurements support human review. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const root = path.resolve(__dirname, '..'), out = path.join(root, 'artifacts/idle-motion')
const appUrl = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8765'
fs.mkdirSync(out, { recursive: true })

;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.addInitScript(() => {
    localStorage.setItem('avatar-model-url', '/models/deepseek/avatar.model3.json')
    localStorage.setItem('avatar-motion-enabled', 'true')
    localStorage.removeItem('avatar-motion-strength')
  })
  const page = await context.newPage(), errors = [], failures = []
  let sessionId
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && /Avatar|Live2D|WebGL/i.test(message.text())) errors.push(message.text()) })
  page.on('response', response => { if (response.status() >= 400) failures.push({ url: response.url(), status: response.status() }) })
  page.on('response', async response => { if (response.url().endsWith('/api/sessions') && response.request().method() === 'POST') sessionId = (await response.json()).id })
  try {
    await page.goto(appUrl, { waitUntil: 'networkidle' })
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
    await page.evaluate(() => {
      const emitter = window.PIXI.utils.EventEmitter.prototype, original = emitter.emit
      window.__idleSamples = []; window.__idleCore = null; window.__idleParameters = {}
      window.__restoreIdleEmitter = () => { emitter.emit = original }
      emitter.emit = function (...args) {
        const result = original.apply(this, args)
        if (args[0] === 'beforeModelUpdate' && this.coreModel) { window.__idleCore = this.coreModel; window.__idleParameters = Object.fromEntries(['ParamAngleX', 'ParamAngleY', 'ParamAngleZ', 'ParamBodyAngleX', 'ParamBodyAngleY', 'ParamBodyAngleZ', 'ParamEyeLOpen', 'ParamEyeROpen', 'ParamBreath', 'ParamMouthOpenY'].map(id => [id, this.coreModel.getParameterValueById(id)])) }
        return result
      }
    })
    await page.waitForFunction(() => window.__idleCore?._model?.drawables?.vertexPositions, null, { timeout: 15000 })
    await page.waitForTimeout(2500)
    await page.evaluate(() => {
      const core = window.__idleCore, raw = core._model, draw = raw.drawables
      const wanted = ['Part81', 'Part82', 'Part85', 'Part89']
      const getString = value => typeof value === 'string' ? value : value?.s ?? String(value)
      const parts = Array.from(raw.parts.ids, getString)
      const indexes = wanted.map(id => parts.indexOf(id))
      if (indexes.some(index => index < 0)) throw Error(`Missing body parts: ${JSON.stringify({ wanted, indexes })}`)
      const meshes = wanted.map((id, i) => {
        const parent = indexes[i], candidates = []
        for (let d = 0; d < draw.count; d++) if (draw.parentPartIndices[d] === parent && draw.vertexPositions[d]?.length >= 2) candidates.push(d)
        if (!candidates.length) throw Error(`No drawable meshes for ${id}`)
        return { part: id, partIndex: parent, drawables: candidates }
      })
      window.__idleMetadata = { parts: meshes, sample: 'local model drawable vertex coordinates; sampled on animation frame after model update', userInput: 'none' }
      const ids = ['ParamAngleX', 'ParamAngleY', 'ParamAngleZ', 'ParamBodyAngleX', 'ParamBodyAngleY', 'ParamBodyAngleZ', 'ParamEyeLOpen', 'ParamEyeROpen', 'ParamBreath', 'ParamMouthOpenY']
      let started = performance.now(), previousSample = -100
      window.__idleCapture = { started, recording: true }
      const sample = now => {
        if (!window.__idleCapture.recording) return
        if (now - previousSample < 100) { requestAnimationFrame(sample); return }; previousSample = now
        const parameters = { ...window.__idleParameters }
        const geometry = Object.fromEntries(meshes.map(({ part, drawables }) => [part, drawables.map(index => {
          const vertices = draw.vertexPositions[index]
          // Same fixed vertex positions across frames; retain the whole mesh for reproducible range calculations.
          return { index, vertices: Array.from(vertices) }
        })]))
        window.__idleSamples.push({ ms: now - started, parameters, geometry })
        requestAnimationFrame(sample)
      }
      requestAnimationFrame(sample)
      const canvas = document.querySelector('.avatar-canvas canvas')
      const stream = canvas.captureStream(30), chunks = []
      if (!MediaRecorder.isTypeSupported('video/webm;codecs=vp9')) throw Error('Edge does not support VP9 canvas recording')
      const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9' })
      window.__idleCapture.stop = () => new Promise((resolve, reject) => {
        recorder.onerror = event => reject(event.error || Error('MediaRecorder failed'))
        recorder.onstop = async () => { stream.getTracks().forEach(track => track.stop()); resolve(Array.from(new Uint8Array(await new Blob(chunks, { type: recorder.mimeType }).arrayBuffer()))) }
        recorder.stop()
      })
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      recorder.start(1000)
    })
    for (let second = 5; second <= 20; second += 5) {
      await page.waitForTimeout(5000)
      await page.locator('.stage-scene').screenshot({ path: path.join(out, `idle-${second}s.png`) })
    }
    const capture = await page.evaluate(async () => {
      window.__idleCapture.recording = false
      return { video: await window.__idleCapture.stop(), samples: window.__idleSamples, metadata: window.__idleMetadata }
    })
    fs.writeFileSync(path.join(out, 'idle.webm'), Buffer.from(capture.video))
    assert(capture.video.length > 1000, 'canvas recording must contain video')
    assert(capture.samples.length > 20, 'must collect multiple real model frames')
    const summarize = values => ({ min: Math.min(...values), max: Math.max(...values), range: Math.max(...values) - Math.min(...values) })
    const windows = []
    for (let start = 0; start < 20000; start += 5000) {
      const samples = capture.samples.filter(sample => sample.ms >= start && sample.ms < start + 5000)
      assert(samples.length, `missing samples in ${start / 1000}s window`)
      const parameters = Object.fromEntries(Object.keys(samples[0].parameters).map(id => [id, summarize(samples.map(s => s.parameters[id]).filter(Number.isFinite))]))
      const geometry = Object.fromEntries(capture.metadata.parts.map(({ part }) => {
        const first = samples[0].geometry[part], changes = []
        for (const sample of samples) for (let m = 0; m < first.length; m++) {
          const current = sample.geometry[part][m].vertices, base = first[m].vertices
          for (let i = 0; i < base.length; i++) changes.push(Math.abs(current[i] - base[i]))
        }
        return [part, { drawableCount: first.length, maxVertexDelta: changes.reduce((max, value) => Math.max(max, value), 0) }]
      }))
      windows.push({ startMs: start, endMs: start + 5000, frames: samples.length, parameters, geometry })
    }
    for (const window of windows) {
      assert(window.parameters.ParamAngleX.range > .1, 'rendered head angle must move in every five-second window')
      assert(window.parameters.ParamBodyAngleX.range > .1, 'rendered body angle must move in every five-second window')
      assert(window.geometry.Part85.maxVertexDelta > .001, 'actual clothing vertices must deform beyond breath-only baseline')
      assert(window.parameters.ParamMouthOpenY.max < .03, 'silent idle mouth must remain closed')
    }
    assert(windows.some(w => w.parameters.ParamEyeLOpen.min < .3), 'SDK blink must visibly close the eye during idle')
    assert(windows.some(w => w.parameters.ParamBreath.range > .1), 'idle must keep the SDK breathing cycle')
    await page.getByRole('button', { name: '设置', exact: true }).first().click()
    const checkbox = page.getByRole('checkbox', { name: '自然动作', exact: true })
    assert(await checkbox.isChecked(), 'natural motion is enabled during recording')
    await checkbox.uncheck()
    assert.equal(await page.evaluate(() => localStorage.getItem('avatar-motion-enabled')), 'false')
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    const off = await page.evaluate(async () => {
      const values = []; const start = performance.now()
      while (performance.now() - start < 2000) {
        await new Promise(resolve => requestAnimationFrame(resolve))
        values.push({ ms: performance.now() - start, x: window.__idleCore.getParameterValueById('ParamAngleX'), bodyX: window.__idleCore.getParameterValueById('ParamBodyAngleX') })
      }
      return values
    })
    await page.screenshot({ path: path.join(out, 'motion-disabled.png') })
    await page.evaluate(() => window.__restoreIdleEmitter())
    assert.deepEqual(errors, [], 'avatar errors')
    assert.deepEqual(failures, [], 'failed resources')
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ model: 'DeepSeek-chan', method: capture.metadata, durationMs: capture.samples.at(-1).ms, windows, motionDisabled: off, errors, failures, limitations: 'Silent synthetic browser observation; no mic or audio. Local vertex displacement does not establish visual quality or whole-model screen motion. Review video and screenshots.' }, null, 2))
    console.log(JSON.stringify({ out, frames: capture.samples.length, windows: windows.length, errors, failures }))
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true }).catch(() => {})
    fs.writeFileSync(path.join(out, 'failure.json'), JSON.stringify({ error: String(error), errors, failures }, null, 2))
    throw error
  } finally {
    if (sessionId) await context.request.delete(`${appUrl}/api/sessions/${sessionId}`).catch(() => {})
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
