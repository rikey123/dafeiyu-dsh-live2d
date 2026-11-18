/* Real browser handshake, profile reconnect and explicit WASM failure fallback.
 * Uses primary loopback UI but never writes backend settings or opens a mic.
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8765'
const out = path.resolve(__dirname, '../artifacts/lip-profiles')
;(async () => {
  fs.mkdirSync(out, { recursive: true })
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const sessions = new Set(), results = []
  try {
    for (const fallback of [false, true]) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
      const page = await context.newPage(), errors = []
      await context.addInitScript(() => { window.__micCalls = 0; navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('No microphone in profile test') } })
      if (fallback) await page.route('**/assets/wlipsync-*.wasm', route => route.abort())
      page.on('pageerror', e => errors.push(e.message))
      page.on('response', async response => { if (response.url().endsWith('/api/sessions') && response.request().method() === 'POST') sessions.add((await response.json()).id) })
      await page.goto(base, { waitUntil: 'networkidle' })
      await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
      await page.getByRole('button', { name: '发送', exact: true }).waitFor()
      await page.getByText('本地服务已连接', { exact: true }).waitFor({ timeout: 30000 })
      await page.getByRole('button', { name: '设置', exact: true }).first().click()
      await page.getByText(fallback ? /口型：音量口型回退/ : /口型：wLipSync 元音口型 · 通用元音模板/).waitFor({ timeout: 15000 })
      if (!fallback) {
        await page.getByLabel('口型声线', { exact: true }).selectOption('airi')
        await page.getByText(/口型：wLipSync 元音口型 · 通用元音模板/).waitFor({ timeout: 15000 })
        await page.getByLabel('口型声线', { exact: true }).selectOption('local-vits')
        await page.getByText(/口型：wLipSync 元音口型 · 旧 VITS 专用/).waitFor({ timeout: 15000 })
      }
      assert.equal(await page.evaluate(() => window.__micCalls), 0)
      assert.deepEqual(errors, [])
      results.push({ name: fallback ? 'WASM failure is visible and handshake still works' : 'normal autoplay handshake and both profile reconnects without mic', passed: true })
      await page.screenshot({ path: path.join(out, fallback ? 'fallback.png' : 'profiles.png') })
      await context.close()
    }
    const settings = await (await fetch(base + '/api/settings')).json()
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ results, api_key_set: settings.api_key_set, limitations: 'No cloud conversation or physical microphone/speaker measurement.' }, null, 2))
    console.log(JSON.stringify({ results, api_key_set: settings.api_key_set }, null, 2))
  } finally {
    await browser.close()
    for (const id of sessions) await fetch(base + '/api/sessions/' + id, { method: 'DELETE' }).catch(() => {})
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
