const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8875'
const provider = process.env.VOICE_PROVIDER_URL || 'http://127.0.0.1:8874'
function event(payload) { const bytes = Buffer.from(payload), start = bytes.indexOf(Buffer.from('{"label"')); if (start < 0) return; try { return JSON.parse(bytes.subarray(start).toString('utf8')) } catch {} }
;(async () => {
  assert(['8875', '8897'].includes(new URL(base).port))
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.addInitScript(() => {
    window.__tracks = []; window.__consumed = []; window.__micCalls = 0; window.__sockets = []
    const Socket = window.WebSocket
    window.WebSocket = class extends Socket { constructor(...args) { super(...args); window.__sockets.push(this) } }
    const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async (...args) => { window.__micCalls++; const stream = await get(...args); window.__tracks.push(...stream.getAudioTracks()); return stream }
    const Native = window.AudioWorkletNode
    window.AudioWorkletNode = class extends Native { constructor(...args) { super(...args); if (args[1] === 'stream_processor') this.port.addEventListener('message', e => { if (e.data?.event === 'consumed') window.__consumed.push({ ...e.data, at: Date.now() }) }) } }
  })
  const page = await context.newPage(), received = [], sent = [], errors = [], logs = [], sessions = new Set(), routes = []; let outage = false, routeClient, routeServer
  await page.routeWebSocket(/\/ws\/voice/, ws => { routes.push({ outage, at: Date.now() }); if (outage) { void ws.close({ code: 1013 }); return }; routeClient = ws; routeServer = ws.connectToServer(); ws.onMessage(data => { const value = event(data); if (value) sent.push(value); routeServer.send(data) }); routeServer.onMessage(data => { const value = event(data); if (value) received.push(value); ws.send(data) }) })
  let session
  page.on('pageerror', e => errors.push(e.message)); page.on('console', e => { if (e.type() === 'error') logs.push(e.text()) })
  page.on('response', async response => { if (response.url().endsWith('/api/sessions') && response.request().method() === 'POST') { session = (await response.json()).id; sessions.add(session) } })
  const wait = async (fn, label, timeout = 90000) => { const end = Date.now() + timeout; while (!await fn()) { if (Date.now() > end) throw Error(label); await page.waitForTimeout(100) } }
  const history = async () => (await fetch(`${base}/api/sessions/${session}/messages`)).json()
  try {
    const requestStart = (await (await fetch(`${provider}/test/requests`)).json()).length
    await page.goto(base, { waitUntil: 'networkidle' }); await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: '设置', exact: true }).first().click(); await page.waitForTimeout(2500)
    const lipStatus = await page.locator('.settings-form').innerText(); await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByRole('button', { name: '开启语音' }).click(); await wait(() => page.getByRole('button', { name: '正在聆听' }).isVisible(), 'microphone not started')
    const micCalls = await page.evaluate(() => window.__micCalls)
    const suffix = crypto.randomUUID(), firstPrompt = `请继续详细介绍。${suffix}`, secondPrompt = `换一个问题。${suffix}`
    const input = page.getByPlaceholder('说点什么，或开启语音...'); await input.fill(firstPrompt); await page.getByRole('button', { name: '发送', exact: true }).click()
    await wait(() => received.some(e => e.data?.type === 'voice.playback.start'), 'no first epoch')
    const oldEpoch = received.find(e => e.data?.type === 'voice.playback.start').data.epoch
    await wait(() => page.evaluate(epoch => window.__consumed.some(x => x.epoch === epoch), oldEpoch), 'no first audio')
    outage = true; await routeClient.close({ code: 1012 }); await routeServer.close({ code: 1012 }); await wait(() => page.getByText('本地服务已连接', { exact: true }).isHidden(), 'disconnect not observed'); await page.waitForTimeout(2000)
    const stopped = await page.evaluate(() => window.__tracks.every(t => t.readyState === 'ended'))
    outage = false; await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 45000 })
    await page.waitForTimeout(1000)
    assert(stopped, 'microphone track remained live after disconnect'); assert.equal(await page.evaluate(() => window.__micCalls), micCalls, 'microphone reopened')
    assert(!sent.some(e => e.type === 'client-message' && e.data?.t === 'voice.playback' && e.data?.d?.epoch === oldEpoch), 'interrupted epoch acknowledged')
    const before = (await history()).filter(x => x.role === 'assistant').length, from = received.length
    await input.fill(secondPrompt); await page.getByRole('button', { name: '发送', exact: true }).click()
    await wait(async () => (await history()).filter(x => x.role === 'assistant').slice(before).some(x => x.content === '好的，我们换一个问题。你想聊些什么？'), 'next turn not fully confirmed')
    await wait(() => received.slice(from).filter(e => e.data?.type === 'voice.playback.boundary').length >= 2, 'missing next segment')
    const boundaries = received.slice(from).filter(e => e.data?.type === 'voice.playback.boundary'); const b = boundaries[0].data, consumed = await page.evaluate(epoch => window.__consumed.filter(x => x.epoch === epoch).reduce((sum, x) => sum + x.samples, 0), b.epoch)
    for (const { data } of boundaries) { const count = await page.evaluate(epoch => window.__consumed.filter(x => x.epoch === epoch).reduce((sum, x) => sum + x.samples, 0), data.epoch); assert.equal(count, data.samples); assert(sent.some(e => e.data?.t === 'voice.playback' && e.data?.d?.epoch === data.epoch && e.data.d.consumed_samples === data.samples)) }; assert.deepEqual(errors, [])
    const requests = (await (await fetch(`${provider}/test/requests`)).json()).slice(requestStart)
    assert.equal(requests.filter(x => x.text === firstPrompt).length, 1); assert.equal(requests.filter(x => x.text === secondPrompt).length, 1); assert(!logs.some(x => x.includes('InvalidStateError')))
    console.log(JSON.stringify({ session, oldEpoch, newEpoch: b.epoch, consumed, micCalls, stopped, lipStatus, errors, logs, requests }, null, 2))
  } catch (error) { console.error(JSON.stringify({ routes, logs, errors, recent: received.slice(-8), body: await page.locator('body').innerText().catch(() => '') })); throw error } finally { await browser.close(); for (const id of sessions) await fetch(`${base}/api/sessions/${id}`, { method: 'DELETE' }).catch(() => {}) }
})().catch(error => { console.error(error); process.exitCode = 1 })
