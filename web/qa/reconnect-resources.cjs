const assert = require('node:assert/strict')
const { chromium } = require('playwright')
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] })
  const context = await browser.newContext()
  await context.addInitScript(() => {
    window.__contexts = []; window.__tracks = []; window.__sockets = []
    const AC = window.AudioContext; window.AudioContext = class extends AC { constructor(...args) { super(...args); window.__contexts.push(this) } }
    const WS = window.WebSocket; window.WebSocket = class extends WS { constructor(...args) { super(...args); window.__sockets.push(this) } }
    const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices); navigator.mediaDevices.getUserMedia = async (...args) => { const stream = await get(...args); window.__tracks.push(...stream.getAudioTracks()); return stream }
  })
  const page = await context.newPage(), sessions = new Set(), routes = []; let fail = false, client, server
  await page.routeWebSocket(/\/ws\/voice/, ws => { routes.push({ fail, at: Date.now() }); if (fail) { void ws.close({ code: 1013 }); return }; client = ws; server = ws.connectToServer() })
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') sessions.add((await r.json()).id) })
  const snapshot = () => page.evaluate(() => ({ contexts: window.__contexts.map(c => c.state), tracks: window.__tracks.map(t => t.readyState), sockets: window.__sockets.map(s => s.readyState) }))
  const wait = async (fn, label, timeout = 90000) => { const end = Date.now() + timeout; while (!await fn()) { if (Date.now() > end) throw Error(label); await page.waitForTimeout(100) } }
  try {
    const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8875'
    await page.goto(base, { waitUntil: 'networkidle' }); await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: '开启语音' }).click(); await wait(() => page.getByRole('button', { name: '正在聆听' }).isVisible(), 'mic not active')
    let peak = 0; const snapshots = []
    for (let i = 0; i < 3; i++) {
      await client.close({ code: 1012 }); await server.close({ code: 1012 })
      await wait(() => page.getByText('本地服务已连接', { exact: true }).isHidden(), 'disconnect not observed')
      await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 60000 }); await page.waitForTimeout(500)
      const s = await snapshot(); snapshots.push(s); peak = Math.max(peak, s.contexts.filter(x => x !== 'closed').length)
      assert(s.tracks.every(x => x === 'ended')); assert(s.contexts.filter(x => x !== 'closed').length <= 1)
      await page.getByRole('button', { name: '开启语音' }).click(); await wait(() => page.getByRole('button', { name: '正在聆听' }).isVisible(), 'mic reopen failed')
      const reopened = await snapshot(); peak = Math.max(peak, reopened.contexts.filter(x => x !== 'closed').length)
    }
    const final = await snapshot(); assert.equal(final.tracks.filter(x => x === 'live').length, 1); assert(final.sockets.filter(x => x < 2).length <= 1)
    console.log(JSON.stringify({ routes, peakLiveContexts: peak, final, snapshots }, null, 2))
  } finally { await browser.close(); for (const id of sessions) await fetch(`${process.env.VOICE_TEST_URL || 'http://127.0.0.1:8875'}/api/sessions/${id}`, { method: 'DELETE' }).catch(() => {}) }
})().catch(error => { console.error(error); process.exitCode = 1 })
