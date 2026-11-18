/* Real Edge/Pipecat/playback; synthetic VAD/ASR/decisions/LLM/tone. No mic/cloud. */
const assert = require('node:assert/strict'), fs = require('node:fs')
const { chromium } = require('../qa/node_modules/playwright')
const base = 'http://127.0.0.1:8875', provider = 'http://127.0.0.1:8874'
const out = process.env.DAFEIYU_QA_OUT || 'E:/Dafeiyu/verification/systemone-initiative'
const report = { method: 'Real Edge and Pipecat; synthetic speech frames, fixture ASR/SystemOne/LLM/tone. Not acoustic or live-model evidence.', cases: [] }
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function wait(predicate, label, timeout = 15000) { const end = Date.now() + timeout; while (Date.now() < end) { if (await predicate()) return; await delay(50) } throw Error(label) }
async function request(url, body, method = 'POST') { const response = await fetch(url, body === undefined ? {} : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); assert(response.ok, `${url}: ${response.status}`); return response.json() }
const feed = action => request(provider + '/test/initiative', { action })
const mode = (initiative_mode, mode = 'success') => request(provider + '/test/decisions', { initiative_mode, mode }, 'PUT')
function wire(payload) { const raw = Buffer.from(payload), index = raw.indexOf('{"label"'); if (index >= 0) try { return JSON.parse(raw.subarray(index).toString()) } catch {} }

;(async () => {
  fs.mkdirSync(out, { recursive: true })
  // Synthetic capture bypasses the real mic gesture which normally resumes
  // output. Allow fixture tone autoplay without requesting a real microphone.
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } })
  await context.addInitScript(() => { window.__micCalls = 0; navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('Microphone forbidden in synthetic fixture QA') } })
  const page = await context.newPage(), errors = [], received = [], sent = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('websocket', socket => {
    socket.on('framereceived', ({ payload }) => { const value = wire(payload); if (value) received.push(value) })
    socket.on('framesent', ({ payload }) => { const value = wire(payload); if (value) sent.push(value) })
  })
  const ready = () => page.waitForFunction(() => document.querySelector('.mic-btn')?.disabled === false)
  const settings = () => page.getByRole('button', { name: '设置', exact: true }).click()
  const close = () => page.getByRole('button', { name: '关闭', exact: true }).click()
  async function check(name, run) { await run(); report.cases.push({ name, status: 'passed' }); fs.writeFileSync(out + '/browser.json', JSON.stringify(report, null, 2)); console.log('PASS', name) }
  try {
    await request(base + '/api/settings', { systemone_enabled: false, systemone_initiative_enabled: false,
      systemone_provider: 'ark', systemone_ark_model: 'doubao-seed-2-1-lite-260915',
      clear_systemone_ark_api_key: true, clear_systemone_api_key: true }, 'PUT')
    for (const session of await request(base + '/api/sessions')) await request(base + `/api/sessions/${session.id}`, {}, 'DELETE')
    await mode('strong')
    await page.goto(base); await ready()
    await check('initiative is opt-in, saves/reloads through real settings API and never opens microphone', async () => {
      await settings()
      assert(!await page.getByRole('checkbox', { name: '允许助手主动接话', exact: true }).isChecked())
      assert(await page.getByLabel('主动开口意愿阈值', { exact: true }).isVisible())
      assert(await page.getByLabel('主动接话最大回复长度（字符）', { exact: true }).isVisible())
      await page.getByLabel('方舟 API Key', { exact: true }).fill('initiative-fixture-key')
      await page.getByLabel('启用 System One 判断', { exact: true }).check()
      await page.getByRole('checkbox', { name: '允许助手主动接话', exact: true }).check()
      await page.getByRole('button', { name: '保存设置', exact: true }).click(); await ready()
      const saved = await request(base + '/api/settings')
      assert(saved.systemone_initiative_enabled && saved.systemone_initiative_threshold === .9)
      assert(!JSON.stringify(saved).includes('initiative-fixture-key'))
      await page.reload(); await ready(); await settings()
      assert(await page.getByRole('checkbox', { name: '允许助手主动接话', exact: true }).isChecked())
      await page.screenshot({ path: out + '/settings.png', fullPage: true }); await close()
      assert.equal(await page.evaluate(() => window.__micCalls), 0)
    })
    await check('numeric settings validate, reset only initiative drafts, persist and reload all custom values', async () => {
      await settings()
      const values = [
        ['主动开口意愿阈值', 'systemone_initiative_threshold', .94],
        ['至少聆听（毫秒）', 'systemone_initiative_min_speech_ms', 2000],
        ['两次主动接话最短间隔（秒）', 'systemone_initiative_cooldown_s', 30],
        ['主动接话最大回复长度（字符）', 'systemone_initiative_max_reply_chars', 24],
        ['等待保护概率阈值', 'systemone_initiative_wait_threshold', .1],
        ['再次判断间隔（毫秒）', 'systemone_initiative_probe_interval_ms', 2000],
        ['每段连续发言最多判断次数', 'systemone_initiative_max_probes', 5],
      ]
      await page.getByText('主动接话高级参数', { exact: true }).click()
      let writes = 0
      const observe = request => { if (request.method() === 'PUT' && request.url() === base + '/api/settings') writes++ }
      page.on('request', observe)
      const count = page.getByLabel('每段连续发言最多判断次数', { exact: true })
      for (const invalid of ['', '0', '1.5']) {
        await count.fill(invalid)
        await page.getByText('主动接话高级参数', { exact: true }).click()
        await page.getByRole('button', { name: '保存设置', exact: true }).click()
        assert(await count.isVisible()) // Validation reopens a collapsed details.
        assert.equal(await count.evaluate(el => el.validity.valid), false)
        assert.equal(writes, 0)
        assert.equal((await request(base + '/api/settings')).systemone_initiative_max_probes, 3)
      }
      page.off('request', observe)
      await page.getByRole('button', { name: '恢复主动接话默认参数', exact: true }).click()
      assert.equal(await count.inputValue(), '3')
      assert(await page.getByRole('checkbox', { name: '允许助手主动接话', exact: true }).isChecked())
      assert(await page.getByRole('checkbox', { name: '启用 System One 判断', exact: true }).isChecked())
      assert.equal(await page.getByLabel('方舟 API Key', { exact: true }).inputValue(), '')
      for (const [label, , value] of values) await page.getByLabel(label, { exact: true }).fill(String(value))
      await page.getByRole('button', { name: '保存设置', exact: true }).click(); await ready()
      const saved = await request(base + '/api/settings')
      for (const [, key, value] of values) assert.equal(saved[key], value)
      assert(saved.systemone_ark_api_key_set && saved.systemone_initiative_enabled)
      await page.reload(); await ready(); await settings()
      await page.getByText('主动接话高级参数', { exact: true }).click()
      for (const [label, , value] of values) assert.equal(await page.getByLabel(label, { exact: true }).inputValue(), String(value))
      await page.getByLabel('主动开口意愿阈值', { exact: true }).scrollIntoViewIfNeeded()
      await page.screenshot({ path: out + '/custom-settings.png', fullPage: true })
      await close()
      assert.equal(await page.evaluate(() => window.__micCalls), 0)
    })
    await check('strong desire reaches brief LLM/TTS playback with one contribution per live utterance', async () => {
      await mode('strong')
      const start = received.length, acks = sent.length
      await feed('start'); await feed('probe')
      await wait(() => received.slice(start).some(value => value.data?.type === 'voice.initiative' && value.data.status === 'accepted'), 'No accepted initiative diagnostic')
      await wait(() => sent.slice(acks).some(value => value.data?.t === 'voice.playback' && value.data.d?.completed === true), 'No actual tone playback receipt')
      const before = (await request(provider + '/test/decisions')).initiative_calls
      await feed('probe'); await delay(300)
      assert.equal((await request(provider + '/test/decisions')).initiative_calls, before)
      await settings(); await page.getByText(/主动接话：豆包 System One · 已请求及时共情，不代表已经播放/).waitFor()
      await page.screenshot({ path: out + '/accepted.png', fullPage: true }); await close()
      const requests = (await request(provider + '/test/requests')).filter(value => Array.isArray(value.messages))
      assert(requests.some(value => value.messages.some(message => message.role === 'system' && message.content.includes('用户仍在说话'))))
      assert(requests.some(value => value.messages.some(message => message.role === 'system' && message.content.includes('最多24个字符（含标点）'))))
    })
    await check('the complete user utterance is preserved and gets an ordinary reply, partial is not persisted', async () => {
      const acks = sent.length
      await feed('stop'); await feed('final')
      await wait(() => sent.slice(acks).some(value => value.data?.t === 'voice.playback' && value.data.d?.completed), 'No regular reply after the full transcript')
      const sessions = await request(base + '/api/sessions')
      const messages = (await Promise.all(sessions.map(value => request(base + `/api/sessions/${value.id}/messages`)))).flat()
      const users = messages.filter(value => value.role === 'user')
      assert.equal(users.length, 1)
      assert(users[0].content.endsWith('后来我的朋友来安慰我，现在已经好多了。'))
      const before = (await request(provider + '/test/decisions')).initiative_calls
      await feed('start'); await feed('probe'); await delay(300); await feed('stop')
      assert.equal((await request(provider + '/test/decisions')).initiative_calls, before)
    })
    await check('low desire keeps listening and does not call the reply model', async () => {
      await mode('wait'); await page.reload(); await ready()
      const start = received.length, before = (await request(provider + '/test/requests')).length
      await feed('start'); await feed('probe')
      await wait(() => received.slice(start).some(value => value.data?.type === 'voice.initiative' && value.data.status === 'waiting'), 'No waiting diagnostic')
      assert.equal((await request(provider + '/test/requests')).length, before)
      assert(!received.slice(start).some(value => value.data?.type === 'voice.playback.start'))
      await feed('stop')
    })
    await check('finishing while decision is pending prevents late speech', async () => {
      await mode('strong', 'timeout'); await page.reload(); await ready()
      const start = received.length, before = (await request(provider + '/test/requests')).length
      await feed('start'); await feed('probe'); await delay(200); await feed('stop'); await delay(1500)
      assert(!received.slice(start).some(value => value.data?.type === 'voice.initiative' && value.data.status === 'accepted'))
      assert.equal((await request(provider + '/test/requests')).length, before)
      assert(!received.slice(start).some(value => value.data?.type === 'voice.playback.start'))
      await mode('strong')
    })
    assert.equal(await page.evaluate(() => window.__micCalls), 0)
    assert.deepEqual(errors, [])
    report.microphoneCalls = 0
  } finally {
    report.pageErrors = errors
    fs.writeFileSync(out + '/browser.json', JSON.stringify(report, null, 2))
    await context.close(); await browser.close()
  }
  console.log(JSON.stringify(report, null, 2))
})().catch(error => { report.fatal = String(error); fs.writeFileSync(out + '/browser.json', JSON.stringify(report, null, 2)); console.error(error); process.exitCode = 1 })
