// Standalone UI acceptance: static build + mocked APIs, no models or paid calls.
const assert = require('node:assert/strict')
const http = require('node:http')
const fs = require('node:fs/promises')
const path = require('node:path')
const { chromium } = require('../../qa/node_modules/playwright')
const dist = path.resolve(__dirname, '../dist')
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.wasm': 'application/wasm' }
;(async () => {
  const server = http.createServer(async (req, res) => {
    try {
      const file = path.resolve(dist, '.' + new URL(req.url, 'http://localhost').pathname)
      if (!file.startsWith(dist + path.sep) && file !== dist) { res.writeHead(403).end(); return }
      const target = file === dist ? path.join(dist, 'index.html') : file
      res.setHeader('content-type', types[path.extname(target)] || 'application/octet-stream')
      res.end(await fs.readFile(target))
    } catch { res.writeHead(404).end() }
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${server.address().port}`
  let browser
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--disable-gpu', '--mute-audio'] })
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addInitScript(() => {
      localStorage.setItem('avatar-model-url', '')
      window.__micCalls = 0
      navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('Microphone forbidden in UI test') }
    })
    let settings = { tts_mode: 'legacy', tts_api_key_set: false, api_key_set: false }
    const writes = [], errors = [], unexpected = []
    await context.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin !== origin) { unexpected.push(url.origin); await route.abort(); return }
      if (!url.pathname.startsWith('/api/')) { await route.continue(); return }
      let payload
      if (url.pathname === '/api/settings') {
        if (route.request().method() === 'PUT') {
          const update = route.request().postDataJSON(); writes.push(update)
          assert(!('tts_api_key_set' in update)); assert(!('api_key_set' in update))
          settings = { ...settings, ...update, tts_api_key_set: update.clear_tts_api_key ? false : Boolean(update.tts_api_key || settings.tts_api_key_set) }
          delete settings.tts_api_key; delete settings.llm_api_key; delete settings.clear_tts_api_key
        }
        payload = settings
      } else if (url.pathname === '/api/status') payload = { tts: { mode: settings.tts_mode, provider: settings.tts_mode === 'api' ? 'OpenAI-compatible' : 'local CPU', detail: '配置状态', ready: false } }
      else if (url.pathname === '/api/sessions') payload = route.request().method() === 'POST' ? { id: 'ui-test' } : []
      else if (url.pathname === '/api/memories') payload = []
      else if (url.pathname === '/api/voice/config') payload = { engine: 'pipecat', endpoint: '/ws/voice', input_sample_rate: 16000, output_sample_rate: 24000 }
      else if (url.pathname === '/api/voice/owner/status') payload = { enabled: false, ready: false, enrolled: false }
      else throw Error(`Unexpected API in UI test: ${url.pathname}`)
      await route.fulfill({ json: payload })
    })
    await context.routeWebSocket('**/ws/voice*', socket => socket.close())
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(origin, { waitUntil: 'networkidle' })
    const open = () => page.getByRole('button', { name: '设置', exact: true }).click()
    await open()
    const mode = page.getByLabel('语音合成模式', { exact: false })
    assert.deepEqual(await mode.locator('option').evaluateAll(options => options.map(option => option.value)), ['auto', 'cpu', 'gpu', 'api', 'legacy'])
    for (const value of ['auto', 'cpu', 'gpu', 'legacy']) {
      await mode.selectOption(value)
      assert.equal(await page.getByLabel('TTS API 密钥', { exact: true }).count(), 0)
    }
    await mode.selectOption('api')
    await page.getByLabel('TTS API 基础地址', { exact: false }).fill('https://provider.test/v1')
    await page.getByLabel('TTS 模型', { exact: true }).fill('custom-model')
    await page.getByLabel('API 音色', { exact: true }).fill('custom-voice')
    await page.getByLabel('TTS API 密钥', { exact: true }).fill('qa-placeholder-key')
    await page.getByRole('button', { name: '保存设置' }).click()
    await page.getByRole('button', { name: '保存设置' }).waitFor({ state: 'hidden' })
    assert.equal(writes.at(-1).tts_mode, 'api')
    assert.equal(writes.at(-1).tts_api_key, 'qa-placeholder-key')
    await open()
    assert.equal(await page.getByLabel('TTS API 密钥', { exact: true }).inputValue(), '')
    await page.getByLabel('语音合成模式', { exact: false }).selectOption('cpu')
    await page.getByRole('button', { name: '保存设置' }).click()
    await page.getByRole('button', { name: '保存设置' }).waitFor({ state: 'hidden' })
    assert.equal(writes.at(-1).tts_mode, 'cpu')
    assert.equal(writes.at(-1).tts_api_key, '')
    assert.equal(settings.tts_api_key_set, true)
    await open()
    await page.getByLabel('语音合成模式', { exact: false }).selectOption('api')
    await page.getByLabel('保存时清除 TTS 密钥', { exact: true }).check()
    await page.getByRole('button', { name: '保存设置' }).click()
    await page.getByRole('button', { name: '保存设置' }).waitFor({ state: 'hidden' })
    assert.equal(writes.at(-1).clear_tts_api_key, true)
    assert.equal(settings.tts_api_key_set, false)
    assert.equal(await page.evaluate(() => window.__micCalls), 0)
    assert.deepEqual(errors, [])
    assert.deepEqual(unexpected, [])
    console.log('PASS: five mode options, API save/redaction, CPU switch, explicit key clear, no microphone/external requests')
  } finally {
    if (browser) await browser.close()
    await new Promise(resolve => server.close(resolve))
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
