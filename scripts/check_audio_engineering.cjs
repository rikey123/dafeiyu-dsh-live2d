/* Actual official player + Cubism model. Controlled LLM/local TTS, no microphone. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const base = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8875'
const out = path.resolve(__dirname, '../artifacts/audio-engineering')
;(async () => {
  fs.mkdirSync(out, { recursive: true })
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({viewport:{width:1440,height:1000}})
  await context.addInitScript(() => {
    window.__analysers = []; window.__micCalls = 0
    const Native = window.AudioContext
    window.AudioContext = class extends Native {
      createAnalyser() { const node = super.createAnalyser(); window.__analysers.push(node); return node }
    }
    navigator.mediaDevices.getUserMedia = async () => { window.__micCalls++; throw Error('This test must not open a microphone') }
  })
  const page = await context.newPage(), errors = [], assets = []
  let session
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => { if (response.url().includes('wlipsync')) assets.push(response.url()) })
  page.on('response', async response => { if(response.url().endsWith('/api/sessions') && response.request().method()==='POST') session=(await response.json()).id })
  const setVolume = async value => page.getByRole('slider', {name:'音量', exact:true}).evaluate((element, volume) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(element,String(volume))
    element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}))
  },value)
  try {
    await page.goto(base,{waitUntil:'networkidle'})
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({timeout:90000})
    await page.evaluate(() => {
      const emitter = window.PIXI.utils.EventEmitter.prototype, original = emitter.emit
      window.__mouthSamples = []
      emitter.emit = function (...args) {
        const result = original.apply(this,args)
        if(args[0]==='beforeModelUpdate' && this.coreModel) window.__mouthSamples.push({at:performance.now(),value:this.coreModel.getParameterValueById('ParamMouthOpenY'),form:this.coreModel.getParameterValueById('ParamMouthForm'),pucker:this.coreModel.getParameterValueById('Mouthpucker'),funnel:this.coreModel.getParameterValueById('MouthFunnel')})
        return result
      }
    })
    const input = page.getByPlaceholder('说点什么，或开启语音...')
    await input.fill('请慢慢介绍你自己，让我检查声音与口型。')
    await page.getByRole('button',{name:'发送',exact:true}).click()
    await page.waitForFunction(() => window.__mouthSamples.slice(-5).some(sample=>sample.value>.08), null, {timeout:60000})
    assert(assets.length > 0, 'AIRI wLipSync runtime was not loaded')
    const settings = await page.evaluate(() => window.__analysers.filter(node=>node.fftSize===1024).map(node=>({fft:node.fftSize,rate:node.context.sampleRate,window_ms:node.fftSize/node.context.sampleRate*1000})))
    assert(settings.some(item=>item.rate===24000 && item.fft===1024),'short actual output analysis window is missing')
    const muteAt = await page.evaluate(()=>performance.now())
    await setVolume(0)
    await page.waitForFunction(at=>window.__mouthSamples.slice(-3).every(sample=>sample.at>at && sample.value<.005),muteAt,{timeout:2000})
    await page.waitForTimeout(300)
    const muted = await page.evaluate(at=>window.__mouthSamples.filter(sample=>sample.at>at+350),muteAt)
    const mutedPeak = Math.max(0, ...muted.map(sample => sample.value))
    assert(muted.length>0 && mutedPeak<.04,`mouth follows pre-gain audio while muted (peak=${mutedPeak})`)
    const resumeAt = await page.evaluate(()=>performance.now())
    await setVolume(.85)
    await page.waitForFunction(at=>window.__mouthSamples.some(sample=>sample.at>at && sample.value>.05),resumeAt,{timeout:3000})
    const stoppedAt = await page.evaluate(()=>performance.now())
    await page.getByRole('button',{name:'停止',exact:true}).click()
    await page.waitForFunction(at=>window.__mouthSamples.slice(-3).every(sample=>sample.at>at && sample.value<.005),stoppedAt,{timeout:1500})
    const timings = await page.evaluate(({muteAt,resumeAt,stoppedAt})=>{
      const samples=window.__mouthSamples
      const settle = at=>{const last=samples.filter(sample=>sample.at>=at && sample.value>=.005).at(-1);return last?last.at-at:0}
      return {mute_visual_settle_ms:settle(muteAt),resume_first_open_ms:samples.find(sample=>sample.at>resumeAt && sample.value>.05)?.at-resumeAt,stop_visual_settle_ms:settle(stoppedAt)}
    },{muteAt,resumeAt,stoppedAt})
    // Isolate each interval; later intentional unmuting is not mute failure.
    const samples = await page.evaluate(()=>window.__mouthSamples)
    timings.mute_visual_settle_ms = Math.max(0,...samples.filter(sample=>sample.at>=muteAt && sample.at<resumeAt && sample.value>=.005).map(sample=>sample.at-muteAt))
    assert(timings.mute_visual_settle_ms<500,'muted mouth release exceeds 500ms')
    assert.equal(await page.evaluate(()=>window.__micCalls),0)
    assert.deepEqual(errors,[])
    const shapes = await page.evaluate(() => window.__mouthSamples)
    assert(shapes.some(sample => Math.abs(sample.form || 0) > .005 || Math.abs(sample.pucker || 0) > .005 || Math.abs(sample.funnel || 0) > .005), 'vowel mouth parameters never changed')
    const result={passed:true,method:'Normal Edge autoplay; real official PCM player, gain, wLipSync AEIOU worklet, and Cubism values. Controlled SSE and local VITS. No physical speaker or phoneme-accuracy claim.',settings,timings,assets,waveform_shapes:{form_peak:Math.max(...shapes.map(sample=>Math.abs(sample.form||0))),pucker_peak:Math.max(...shapes.map(sample=>Math.abs(sample.pucker||0))),funnel_peak:Math.max(...shapes.map(sample=>Math.abs(sample.funnel||0)))},errors}
    fs.writeFileSync(path.join(out,'mouth.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))
  } catch(error) { await page.screenshot({path:path.join(out,'mouth-failure.png')}).catch(()=>{});throw error }
  finally { await context.close();if(session)await fetch(base+'/api/sessions/'+session,{method:'DELETE'}).catch(()=>{});await browser.close() }
})().catch(error=>{console.error(error);process.exitCode=1})
