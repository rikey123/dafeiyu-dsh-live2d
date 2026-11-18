/* Browser regression checks. Synthetic silence tests lifecycle, not hardware capture. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8765'

;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-fake-ui-for-media-stream'] })
  const context = await browser.newContext()
  const errors = [], checks = []
  await context.addInitScript(() => {
    const nativeCapture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    const nativeEnumerate = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices)
    const NativeContext = window.AudioContext
    const test = window.__micTest = { mode: 'native', calls: [], tracks: [], contexts: [], devices: null, failWorklet: false, nativeError: null }
    window.AudioContext = class extends NativeContext {
      constructor(options) {
        super(options)
        if (options?.sampleRate === 16000) {
          test.contexts.push(this)
          if (test.failWorklet) this.audioWorklet.addModule = async () => { throw new Error('Injected worklet failure') }
        }
      }
    }
    navigator.mediaDevices.enumerateDevices = () => test.devices ? Promise.resolve(test.devices) : nativeEnumerate()
    navigator.mediaDevices.getUserMedia = async constraints => {
      test.calls.push(constraints)
      if (test.mode === 'native') {
        try { return await nativeCapture(constraints) }
        catch (error) { test.nativeError = { name: error.name, message: error.message }; throw error }
      }
      if (test.mode !== 'silence') throw new DOMException('Injected device failure', test.mode)
      const source = new NativeContext(), destination = source.createMediaStreamDestination()
      test.tracks.push(...destination.stream.getTracks())
      // A destination with no source produces silence and cannot initiate an LLM turn.
      test.sourceContext = source
      return destination.stream
    }
  })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  const mic = () => page.getByRole('button', { name: '开启语音', exact: true })
  const listening = () => page.getByRole('button', { name: '正在聆听', exact: true })
  try {
    await page.goto(base, { waitUntil: 'networkidle' })
    await mic().waitFor()
    await page.waitForFunction(() => !document.querySelector('.mic-btn')?.disabled)
    assert.equal(await page.evaluate(() => window.__micTest.calls.length), 0, 'page load must not acquire a microphone')
    await mic().click()
    await page.waitForFunction(() => window.__micTest.nativeError || document.querySelector('.mic-btn.listening'))
    const native = await page.evaluate(async () => ({ error: window.__micTest.nativeError, devices: (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput').map(d => d.label) }))
    if (native.error) {
      await page.getByText(new RegExp(`麦克风启动失败：.*${native.error.name}`)).waitFor()
    } else {
      await listening().click()
    }
    checks.push({ nativeHardware: native })
    for (const [code, hint] of [['NotAllowedError', '访问被拒绝'], ['NotReadableError', '独占设备'], ['OverconstrainedError', '重新选择'], ['NotFoundError', '未找到可用麦克风']]) {
      const before = await page.evaluate(code => { window.__micTest.mode = code; return window.__micTest.calls.length }, code)
      await mic().click()
      await page.getByText(new RegExp(`麦克风启动失败：.*${hint}.*${code}`)).waitFor()
      assert.equal(await page.evaluate(() => window.__micTest.calls.length), before + 1, 'device failures must not cause hidden acquisition retries')
      checks.push({ errorCode: code, passed: true })
    }
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await page.evaluate(() => {
      window.__micTest.devices = [{ kind: 'audioinput', deviceId: 'test-usb', groupId: 'test', label: '测试 USB 麦克风' }]
      navigator.mediaDevices.dispatchEvent(new Event('devicechange'))
    })
    const select = page.getByRole('combobox', { name: /^麦克风/ })
    await page.waitForFunction(() => [...document.querySelectorAll('option')].some(option => option.value === 'test-usb'))
    await select.selectOption('test-usb')
    await page.getByRole('button', { name: '刷新麦克风列表', exact: true }).click()
    // The page drawer must be closed before using its microphone control.
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.evaluate(() => { window.__micTest.mode = 'silence' })
    await mic().click(); await listening().waitFor()
    assert.equal(await page.evaluate(() => window.__micTest.calls.at(-1).audio.deviceId.exact), 'test-usb')
    await listening().click(); await mic().waitFor()
    assert(await page.evaluate(() => window.__micTest.tracks.every(t => t.readyState === 'ended') && window.__micTest.contexts.every(c => c.state === 'closed')))
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await select.selectOption('')
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.evaluate(() => { window.__micTest.failWorklet = true })
    await mic().click()
    await page.getByText(/麦克风启动失败：.*audioWorklet/).waitFor()
    assert(await page.evaluate(() => window.__micTest.tracks.every(t => t.readyState === 'ended') && window.__micTest.contexts.every(c => c.state === 'closed')))
    await page.evaluate(() => { window.__micTest.failWorklet = false })
    await mic().click(); await listening().waitFor()
    assert.equal(await page.evaluate(() => window.__micTest.calls.at(-1).audio.deviceId), undefined, 'system default must not reuse the previously selected USB ID')
    await listening().click(); await mic().waitFor()
    assert(await page.evaluate(() => window.__micTest.tracks.every(t => t.readyState === 'ended') && window.__micTest.contexts.every(c => c.state === 'closed')))
    checks.push({ syntheticLifecycle: 'device change, explicit selection, disable, failed worklet cleanup, retry, system default', passed: true })
    assert.deepEqual(errors, [])
    const output = process.env.MIC_CHECK_OUTPUT
    if (output) fs.writeFileSync(output, JSON.stringify({ checks, pageErrors: errors }, null, 2))
    console.log(JSON.stringify({ checks, pageErrors: errors }, null, 2))
  } finally { await context.close(); await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
