const http = require('node:http')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
// Optional QA dependency: playwright-core plus an installed Microsoft Edge.
const { chromium } = require('playwright-core')
;(async () => {
  const requests = [], bodies = [], errors = []
  const server = http.createServer((req, res) => {
    requests.push(req.url)
    if (req.url.startsWith('/dafeiyu/api/')) {
      let text = ''; req.on('data', c => text += c); req.on('end', () => {
        let value = {}
        if (req.url.endsWith('/settings')) {
          if (req.method === 'PUT') { value = JSON.parse(text); bodies.push(value) }
          else value = { harness_provider: 'dsh', memory_owner: 'dsh', llm_base_url: 'https://old.invalid', llm_model: 'OLDMODEL', llm_api_key: 'OLDSECRET', system_prompt: 'persona', tts_mode: 'api' }
        } else if (req.url.endsWith('/sessions')) value = req.method === 'POST' ? { id: 'test-session' } : []
        else if (req.url.endsWith('/status')) value = { llm: { ready: true, model: 'DSH Model' } }
        else if (req.url.endsWith('/owner/status')) value = { ready: false, enrolled: false, enabled: false }
        res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(value))
      }); return
    }
    if (req.url === '/') { res.setHeader('content-type','text/html'); res.end('<html data-theme="dsh"><body style="background:rgb(1,2,3)"><div id="host" style="width:640px;height:500px"></div></body></html>'); return }
    const file = path.join(__dirname, '..', 'dist-dsh', req.url.replace(/^\/dafeiyu\//, ''))
    if (!file.startsWith(path.join(__dirname,'..','dist-dsh')) || !fs.existsSync(file)) { res.statusCode = 404; res.end(); return }
    res.setHeader('content-type', file.endsWith('.js') ? 'application/javascript' : 'application/octet-stream'); res.end(fs.readFileSync(file))
  })
  server.on('upgrade', (req, socket) => { requests.push(req.url); socket.destroy() })
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve))
  const browser = await chromium.launch({ executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless:true, args:['--disable-gpu','--disable-webgl'] })
  try {
    const page = await browser.newPage()
    page.on('pageerror',e => errors.push(e.message))
    await page.addInitScript(() => {
      localStorage.setItem('avatar-model-url','')
      window.micCalls = 0
      window.audioContexts = []
      const NativeContext = window.AudioContext
      window.AudioContext = class extends NativeContext { constructor(...args) { super(...args); window.audioContexts.push(this) } }
      navigator.mediaDevices.getUserMedia = async () => { window.micCalls++; throw Error('Microphone forbidden in test') }
    })
    await page.goto(`http://127.0.0.1:${server.address().port}/`)
    await page.evaluate(async () => { window.pluginModule = await import('/dafeiyu/entry.js'); window.plugin = window.pluginModule.mountDafeiyu(document.querySelector('#host'), {harnessProvider:'dsh'}) })
    await page.waitForSelector('#host .app')
    assert.deepEqual(await page.locator('#host .app').evaluate(n => [n.clientWidth,n.clientHeight]),[640,500])
    assert.equal(await page.locator('#host .hud').evaluate(n => getComputedStyle(n).display),'none')
    await page.locator('#host').evaluate(n => n.style.width='1200px')
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#host').shadowRoot.querySelector('.hud')).display !== 'none')
    await page.locator('#host').evaluate(n => n.style.width='640px')
    assert.equal(await page.locator('html').getAttribute('data-theme'),'dsh')
    assert.equal(await page.locator('body').evaluate(n => getComputedStyle(n).backgroundColor),'rgb(1, 2, 3)')
    await page.getByRole('button',{name:'设置',exact:true}).click()
    await page.getByLabel('DSH 温度').waitFor()
    await page.getByLabel('口型声线').selectOption('local-vits')
    await page.waitForFunction(() => localStorage.getItem('lip-profile') === 'local-vits')
    assert.equal(await page.getByLabel('添加记忆',{exact:true}).count(),0)
    assert.equal(await page.getByText('OLDSECRET',{exact:false}).count(),0)
    assert.equal(await page.getByText('OLDMODEL',{exact:false}).count(),0)
    await page.getByRole('button',{name:'保存设置',exact:true}).click()
    await page.waitForFunction(() => !document.querySelector('#host').shadowRoot.querySelector('.settings-form'))
    assert(bodies.length)
    for (const field of ['llm_base_url','llm_model','llm_api_key','temperature','harness_provider','memory_owner']) assert(!(field in bodies[0]),field)
    assert.equal(bodies[0].system_prompt,'persona')
    await page.evaluate(() => plugin.setActive(false))
    await page.waitForFunction(() => audioContexts.every(c => c.state === 'closed'))
    assert.equal(await page.locator('#host .app').count(),0)
    const before = requests.length
    await page.waitForTimeout(1200)
    assert.equal(requests.length,before)
    await page.evaluate(() => { plugin.setActive(true); plugin.setActive(false); plugin.setActive(true) })
    await page.waitForSelector('#host .app')
    assert.equal(await page.evaluate(() => micCalls),0)
    await page.evaluate(() => { plugin.dispose(); plugin = pluginModule.mountDafeiyu(document.querySelector('#host')); plugin.dispose() })
    await page.waitForFunction(() => audioContexts.every(c => c.state === 'closed'))
    assert.equal(await page.locator('#host .app').count(),0)
    assert(!requests.some(p => p.includes('memories')))
    assert(!requests.some(p => p.startsWith('/api/') || p.startsWith('/ws/')))
    assert(requests.some(p => p.startsWith('/dafeiyu/ws/voice?')))
    assert(requests.some(p => p.startsWith('/dafeiyu/assets/audio-processor-')))
    assert(requests.some(p => p.startsWith('/dafeiyu/assets/local-vits-profile-')))
    assert.deepEqual(errors,[])
    console.log(JSON.stringify({shadow:true,dimensions:true,themeIsolated:true,memoryMasked:true,settingsFiltered:true,inactiveQuiet:true,remount:true,microphoneCalls:0,requests:requests.length}))
  } finally { await browser.close(); server.close() }
})().catch(e => { console.error(e); process.exitCode=1 })
