/* Probe the everyday gateway with normal browser autoplay policy; no cloud call. */
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext(), page = await context.newPage(), errors = []
  const base = 'http://127.0.0.1:8765'; let session
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', async response => { if (response.url().endsWith('/api/sessions') && response.request().method() === 'POST') session = (await response.json()).id })
  try {
    const config = await (await context.request.get(base + '/api/voice/config')).json()
    assert.equal(config.engine, 'pipecat')
    const settings = await (await context.request.get(base + '/api/settings')).json()
    await page.goto(base, {waitUntil:'networkidle'})
    await page.waitForFunction(() => document.querySelector('.top-status')?.textContent?.includes('已连接') || document.querySelector('.topbar')?.textContent?.includes('已连接'), null, {timeout:15000}).catch(async () => {
      // A filled composer exposes connection readiness without activating audio.
      await page.getByPlaceholder('说点什么，或开启语音...').fill('连接自检')
      await page.waitForFunction(() => !document.querySelector('.send-btn')?.disabled)
    })
    if (!settings.api_key_set) {
      await page.getByPlaceholder('说点什么，或开启语音...').fill('连接自检')
      await page.getByRole('button', {name:'发送',exact:true}).click()
      await page.getByRole('status').filter({hasText:'请先在设置中填写 DeepSeek API 密钥'}).waitFor({timeout:15000})
      assert.equal(await page.getByRole('button',{name:'停止',exact:true}).count(),0,'provider error left the UI busy')
    }
    assert.deepEqual(errors,[])
    const out = path.resolve(__dirname,'../artifacts/pipecat-acceptance'); fs.mkdirSync(out,{recursive:true})
    const result = {engine:config.engine,version:config.version,normal_autoplay_handshake:true,missing_key_error:!settings.api_key_set,cloud_called:false,errors}
    fs.writeFileSync(path.join(out,'primary.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))
  } finally { await context.close(); if(session) await fetch(base+'/api/sessions/'+session,{method:'DELETE'}).catch(()=>{}); await browser.close() }
})().catch(error => {console.error(error);process.exitCode=1})
