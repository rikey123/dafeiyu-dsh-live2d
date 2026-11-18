/* Real official Pipecat browser client/worklets + real local STT/TTS.
   Uses isolated serve_voice_acceptance.py, controlled LLM, calibrated file-backed fake microphone. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const root = path.resolve(__dirname, '..'), out = path.join(root, 'artifacts/pipecat-acceptance')
fs.mkdirSync(out, { recursive: true })
const url = process.env.VOICE_TEST_URL || 'http://127.0.0.1:8875'
;(async () => {
  const fixtures = {}
  for (const [name, text] of Object.entries({ backchannel: '好的。', interrupt: '等一下，我想换一个问题。' })) {
    const response = await fetch('http://127.0.0.1:8766/v1/audio/speech', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ input: text, response_format: 'wav' }) })
    assert(response.ok); fixtures[name] = Buffer.from(await response.arrayBuffer()).toString('base64')
  }
  const pcm = base64 => {
    const wav = Buffer.from(base64, 'base64'); let offset = 12
    while (offset + 8 <= wav.length) { const size = wav.readUInt32LE(offset + 4); if (wav.toString('ascii', offset, offset + 4) === 'data') {const data = Buffer.from(wav.subarray(offset + 8, offset + 8 + size)); let peak=1;for(let i=0;i<data.length;i+=2)peak=Math.max(peak,Math.abs(data.readInt16LE(i)));for(let i=0;i<data.length;i+=2)data.writeInt16LE(Math.round(data.readInt16LE(i)*22000/peak),i);return data} offset += 8 + size + (size % 2) }
    throw Error('fixture WAV has no data')
  }
  const backPcm = pcm(fixtures.backchannel), interruptPcm = pcm(fixtures.interrupt)
  const prefixMs = 1500, gapMs = 3500
  const data = Buffer.concat([Buffer.alloc(prefixMs*32),backPcm,Buffer.alloc(gapMs*32),interruptPcm,Buffer.alloc(20*32000)])
  const header = Buffer.alloc(44);header.write('RIFF');header.writeUInt32LE(data.length+36,4);header.write('WAVEfmt ',8);header.writeUInt32LE(16,16);header.writeUInt16LE(1,20);header.writeUInt16LE(1,22);header.writeUInt32LE(16000,24);header.writeUInt32LE(32000,28);header.writeUInt16LE(2,32);header.writeUInt16LE(16,34);header.write('data',36);header.writeUInt32LE(data.length,40)
  const fakeMic = path.join(out,'microphone.wav');fs.writeFileSync(fakeMic,Buffer.concat([header,data]))
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',`--use-file-for-fake-audio-capture=${fakeMic}`] })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['microphone'] })
  await context.addInitScript(() => {
    const Native = window.AudioContext
    window.__voiceContexts = []; window.__voiceTrace = []; window.__micCalls = 0; window.__micStreams = []; window.__workletMessages = []
    const Socket = window.WebSocket; window.__voiceSockets = []
    window.WebSocket = class extends Socket { constructor(...args) { super(...args); window.__voiceSockets.push(this) } }
    const Worklet = window.AudioWorkletNode
    window.AudioWorkletNode = class extends Worklet {
      constructor(...args) { super(...args); this.port.addEventListener('message', event => { window.__workletMessages.push({ name: args[1], event: event.data?.event, bytes: event.data?.data?.mono?.byteLength }) }) }
    }
    window.AudioContext = class extends Native {
      constructor(...args) { super(...args); window.__voiceContexts.push(this) }
      createGain() {
        const node = super.createGain(), original = node.gain.setTargetAtTime.bind(node.gain)
        node.gain.setTargetAtTime = (...args) => { window.__voiceTrace.push({ type: 'gain', value: args[0], at: performance.now() }); return original(...args) }; return node
      }
    }
    const nativeGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async constraints => {
      window.__micCalls++;window.__micConstraints = constraints;window.__micOpenedAt = Date.now()
      if (window.__denyNextMic) { window.__denyNextMic = false; throw new DOMException('Test permission denial', 'NotAllowedError') }
      const stream = await nativeGetUserMedia(constraints);window.__micStreams.push(stream);return stream
    }
  })
  const page = await context.newPage(), errors = [], events = [], frames = [], results = [], consoleMessages = [], uploads = []
  let sessionId
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => consoleMessages.push({ type: message.type(), text: message.text() }))
  page.on('response', async response => {
    if (response.url().endsWith('/api/sessions') && response.request().method() === 'POST') sessionId = (await response.json()).id
  })
  page.on('websocket', socket => { socket.on('framesent', frame => uploads.push({ at: Date.now(), bytes: Buffer.byteLength(frame.payload), payload: Buffer.from(frame.payload).toString('base64') })); socket.on('framereceived', frame => {
    const buffer = Buffer.from(frame.payload)
    frames.push({ at: Date.now(), bytes: buffer.length })
    // RTVI JSON is embedded as one protobuf string; locate its final JSON payload.
    const start = buffer.indexOf(Buffer.from('{"label"'))
    if (start >= 0) { try { const event = JSON.parse(buffer.subarray(start).toString('utf8')); events.push({ ...event, at: Date.now() }) } catch {} }
  }) })
  const wait = async (predicate, description, timeout = 30000) => {
    const deadline = Date.now() + timeout
    while (!predicate()) { if (Date.now() > deadline) throw Error(description); await page.waitForTimeout(50) }
  }
  async function sendText(text) {
    await page.getByPlaceholder('说点什么，或开启语音...').fill(text)
    await page.getByRole('button', { name: '发送', exact: true }).click()
  }
  try {
    await page.goto(url, { waitUntil: 'networkidle' })
    await wait(() => events.some(event => event.type === 'bot-ready'), 'official RTVI handshake failed', 60000)
    assert.equal(await page.evaluate(() => window.__micCalls), 0, 'opening app must not capture microphone')
    results.push({ name: 'official handshake without microphone permission', passed: true })
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({ timeout: 90000 })
    await page.evaluate(() => {
      const emitter = window.PIXI.utils.EventEmitter.prototype, original = emitter.emit
      window.__mouthValues = []
      emitter.emit = function(...args) { const result = original.apply(this, args); if (args[0] === 'beforeModelUpdate' && this.coreModel) window.__mouthValues.push({at: Date.now(), value: this.coreModel.getParameterValueById('ParamMouthOpenY')}); return result }
      window.__denyNextMic = true
    })
    await page.getByRole('button', {name:'开启语音', exact:true}).click()
    await page.getByRole('status').filter({hasText:'麦克风启动失败'}).waitFor()
    assert.equal(await page.evaluate(() => window.__micStreams.length), 0)
    results.push({name:'permission denial safely releases initialization and allows retry',passed:true})
    const before = events.length
    await sendText('你好，请慢慢介绍你自己。')
    await wait(() => events.slice(before).some(event => event.type === 'bot-started-speaking'), 'real local speech did not start', 60000)
    await page.waitForFunction(() => window.__mouthValues.some(sample => sample.value > .05))
    results.push({name:'real official PCM playback drives actual Cubism mouth',passed:true})
    await page.getByRole('button', { name: '开启语音', exact: true }).click()
    await page.getByRole('button', { name: '正在聆听', exact: true }).waitFor({ timeout: 20000 })
    await wait(() => uploads.some(frame => frame.bytes > 500 && frame.at < Date.now() && frame.at > 0), 'recording did not send continuous leading silence', 1000)
    const backStart = events.length
    assert.deepEqual(await page.evaluate(() => window.__micConstraints.audio), {echoCancellation:true,noiseSuppression:true,autoGainControl:true})
    await wait(() => events.slice(backStart).some(event => event.data?.type === 'voice.backchannel'), 'native backchannel event did not arrive', 15000)
    // The file-backed microphone keeps playing while ASR is busy. A delayed
    // final can arrive immediately before the next utterance's valid partial;
    // a wall-clock sleep would incorrectly count that next turn as backchannel.
    await wait(() => events.slice(backStart).some(event => /user-input|user-transcription/.test(event.type) && /等/.test(event.data?.text || '')), 'second fixture did not reach recognition', 20000)
    const nextUtteranceIndex = events.findIndex((event, index) => index >= backStart && /user-input|user-transcription/.test(event.type) && /等/.test(event.data?.text || ''))
    const backEvents = events.slice(backStart, nextUtteranceIndex)
    assert(!backEvents.some(event => event.type === 'bot-interrupted'), 'acknowledgement falsely interrupted bot')
    const requests = await (await context.request.get('http://127.0.0.1:8874/test/requests')).json()
    assert(!requests.some(request => /^好的[。！!]?$/u.test(request.text)), 'backchannel started a new LLM turn')
    results.push({ name: 'real local synthesized acknowledgement preserves reply', passed: true, transcript: [...new Set(backEvents.filter(event => /user-input|user-transcription/.test(event.type) || event.data?.type === 'voice.backchannel').map(event => event.data?.text))] })
    assert.equal(await page.locator('.message.user .message-text').filter({hasText:/^好的。$/u}).count(),1,'backchannel rendered more than once')
    const interruptStart = nextUtteranceIndex, inputAt = await page.evaluate(() => window.__micOpenedAt) + prefixMs + backPcm.length/32 + gapMs
    await wait(() => events.slice(interruptStart).some(event => event.type === 'bot-interrupted'), 'semantic voice interruption did not occur', 20000)
    await wait(() => events.slice(interruptStart).some(event => event.type === 'bot-started-speaking'), 'new answer did not start after barge-in', 60000)
    results.push({ name: 'real local voice barge-in and next reply', passed: true, virtual_input_duration_ms: interruptPcm.length/32, input_to_interruption_ms: events.slice(interruptStart).find(event => event.type === 'bot-interrupted').at - inputAt })
    const stoppedAt = events.length
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await wait(() => events.slice(stoppedAt).some(event => event.type === 'bot-interrupted'), 'manual stop did not cancel framework')
    await page.waitForTimeout(500)
    assert((await page.evaluate(() => window.__mouthValues.slice(-3))).every(sample => sample.value < .01), 'mouth remained open after official player interruption')
    results.push({ name: 'manual stop uses framework cancellation', passed: true })
    await page.getByRole('button', { name: '正在聆听', exact: true }).click()
    await page.getByRole('button', { name: '开启语音', exact: true }).waitFor({timeout: 10000})
    await page.waitForFunction(() => window.__micStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended')))
    assert(await page.evaluate(() => window.__micStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended'))), 'mic tracks leaked after off')
    results.push({name:'microphone off releases native tracks',passed:true})
    const readyCount = events.filter(event => event.type === 'bot-ready').length, micCount = await page.evaluate(() => window.__micCalls)
    await page.evaluate(() => window.__voiceSockets.at(-1).close())
    await wait(() => events.filter(event => event.type === 'bot-ready').length > readyCount, 'automatic voice reconnection failed', 30000)
    assert.equal(await page.evaluate(() => window.__micCalls),micCount,'reconnect silently reopened microphone')
    results.push({name:'disconnect reconnects same session without automatically recording',passed:true})
    // A manual interruption intentionally has no whole-context completion ACK.
    // Complete one independent text turn to verify the new conservative history
    // policy instead of treating generated/queued speech as already consumed.
    const assistantsBefore = (await (await context.request.get(`${url}/api/sessions/${sessionId}/messages`)).json()).filter(item => item.role === 'assistant').length
    const confirmStart = events.length
    await sendText('换一个问题。')
    await wait(() => events.slice(confirmStart).some(event => event.type === 'server-response' && event.data?.t === 'voice.playback' && event.data?.d?.accepted === true), 'actual player did not confirm completed answer', 60000)
    const stored = await (await context.request.get(`${url}/api/sessions/${sessionId}/messages`)).json()
    assert.equal(stored.filter(item => item.role === 'user' && item.content === '你好，请慢慢介绍你自己。').length, 1, 'typed user message persisted more than once')
    assert(stored.filter(item => item.role === 'assistant').length > assistantsBefore, 'playback-confirmed assistant history missing')
    assert.deepEqual(errors, [])
    await page.screenshot({ path: path.join(out, 'desktop.png'), fullPage: true })
    await page.setViewportSize({width:390,height:844})
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'mobile horizontal overflow')
    await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true})
    const result = { method: 'Real official browser client + official PCM worklets + Pipecat server/Silero/SmartTurn + real local ASR/TTS; controlled LLM and calibrated file-backed fake microphone, no physical AEC/cloud claim.', results, events, frames: frames.length, errors, history: stored }
    fs.writeFileSync(path.join(out, 'browser.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify({ results, errors, directory: out }, null, 2))
  } catch (error) {
    fs.writeFileSync(path.join(out, 'failure.json'), JSON.stringify({ error: String(error), results, errors, events, consoleMessages, uploads, browser: await page.evaluate(() => ({ contexts: window.__voiceContexts.map(context => ({ rate: context.sampleRate, state: context.state, time: context.currentTime })),  trace: window.__voiceTrace, worklet: window.__workletMessages.slice(0, 30), micCalls: window.__micCalls, streams: window.__micStreams.map(stream => stream.getTracks().map(track => ({ readyState: track.readyState, enabled: track.enabled }))) })) }, null, 2))
    await page.screenshot({ path: path.join(out, 'failure.png') }).catch(() => {}); throw error
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
