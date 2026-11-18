/* Real compiled settings + installed MOSS ONNX CPU. Isolated QA gateway only.
 * No microphone, paid API or production settings changes. */
const assert = require('node:assert/strict'), fs = require('node:fs')
const { chromium } = require('../qa/node_modules/playwright')
const base = 'http://127.0.0.1:8875', out = 'E:/Dafeiyu/verification/moss-voices'
const report = { method: 'Real Edge + local CPU MOSS; controlled local LLM fixture; no mic or paid API', cases: [] }
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function wait(fn, label, timeout = 30000) {
  const end = Date.now() + timeout
  while (Date.now() < end) { if (await fn()) return; await delay(50) }
  throw Error(label)
}
async function api(path) { const r = await fetch(base + path); assert(r.ok, `${path}: ${r.status}`); return r.json() }
function wire(payload) { const raw = Buffer.from(payload), i = raw.indexOf('{"label"'); if (i >= 0) try { return JSON.parse(raw.subarray(i).toString()) } catch {} }
;(async () => {
  fs.mkdirSync(out, { recursive: true })
  await wait(async () => { try { return (await api('/api/health')).status === 'ok' } catch { return false } }, 'Gateway unavailable')
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
  await context.addInitScript(() => {
    window.__micCalls = 0
    navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('No microphone in voice catalog QA') }
  })
  const page = await context.newPage(), errors = [], received = [], sent = []
  let session
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', async r => { if (r.url().endsWith('/api/sessions') && r.request().method() === 'POST') session = (await r.json()).id })
  page.on('websocket', socket => {
    socket.on('framereceived', ({ payload }) => { const msg = wire(payload); if (msg) received.push(msg) })
    socket.on('framesent', ({ payload }) => { const msg = wire(payload); if (msg) sent.push(msg) })
  })
  const ready = () => page.waitForFunction(() => document.querySelector('.mic-btn')?.disabled === false, null, { timeout: 30000 })
  const openSettings = () => page.getByRole('button', { name: '设置', exact: true }).click()
  const picker = () => page.getByRole('combobox', { name: 'MOSS 内置音色', exact: true })
  async function check(name, fn) {
    console.log('CHECK', name)
    const detail = await fn()
    report.cases.push({ name, status: 'passed', detail }); console.log('PASS', name)
    fs.writeFileSync(out + '/browser.json', JSON.stringify(report, null, 2))
  }
  try {
    await page.goto(base); await ready(); await openSettings()
    const catalog = await api('/api/tts/voices')
    await check('dynamic grouped catalog matches installed model; no duplicate free-text field', async () => {
      await picker().waitFor(); await wait(() => picker().isEnabled(), 'Catalog select not enabled')
      const values = await picker().locator('option').evaluateAll(options => options.map(option => option.value))
      assert.deepEqual(values.filter(v => v !== 'default').sort(), catalog.voices.map(v => v.id).sort())
      assert.equal(catalog.voices.length, 18)
      assert.equal(await page.locator('label').filter({ hasText: /^声音$/ }).count(), 0)
      const groups = await picker().locator('optgroup').evaluateAll(items => items.map(item => ({ name: item.label, count: item.children.length })))
      assert.deepEqual(groups, [{ name: '中文男声', count: 3 }, { name: '中文女声', count: 3 }, { name: '英文男声', count: 3 }, { name: '英文女声', count: 2 }, { name: '日文女声', count: 7 }])
      assert((await picker().locator('option[value="default"]').innerText()).includes('Junhao'))
      await page.screenshot({ path: out + '/settings.png' })
      return { count: values.length - 1, groups, source: catalog.source }
    })
    await check('explicit non-default voice persists and produces real CPU audio and ACK', async () => {
      await picker().selectOption('Lingyu')
      await page.getByRole('button', { name: '保存设置', exact: true }).click(); await ready()
      assert.equal((await api('/api/settings')).voice, 'Lingyu')
      await page.reload(); await ready(); await openSettings()
      await wait(() => picker().isEnabled(), 'Catalog not ready after reload')
      assert.equal(await picker().inputValue(), 'Lingyu')
      await page.getByRole('button', { name: '关闭', exact: true }).click()
      const ei = received.length, si = sent.length
      await page.getByPlaceholder('说点什么，或开启语音...').fill('测试深夜电台音色')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await wait(() => received.slice(ei).some(e => e.type === 'error') || sent.slice(si).some(e => e.data?.t === 'voice.playback'), 'No actual playback ACK', 120000)
      assert.deepEqual(received.slice(ei).filter(e => e.type === 'error'), [])
      const ack = sent.slice(si).find(e => e.data?.t === 'voice.playback')?.data?.d
      assert(ack?.completed && ack.consumed_samples > 0)
      await wait(async () => (await api(`/api/sessions/${session}/messages`)).some(m => m.role === 'assistant' && m.content), 'No confirmed assistant history')
      return { voice: 'Lingyu', consumedSamples: ack.consumed_samples, sampleRate: ack.sample_rate, humanVoiceQuality: 'not evaluated' }
    })
    await check('catalog failure is visible, retains the saved voice and retries', async () => {
      await page.route('**/api/tts/voices', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '验收：清单暂不可用' }) }))
      await openSettings(); await page.getByRole('alert').filter({ hasText: '验收：清单暂不可用' }).waitFor()
      assert(await picker().isDisabled())
      assert.equal(await picker().inputValue(), 'Lingyu')
      await page.unroute('**/api/tts/voices')
      await page.getByRole('button', { name: '刷新 MOSS 音色', exact: true }).click()
      await wait(() => picker().isEnabled(), 'Retry did not recover the catalog')
      assert.equal(await picker().inputValue(), 'Lingyu')
      return { preserved: 'Lingyu', retryRecovered: true }
    })
    assert.equal(await page.evaluate(() => window.__micCalls), 0)
    assert.deepEqual(errors, [])
  } finally {
    report.pageErrors = errors
    fs.writeFileSync(out + '/browser.json', JSON.stringify(report, null, 2))
    await context.close(); await browser.close()
  }
  console.log(JSON.stringify(report, null, 2))
})().catch(error => { report.fatal = String(error); fs.writeFileSync(out + '/browser.json', JSON.stringify(report, null, 2)); console.error(error); process.exitCode = 1 })
