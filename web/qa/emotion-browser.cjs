const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const decode = value => { const b = Buffer.from(value), i = b.indexOf(Buffer.from('{"label"')); try { return i < 0 ? undefined : JSON.parse(b.subarray(i).toString()) } catch {} }
;(async () => {
  const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8897', browser = await chromium.launch({ channel: 'msedge', headless: true }), context = await browser.newContext()
  await context.addInitScript(() => { window.__consumed = []; const Node = window.AudioWorkletNode; window.AudioWorkletNode = class extends Node { constructor(...args) { super(...args); if (args[1] === 'stream_processor') this.port.addEventListener('message', e => { if (e.data?.event === 'consumed') window.__consumed.push({ ...e.data, at: performance.now() }) }) } }; navigator.mediaDevices.getUserMedia = async () => { throw Error('no microphone') } })
  const page = await context.newPage(), received = [], errors = [], sessions = new Set()
  page.on('pageerror', e => errors.push(e.message)); page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') sessions.add((await r.json()).id) }); page.on('websocket', ws => ws.on('framereceived', f => { const e = decode(f.payload); if (e) received.push(e) }))
  const wait = async (fn, message) => { const end = Date.now() + 30000; while (!await fn()) { if (Date.now() > end) throw Error(message); await page.waitForTimeout(30) } }
  try {
    await page.goto(base, { waitUntil: 'networkidle' }); await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 }); await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
    await page.evaluate(() => { window.__expressions = []; const p = window.PIXI.utils.EventEmitter.prototype, emit = p.emit; p.emit = function (...args) { const result = emit.apply(this, args); if (args[0] === 'beforeModelUpdate' && this.coreModel) window.__expressions.push({ at: performance.now(), happy: this.coreModel.getParameterValueById('key7'), sad: this.coreModel.getParameterValueById('key2') }); return result } })
    await page.getByPlaceholder('说点什么，或开启语音...').fill('请说两句情绪测试。'); await page.getByRole('button', { name: '发送', exact: true }).click()
    await wait(() => received.filter(x => x.data?.type === 'voice.playback.start' && typeof x.data.text === 'string').length >= 2, 'missing two start texts')
    const starts = received.filter(x => x.data?.type === 'voice.playback.start' && typeof x.data.text === 'string').map(x => x.data)
    assert(starts[0].text.includes('开心') && starts[1].text.includes('难过'), `unexpected fixture: ${JSON.stringify(starts.map(x => x.text))}`)
    await wait(async () => { const frames = await page.evaluate(() => window.__expressions); return frames.some(x => x.happy > .1) && frames.some(x => x.sad > .1) }, 'expected avatar expressions not observed')
    const data = await page.evaluate(() => ({ consumed: window.__consumed, expressions: window.__expressions }))
    for (const [index, key] of [[0, 'happy'], [1, 'sad']]) { const consumption = data.consumed.find(x => x.epoch === starts[index].epoch), expression = data.expressions.find(x => x[key] > .1); assert(consumption && expression && expression.at >= consumption.at, `expression ${index} preceded audio consumption`) }
    assert.deepEqual(errors, []); console.log(JSON.stringify({ starts, firstConsumed: starts.map(s => data.consumed.find(x => x.epoch === s.epoch)), firstHappy: data.expressions.find(x => x.happy > .1), firstSad: data.expressions.find(x => x.sad > .1), maxHappy: Math.max(...data.expressions.map(x => x.happy)), maxSad: Math.max(...data.expressions.map(x => x.sad)), errors }))
  } catch (error) { const data = await page.evaluate(() => ({ consumed: window.__consumed, expressions: window.__expressions })); console.error(JSON.stringify({ starts: received.filter(x => x.data?.type === 'voice.playback.start').map(x => x.data), maxHappy: Math.max(0, ...data.expressions.map(x => x.happy)), maxSad: Math.max(0, ...data.expressions.map(x => x.sad)), consumed: data.consumed.length, errors })); throw error } finally { await browser.close(); for (const id of sessions) await fetch(`${base}/api/sessions/${id}`, { method: 'DELETE' }).catch(() => {}) }
})().catch(error => { console.error(error); process.exitCode = 1 })
