const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const base = 'http://127.0.0.1:8897'
const decode = payload => { const b = Buffer.from(payload), i = b.indexOf(Buffer.from('{"label"')); try { return i < 0 ? undefined : JSON.parse(b.subarray(i).toString()) } catch {} }
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage(), received = [], sent = [], errors = [], sessions = new Set(); let session
  page.on('pageerror', e => errors.push(e.message)); page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') { session = (await r.json()).id; sessions.add(session) } })
  page.on('websocket', ws => { ws.on('framereceived', f => { const e = decode(f.payload); if (e) received.push(e) }); ws.on('framesent', f => { const e = decode(f.payload); if (e) sent.push(e) }) })
  const wait = async (fn, why, timeout = 90000) => { const until = Date.now() + timeout; while (!await fn()) { if (Date.now() > until) throw Error(why); await page.waitForTimeout(100) } }
  const boundaries = from => received.slice(from).filter(x => x.data?.type === 'voice.playback.boundary').map(x => x.data)
  const acks = from => sent.slice(from).filter(x => x.type === 'client-message' && x.data?.t === 'voice.playback').map(x => x.data.d)
  const history = async () => (await fetch(`${base}/api/sessions/${session}/messages`)).json()
  const send = async text => { await page.getByPlaceholder('说点什么，或开启语音...').fill(text); await page.getByRole('button', { name: '发送', exact: true }).click() }
  try {
    await page.goto(base, { waitUntil: 'networkidle' }); await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
    let from = received.length, sf = sent.length; await send('请继续详细介绍。')
    await wait(() => boundaries(from).length >= 3, 'missing sentence boundaries')
    await wait(() => acks(sf).length >= boundaries(from).length, 'missing sentence ACK')
    const first = boundaries(from), firstAcks = acks(sf); assert(first.every(b => firstAcks.some(a => a.epoch === b.epoch && a.consumed_samples === b.samples)))
    const completeText = first.map(b => b.text).join(''); await wait(async () => (await history()).some(x => x.role === 'assistant' && x.content === completeText), 'full confirmed text missing')
    const before = (await history()).filter(x => x.role === 'assistant').length
    from = received.length; sf = sent.length; await send('再次详细介绍。')
    await wait(() => acks(sf).length >= 2, 'missing first two sentence ACKs')
    await page.getByRole('button', { name: '停止', exact: true }).click(); await page.waitForTimeout(1500)
    const confirmed = acks(sf), interruptedBoundaries = boundaries(from), interruptedHistory = (await history()).filter(x => x.role === 'assistant'), after = interruptedHistory.length
    assert(after > before, 'confirmed sentences not preserved')
    const confirmedText = interruptedBoundaries.filter(b => confirmed.some(a => a.epoch === b.epoch)).map(b => b.text).join('')
    assert.equal(interruptedHistory.at(-1).content, confirmedText, 'stored text must equal confirmed prefix')
    from = received.length; sf = sent.length; await send('换一个问题。')
    await wait(() => boundaries(from).length > 0 && acks(sf).length >= boundaries(from).length, 'next turn failed')
    assert.deepEqual(errors, []); console.log(JSON.stringify({ first: first.map(b => b.text), firstAcks: firstAcks.length, completeText, interrupted: interruptedBoundaries.map(b => ({ text: b.text, ack: confirmed.some(a => a.epoch === b.epoch) })), stored: interruptedHistory.at(-1).content, next: acks(sf).length, errors }))
  } finally { await browser.close(); for (const id of sessions) await fetch(`${base}/api/sessions/${id}`, { method: 'DELETE' }).catch(() => {}) }
})().catch(error => { console.error(error); process.exitCode = 1 })
