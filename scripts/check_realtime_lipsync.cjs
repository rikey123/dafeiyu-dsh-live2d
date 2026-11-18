/* Real compiled UI + local GPU/CPU TTS. The isolated gateway supplies a
 * labelled LLM fixture; no paid provider, physical mic or lip-accuracy claim.
 * Start scripts/serve_voice_acceptance.py --manage-model-services on 8875.
 */
const fs = require('node:fs'), assert = require('node:assert/strict')
const { chromium } = require('../qa/node_modules/playwright')
const base = 'http://127.0.0.1:8875'
const out = 'E:/Dafeiyu/verification/realtime-lipsync'
const report = { cases: [], method: 'Real Edge/Live2D/wLipSync/worklet + local models; controlled loopback LLM, no paid API or physical audio measurement.' }
fs.mkdirSync(out, { recursive: true })
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
const wait = async (fn, label, timeout = 30000) => {
  const end = Date.now() + timeout
  while (Date.now() < end) { if (await fn()) return; await delay(25) }
  throw Error(label)
}
const api = async (path, init) => { const r = await fetch(base + path, init); if (!r.ok) throw Error(`${path}: HTTP ${r.status}`); return r.json() }
const health = async port => { try { return await (await fetch(`http://127.0.0.1:${port}/health`)).json() } catch { return null } }
function instrument() {
  window.__rt = { consumed: [], frames: [], mouths: [], nodes: [], micCalls: 0 }
  navigator.mediaDevices.getUserMedia = async () => { window.__rt.micCalls++; throw Error('Microphone forbidden in lip-sync QA') }
  const Native = window.AudioWorkletNode
  window.AudioWorkletNode = class extends Native {
    constructor(...args) {
      super(...args)
      window.__rt.nodes.push({ name: args[1], node: this })
      this.port.addEventListener('message', e => {
        const r = window.__rt, now = performance.now()
        if (e.data?.event === 'consumed') r.consumed.push({ at: now, samples: e.data.samples })
        if (args[1] === 'wlipsync-processor') r.frames.push({ at: now, timestamp: e.data.timestamp, volume: e.data.volume, name: e.data.name })
        if (r.consumed.length > 3000) r.consumed.shift()
        if (r.frames.length > 3000) r.frames.shift()
      })
    }
  }
}

;(async () => {
 const browser = await chromium.launch({ channel: 'msedge', headless: true })
 let page, context
 const events = [], sent = [], errors = [], wasmRequests = []
 let sessionId
 function wire(payload) { const b = Buffer.from(payload), i = b.indexOf(Buffer.from('{"label"')); if (i >= 0) { try { return JSON.parse(b.subarray(i).toString('utf8')) } catch {} } }
 async function open(failWasm = false) {
  context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
  await context.addInitScript(instrument)
  if (failWasm) await context.route('**/assets/wlipsync-*.wasm', route => route.abort())
  page = await context.newPage()
  page.on('pageerror', e => errors.push(e.message))
  page.on('request', r => { if (/wlipsync-.*\.wasm/.test(r.url())) wasmRequests.push(r.url()) })
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') sessionId = (await r.json()).id })
  page.on('websocket', socket => {
    socket.on('framereceived', ({ payload }) => { const e = wire(payload); if (e) events.push(e) })
    socket.on('framesent', ({ payload }) => { const e = wire(payload); if (e) sent.push(e) })
  })
  await page.goto(base)
  await ready()
  await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
  await page.evaluate(() => {
    const proto = window.PIXI.utils.EventEmitter.prototype, original = proto.emit
    proto.emit = function (...args) {
      const value = original.apply(this, args)
      if (args[0] === 'beforeModelUpdate' && this.coreModel) {
        const c = this.coreModel, r = window.__rt
        r.mouth = c.getParameterValueById('ParamMouthOpenY')
        r.mouths.push({ at: performance.now(), open: r.mouth, form: c.getParameterValueById('ParamMouthForm'), funnel: c.getParameterValueById('MouthFunnel') })
        if (r.mouths.length > 3000) r.mouths.shift()
      }
      return value
    }
  })
 }
 async function ready() { await page.waitForFunction(() => document.querySelector('.mic-btn')?.disabled === false, null, { timeout: 30000 }) }
 async function settings() { if (!await page.locator('.drawer').isVisible()) await page.getByRole('button', { name: '设置', exact: true }).click() }
 async function closeSettings() { if (await page.locator('.drawer').isVisible()) await page.getByRole('button', { name: '关闭', exact: true }).click() }
 async function configure(mode) {
  await settings()
  assert(!await page.locator('.drawer').getByText(/MFA/).count())
  assert(!await page.locator('label').filter({ hasText: /^音素对齐/ }).count())
  await page.locator('label').filter({ hasText: /^语音合成模式/ }).locator('select').selectOption(mode)
  if (mode === 'gpu') await page.locator('label').filter({ hasText: /^GPU 语音模型/ }).locator('select').selectOption('gpt_sovits')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await page.locator('.drawer').waitFor({ state: 'hidden' }); await ready()
  if (mode === 'gpu') await wait(async () => (await health(8770))?.ready, 'GPU did not finish preload', 200000)
  else await wait(async () => (await health(8772))?.configured, 'CPU service absent')
 }
 async function submit(label) {
  await page.getByPlaceholder('说点什么，或开启语音...').fill(label)
  await page.getByRole('button', { name: '发送', exact: true }).click()
 }
 async function playback(label, fallback = false) {
  const start = await page.evaluate(() => performance.now()), ei = events.length, si = sent.length, began = Date.now()
  const old = new Set((await api(`/api/sessions/${sessionId}/messages`)).map(m => m.id))
  await submit(label)
  await wait(() => events.slice(ei).some(e => e.type === 'error') || sent.slice(si).some(e => e.data?.t === 'voice.playback'), 'No actual playback ACK', 100000)
  assert.deepEqual(events.slice(ei).filter(e => e.type === 'error'), [])
  assert(!events.slice(ei).some(e => e.data?.type === 'voice.playback.phonemes'))
  await wait(async () => (await api(`/api/sessions/${sessionId}/messages`)).some(m => m.role === 'assistant' && !old.has(m.id)), 'History not confirmed by playback')
  const result = await page.evaluate(start => {
    const r = window.__rt, mouths = r.mouths.filter(x => x.at >= start), consumed = r.consumed.filter(x => x.at >= start), frames = r.frames.filter(x => x.at >= start)
    const firstMouth = mouths.find(x => x.open > .03), firstFrame = frames.find(x => x.volume > .001)
    return { consumedSamples: consumed.reduce((sum, x) => sum + x.samples, 0), classifiedFrames: frames.length, activeClassifications: frames.filter(x => x.volume > .001).length, maxMouth: Math.max(0, ...mouths.map(x => x.open)), variedShapes: mouths.some(x => x.open > .03 && (Math.abs(x.form) > .001 || x.funnel > .001)), firstMouthAfterConsumptionMs: firstMouth && consumed[0] ? firstMouth.at - consumed[0].at : null, firstMouthAfterActiveClassifierMessageMs: firstMouth && firstFrame ? firstMouth.at - firstFrame.at : null, micCalls: r.micCalls }
  }, start)
  assert(result.consumedSamples > 0 && result.maxMouth > .03)
  if (!fallback) assert(result.activeClassifications > 0 && result.variedShapes, 'Expected genuine classifier-driven model shapes')
  assert.equal(result.micCalls, 0)
  await wait(async () => (await page.evaluate(() => window.__rt.mouth)) < .005, 'Mouth stayed open after playback', 1000)
  return { ...result, submitToAckMs: Date.now() - began, physicalLipAccuracy: 'Not measured; message/render timing is not acoustic synchronization.' }
 }
 async function check(name, fn) {
  console.log('CHECK', name)
  try { report.cases.push({ name, status: 'passed', detail: await fn() }); console.log('PASS', name) }
  catch (e) { report.cases.push({ name, status: 'failed', error: String(e) }); console.log('FAIL', name, e.message); await page?.screenshot({ path: out + '/failure-' + report.cases.length + '.png' }).catch(() => {}) }
  fs.writeFileSync(out + '/browser-realtime.json', JSON.stringify(report, null, 2))
 }
 try {
  await wait(async () => { try { return (await api('/api/health')).status === 'ok' } catch { return false } }, 'Acceptance gateway unavailable')
  await open()
  for (const mode of ['gpu', 'cpu']) await check(`${mode} realtime PCM, classifier, Live2D and ACK`, async () => {
    await configure(mode)
    const saved = await api('/api/settings'), status = await api('/api/status')
    assert(!('tts_alignment' in saved) && !('mfa_url' in saved) && !('mfa' in status.optional))
    return await playback(mode + ' 实时口型验收')
  })
  await check('mute closes mouth, unmute resumes, stop retires late frames', async () => {
    await closeSettings(); await submit('静音和停止口型验收')
    await wait(async () => (await page.evaluate(() => window.__rt.mouth)) > .03, 'No moving mouth to mute', 60000)
    const muted = Date.now(); await page.getByRole('slider', { name: '音量', exact: true }).press('Home')
    await wait(async () => (await page.evaluate(() => window.__rt.mouth)) < .005, 'Mute did not close mouth', 1000)
    const muteCloseMs = Date.now() - muted
    await page.getByRole('slider', { name: '音量', exact: true }).press('End')
    await wait(async () => (await page.evaluate(() => window.__rt.mouth)) > .03, 'Unmute did not resume mouth', 1500)
    const stopped = Date.now(); await page.getByRole('button', { name: '停止', exact: true }).click()
    await wait(async () => (await page.evaluate(() => window.__rt.mouth)) < .005, 'Stop did not close mouth', 1000)
    const stopCloseMs = Date.now() - stopped
    await delay(300); assert((await page.evaluate(() => window.__rt.mouth)) < .005, 'Late frames reopened stopped mouth')
    return { muteCloseMs, stopCloseMs, nextTurn: await playback('停止后下一轮口型验收') }
  })
  await check('reconnect reuses compiled WASM and initializes per-context worklets', async () => {
    const before = wasmRequests.length
    for (const value of ['local-vits', 'airi']) { await settings(); await page.getByLabel('口型声线', { exact: true }).selectOption(value); await ready(); await delay(200) }
    await closeSettings()
    assert.equal(wasmRequests.length, before)
    return { wasmRequests: wasmRequests.length, perContextLipNodes: await page.evaluate(() => window.__rt.nodes.filter(x => x.name === 'wlipsync-processor').length), playback: await playback('重连后的实时口型') }
  })
  await context.close()
  await open(true)
  await check('unavailable WASM is visible and realtime RMS playback remains usable', async () => {
    await settings()
    await page.getByText(/口型：音量口型回退/).waitFor({ timeout: 15000 })
    await closeSettings()
    return { engine: 'RMS fallback, not phoneme recognition', playback: await playback('口型库失败时的音量回退', true) }
  })
 } finally {
  await api('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ tts_mode: 'api', clear_tts_api_key: true }) }).catch(() => {})
  await context?.close().catch(() => {}); await browser.close()
  report.pageErrors = errors
  fs.writeFileSync(out + '/browser-realtime.json', JSON.stringify(report, null, 2))
 }
 console.log(JSON.stringify(report, null, 2))
 if (report.cases.some(x => x.status !== 'passed') || errors.length) process.exitCode = 1
})().catch(e => { report.fatal = String(e); fs.writeFileSync(out + '/browser-realtime.json', JSON.stringify(report, null, 2)); console.error(e); process.exitCode = 1 })
