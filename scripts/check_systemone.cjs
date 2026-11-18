/* Real Edge and Pipecat, controlled SystemOne/LLM/PCM fixtures. No cloud or microphone. */
const assert = require('node:assert/strict'), fs = require('node:fs')
const { chromium } = require('../qa/node_modules/playwright')
const out = 'E:/Dafeiyu/verification/systemone-ark', base = 'http://127.0.0.1:8875'
const report = { method: 'Real browser, isolated Pipecat; simulated SystemOne + LLM + tone PCM; no live inference claims', cases: [] }
const delay = ms => new Promise(r => setTimeout(r, ms))
async function wait(fn, label, timeout = 25000) { const end = Date.now() + timeout; while (Date.now() < end) { if (await fn()) return; await delay(50) } throw Error(label) }
async function api(path, init) { const r = await fetch(base + path, init); assert(r.ok, `${path}: ${r.status}`); return r.json() }
async function mode(value) { await fetch('http://127.0.0.1:8874/test/decisions', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: value }) }) }
function wire(payload) { const raw = Buffer.from(payload), i = raw.indexOf('{"label"'); if (i >= 0) try { return JSON.parse(raw.subarray(i).toString()) } catch {} }
;(async () => {
  fs.mkdirSync(out, { recursive: true })
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
  await context.addInitScript(() => {
    window.__micCalls = 0
    navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('Microphone forbidden in fixture QA') }
    let pixi
    Object.defineProperty(window, 'PIXI', { configurable: true, get: () => pixi, set: value => {
      pixi = value
      const original = value.Container.prototype.addChild
      value.Container.prototype.addChild = function (...children) { for (const child of children) if (child.internalModel) window.__qaAvatar = child; return original.apply(this, children) }
    } })
  })
  const page = await context.newPage(), errors = [], messages = [], sent = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('websocket', socket => {
    socket.on('framereceived', ({ payload }) => { const msg = wire(payload); if (msg) messages.push(msg) })
    socket.on('framesent', ({ payload }) => { const msg = wire(payload); if (msg) sent.push(msg) })
  })
  const ready = () => page.waitForFunction(() => document.querySelector('.mic-btn')?.disabled === false)
  const settings = () => page.getByRole('button', { name: '设置', exact: true }).click()
  const close = () => page.getByRole('button', { name: '关闭', exact: true }).click()
  const submit = async () => { await page.getByPlaceholder('说点什么，或开启语音...').fill('测试语义情绪'); await page.getByRole('button', { name: '发送', exact: true }).click() }
  async function check(name, fn) { await fn(); report.cases.push({ name, status: 'passed' }); fs.writeFileSync(out + '/browser.json', JSON.stringify(report, null, 2)); console.log('PASS', name) }
  try {
    await page.goto(base); await ready()
    await check('settings opt-in, key redaction, reload and saved-config test', async () => {
      await settings()
      assert.equal(await page.getByLabel('启用 System One 判断', { exact: true }).isChecked(), false)
      assert.equal(await page.getByLabel('判断供应商', { exact: true }).inputValue(), 'ark')
      await page.getByLabel('方舟 API Key', { exact: true }).fill('systemone-ark-fixture-key')
      await page.getByLabel('启用 System One 判断', { exact: true }).check()
      await page.getByRole('button', { name: '保存设置', exact: true }).click(); await ready()
      const saved = await api('/api/settings')
      assert(saved.systemone_enabled && saved.systemone_ark_api_key_set && saved.systemone_provider === 'ark')
      assert(!JSON.stringify(saved).includes('systemone-ark-fixture-key'))
      await page.reload(); await ready(); await settings()
      assert.equal(await page.getByLabel('方舟 API Key', { exact: true }).inputValue(), '')
      assert(await page.getByLabel('启用 System One 判断', { exact: true }).isChecked())
      await page.getByRole('button', { name: '测试已保存配置（一次云端调用）' }).click()
      await page.getByText(/豆包 System One · 判断成功 · .*文本接口测试/).waitFor()
      await page.screenshot({ path: out + '/settings.png', fullPage: true }); await close()
    })
    await check('model emotion and real Live2D gesture follow playback, then stop clears them', async () => {
      await submit()
      await wait(async () => (await page.locator('.affect small').innerText()) === '豆包 System One', 'No applied model behavior')
      assert.equal(await page.locator('.affect strong').innerText(), '难过')
      await page.waitForFunction(() => window.__qaAvatar?.internalModel.coreModel.getParameterValueById('Movement2') > .5)
      assert(messages.some(m => m.data?.type === 'voice.behavior' && m.data.source === 'doubao-systemone'))
      await page.screenshot({ path: out + '/behavior.png' })
      await page.getByRole('button', { name: '停止', exact: true }).click()
      await wait(async () => (await page.locator('.affect small').innerText()) === '对话自动', 'Stop did not clear behavior')
      await page.waitForFunction(() => window.__qaAvatar?.internalModel.coreModel.getParameterValueById('Movement2') < .05)
      assert(sent.some(m => m.data?.t === 'voice.stop'))
    })
    await check('timeout falls back while audio still completes', async () => {
      await mode('timeout'); const before = messages.length, acks = sent.length
      await submit()
      await wait(() => messages.slice(before).some(m => m.data?.type === 'voice.behavior' && m.data.source === 'rules' && m.data.reason === 'timeout'), 'No timeout fallback')
      await wait(() => sent.slice(acks).some(m => m.data?.t === 'voice.playback' && m.data.d?.completed), 'No completed playback during fallback')
      assert(!messages.slice(before).some(m => m.type === 'error'))
      await mode('success')
    })
    await check('provider switches isolate credentials; unsaved model cannot trigger a misleading test', async () => {
      await settings()
      const test = page.getByRole('button', { name: '测试已保存配置（一次云端调用）' })
      await page.getByLabel('方舟模型 / 推理接入点 ID', { exact: true }).fill('ep-unsaved-test')
      assert(await test.isDisabled())
      await page.getByLabel('判断供应商', { exact: true }).selectOption('tokentosea')
      assert(await test.isDisabled())
      assert.equal(await page.getByLabel('启用 System One 判断', { exact: true }).isChecked(), false)
      assert.equal(await page.getByLabel('TokenToSea API Key', { exact: true }).inputValue(), '')
      await page.getByLabel('TokenToSea API Key', { exact: true }).fill('clef-independent-fixture-key')
      await page.getByLabel('启用 System One 判断', { exact: true }).check()
      await page.getByRole('button', { name: '保存设置', exact: true }).click(); await ready(); await settings()
      await test.click(); await page.getByText(/Clef Omni · 判断成功/).waitFor()
      const saved = await api('/api/settings')
      assert(saved.systemone_api_key_set && saved.systemone_ark_api_key_set)
      assert(!JSON.stringify(saved).includes('fixture-key'))
      await mode('region'); await test.click()
      await page.getByText(/供应商地区限制，并非连接超时/).waitFor()
      await mode('success')
      await page.getByLabel('判断供应商', { exact: true }).selectOption('ark')
      await page.getByLabel('方舟模型 / 推理接入点 ID', { exact: true }).fill('doubao-seed-2-1-lite-260915')
      await page.getByRole('button', { name: '保存设置', exact: true }).click(); await ready()
    })
    await check('feature off restores rules without model requests', async () => {
      await settings(); await page.getByLabel('启用 System One 判断', { exact: true }).uncheck()
      await page.getByRole('button', { name: '保存设置', exact: true }).click(); await ready()
      const count = (await (await fetch('http://127.0.0.1:8874/test/decisions')).json()).calls, acks = sent.length
      await submit()
      await wait(() => sent.slice(acks).some(m => m.data?.t === 'voice.playback' && m.data.d?.completed), 'No playback with feature off')
      assert.equal((await (await fetch('http://127.0.0.1:8874/test/decisions')).json()).calls, count)
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
