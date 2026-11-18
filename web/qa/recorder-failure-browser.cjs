const assert = require('node:assert/strict')
const { chromium } = require('playwright')
;(async () => {
  const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8897'
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] }), context = await browser.newContext()
  await context.addInitScript(() => {
    window.__contexts = []; window.__tracks = []; window.__failed = false
    const AC = window.AudioContext; window.AudioContext = class extends AC { constructor(...args) { super(...args); window.__contexts.push(this) } }
    const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices); navigator.mediaDevices.getUserMedia = async (...args) => { const stream = await get(...args); window.__tracks.push(...stream.getAudioTracks()); return stream }
    const Node = window.AudioWorkletNode; window.AudioWorkletNode = class extends Node { constructor(...args) { super(...args); if (args[1] === 'audio_processor' && !window.__failed) { const send = this.port.postMessage.bind(this.port); this.port.postMessage = message => { if (message.event === 'start' && !window.__failed) { window.__failed = true; throw Error('injected recorder start failure') }; return send(message) } } } }
  })
  const page = await context.newPage(), sessions = new Set()
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') sessions.add((await r.json()).id) })
  try {
    await page.goto(base, { waitUntil: 'networkidle' }); await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: '开启语音' }).click(); await page.getByText(/麦克风启动失败/).waitFor({ timeout: 15000 })
    const failed = await page.evaluate(() => ({ contexts: window.__contexts.map(x => x.state), tracks: window.__tracks.map(x => x.readyState), injected: window.__failed }))
    assert(failed.injected); assert(failed.tracks.every(x => x === 'ended')); assert.equal(failed.contexts.filter(x => x !== 'closed').length, 1)
    await page.getByRole('button', { name: '开启语音' }).click(); await page.getByRole('button', { name: '正在聆听' }).waitFor({ timeout: 15000 })
    const retry = await page.evaluate(() => ({ contexts: window.__contexts.map(x => x.state), tracks: window.__tracks.map(x => x.readyState) }))
    assert.equal(retry.tracks.filter(x => x === 'live').length, 1); console.log(JSON.stringify({ failed, retry }))
  } finally { await browser.close(); for (const id of sessions) await fetch(`${base}/api/sessions/${id}`, { method: 'DELETE' }).catch(() => {}) }
})().catch(error => { console.error(error); process.exitCode = 1 })
