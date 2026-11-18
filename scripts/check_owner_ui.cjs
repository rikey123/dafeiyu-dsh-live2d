/* Called by check_owner_voice.py against temporary profile/settings only. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = process.env.VOICE_TEST_URL
assert(base === 'http://127.0.0.1:8885', 'owner UI QA requires the isolated owner gateway')
const out = path.resolve(__dirname, '../artifacts/audio-engineering')
;(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',`--use-file-for-fake-audio-capture=${path.join(out,'enrollment-fixture.wav')}`]})
  const context = await browser.newContext({permissions:['microphone'],viewport:{width:1440,height:1000}})
  await context.addInitScript(() => {
    window.__streams = [];window.__calls = 0
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async constraints => {window.__calls++;const stream=await original(constraints);window.__streams.push(stream);return stream}
  })
  const page = await context.newPage(), errors = [], enrollments = []
  let session
  page.on('pageerror',e=>errors.push(e.message))
  page.on('response',async response=>{
    if(response.url().endsWith('/api/sessions') && response.request().method()==='POST')session=(await response.json()).id
    if(response.url().endsWith('/api/voice/owner/enroll'))enrollments.push({status:response.status(),body:await response.json()})
  })
  try {
    await page.goto(base,{waitUntil:'networkidle'})
    await page.getByRole('button',{name:'设置',exact:true}).first().click()
    await page.getByText('尚未录入',{exact:false}).waitFor()
    const toggle=page.getByRole('checkbox',{name:'仅回应本人声音'})
    assert.equal(await toggle.isChecked(),false);assert.equal(await toggle.isDisabled(),true)
    assert.equal(await page.evaluate(()=>window.__calls),0)
    for(let index=1;index<=2;index++) {
      await page.getByRole('button',{name:'录制一段',exact:true}).click()
      await page.getByRole('button',{name:'完成录音',exact:true}).waitFor()
      await page.waitForTimeout(7500)
      await page.getByRole('button',{name:'完成录音',exact:true}).click()
      await page.getByRole('button',{name:`提交 ${index} 段`,exact:true}).waitFor()
      await page.waitForFunction(()=>window.__streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')))
    }
    await page.getByRole('button',{name:'提交 2 段',exact:true}).click()
    await page.getByText('本人声音已录入。',{exact:true}).waitFor({timeout:30000})
    assert.equal(enrollments.at(-1)?.status,200,JSON.stringify(enrollments))
    await toggle.click();await page.waitForFunction(async()=> (await (await fetch('/api/settings')).json()).owner_voice_only===true)
    await page.waitForFunction(()=>document.querySelector('.motion-setting input[type="checkbox"]')?.checked === true)
    await page.waitForTimeout(600)
    assert.equal(await page.evaluate(()=>window.__calls),2,'reconnect unexpectedly acquired the mic')
    await toggle.click();await page.waitForFunction(async()=> (await (await fetch('/api/settings')).json()).owner_voice_only===false)
    await page.waitForTimeout(600)
    // Verify cleanup when the settings panel closes during an active recording.
    await page.getByRole('button',{name:'录制一段',exact:true}).click()
    await page.getByRole('button',{name:'完成录音',exact:true}).waitFor()
    await page.getByRole('button',{name:'关闭',exact:true}).click()
    await page.waitForFunction(()=>window.__streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')))
    await page.getByRole('button',{name:'设置',exact:true}).first().click()
    await page.getByRole('button',{name:'删除本人声音',exact:true}).click()
    await page.waitForFunction(async()=> !(await (await fetch('/api/voice/owner/status')).json()).enrolled)
    assert.equal(await toggle.isChecked(),false)
    assert.equal(await page.evaluate(()=>window.__calls),3)
    assert.deepEqual(errors,[])
    const result={passed:true,recordings:2,actual_enrollment:enrollments,no_automatic_microphone:true,close_releases_tracks:true,errors,method:'Real Edge file-backed microphone, official recorder, WAV conversion, HTTP enrollment, local ERes2Net; no human recording or accuracy claim.'}
    fs.writeFileSync(path.join(out,'owner-ui.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))
  } catch(error) { await page.screenshot({path:path.join(out,'owner-ui-failure.png')}).catch(()=>{});throw error }
  finally {await context.close();if(session)await fetch(base+'/api/sessions/'+session,{method:'DELETE'}).catch(()=>{});await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1})
