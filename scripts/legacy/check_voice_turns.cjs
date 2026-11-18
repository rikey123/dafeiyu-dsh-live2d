/* Real browser AudioWorklet + Silero model, virtual microphone, controlled WS.
   No cloud LLM, physical microphone, acoustic echo or live settings writes. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../qa/node_modules/playwright')
const root = path.resolve(__dirname, '..'), out = path.join(root, 'artifacts/voice-audit')
fs.mkdirSync(out, { recursive: true })
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
;(async () => {
  const speech = fs.readFileSync(path.join(root, 'artifacts/live-smoke/input.wav')).toString('base64')
  const reply = fs.readFileSync(path.join(root, 'artifacts/live-smoke/reply-1-2.wav')).toString('base64')
  const backchannelText = '对，好的。'
  const backchannelResponse = await fetch('http://127.0.0.1:8766/v1/audio/speech', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ input: backchannelText, response_format: 'wav' }) })
  assert(backchannelResponse.ok, 'real local TTS must produce the backchannel fixture')
  const backchannel = Buffer.from(await backchannelResponse.arrayBuffer()).toString('base64')
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] })
  const context = await browser.newContext({ viewport: { width: 1000, height: 800 } })
  await context.addInitScript(() => {
    const Native = window.AudioContext
    window.__voiceTrace = []
    window.AudioContext = class extends Native {
      createGain() {
        const node = super.createGain(), native = node.gain.setTargetAtTime.bind(node.gain)
        node.gain.setTargetAtTime = (...args) => { window.__voiceTrace.push({ type: 'gain', value: args[0], at: performance.now() }); return native(...args) }
        return node
      }
      createBufferSource() {
        const node = super.createBufferSource(), start = node.start.bind(node), stop = node.stop.bind(node)
        node.start = (...args) => { window.__voiceTrace.push({ type: 'play', at: performance.now() }); return start(...args) }
        node.stop = (...args) => { window.__voiceTrace.push({ type: 'stop', at: performance.now() }); return stop(...args) }
        return node
      }
    }
    const capture = new Native({ sampleRate: 16000 }); let destination
    window.__micStreams = []
    window.__denyMicOnce = true
    navigator.mediaDevices.getUserMedia = async () => { if (window.__denyMicOnce) { window.__denyMicOnce = false; throw new DOMException('controlled permission denial', 'NotAllowedError') }; await capture.resume(); destination = capture.createMediaStreamDestination(); window.__micStreams.push(destination.stream); return destination.stream }
    window.__feedSpeech = async (base64, duration) => {
      const buffer = await capture.decodeAudioData(Uint8Array.from(atob(base64), ch => ch.charCodeAt(0)).buffer)
      const source = capture.createBufferSource(); source.buffer = buffer; source.connect(destination)
      const at = performance.now(); window.__voiceTrace.push({ type: 'mic-input', at, duration: duration || buffer.duration })
      source.start(0, 0, duration || buffer.duration)
      return { at, duration: duration || buffer.duration }
    }
    localStorage.setItem('avatar-model-url', '')
  })
  const page = await context.newPage(), received = [], errors = [], cases = []
  page.on('pageerror', e => errors.push(e.message))
  let socket, epoch = 0, connections = 0
  await page.routeWebSocket('**/ws/chat*', ws => {
    socket = ws; epoch = 0; connections++
    ws.onMessage(message => {
      const value = JSON.parse(String(message)); received.push({ ...value, audio: value.audio ? '[PCM omitted]' : undefined, at: Date.now() })
      if (value.type === 'interrupt') { epoch++; ws.send(JSON.stringify({ type: 'audio.clear', epoch })); ws.send(JSON.stringify({ type: 'state', state: 'listening', epoch })) }
    })
    ws.send(JSON.stringify({ type: 'session', session_id: 'voice-audit-isolated', epoch }))
  })
  const send = event => socket.send(JSON.stringify(event))
  async function waitFor(predicate, message, timeout = 10000) {
    const deadline = Date.now() + timeout
    while (!predicate()) { if (Date.now() > deadline) throw Error(message); await pause(40) }
  }
  async function startReply() {
    const before = await page.evaluate(() => window.__voiceTrace.filter(x => x.type === 'play').length)
    epoch++; send({ type: 'audio.clear', epoch }); send({ type: 'response.start', epoch })
    send({ type: 'audio', epoch, segment_id: 0, audio: reply, text: '受控回放音频。' })
    await page.waitForFunction(count => window.__voiceTrace.filter(x => x.type === 'play').length > count, before)
  }
  try {
    await page.goto(process.env.VOICE_TEST_URL || 'http://127.0.0.1:8765', { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: '开启语音', exact: true }).click()
    await page.getByRole('status').filter({ hasText: '麦克风启动失败' }).waitFor({ timeout: 45000 })
    await page.getByRole('button', { name: '开启语音', exact: true }).click()
    await page.getByRole('button', { name: '正在聆听', exact: true }).waitFor({ timeout: 45000 })
    cases.push({ name: 'microphone permission denial and retry', recovered: true })
    await startReply()
    const before = received.length, input = await page.evaluate(wav => window.__feedSpeech(wav), speech)
    await waitFor(() => received.slice(before).some(x => x.type === 'interrupt'), 'actual Silero did not confirm interruption')
    await waitFor(() => received.slice(before).some(x => x.type === 'audio'), 'interrupted utterance was lost')
    const trace = await page.evaluate(() => window.__voiceTrace.slice())
    const duck = trace.find(x => x.type === 'gain' && x.value < .5 && x.at >= input.at)
    const stop = trace.find(x => x.type === 'stop' && x.at >= input.at)
    assert(duck && stop, 'two-stage duck and stop must reach real WebAudio nodes')
    assert(!received.slice(before).some(x => x.type === 'playback.ack'), 'interrupted sentence must not be acknowledged')
    const origin = await page.evaluate(() => performance.timeOrigin)
    cases.push({ name: 'real Silero barge-in', input_duration_ms: input.duration * 1000, virtual_input_to_duck_ms: duck.at - input.at, virtual_input_to_stop_ms: stop.at - input.at, virtual_buffer_end_to_upload_ms: received.slice(before).find(x => x.type === 'audio').at - (origin + input.at + input.duration * 1000), uploaded_utterances: received.slice(before).filter(x => x.type === 'audio').length })
    // A late old-generation WAV must never reach WebAudio.
    const playsBefore = trace.filter(x => x.type === 'play').length
    send({ type: 'audio', epoch: epoch - 1, segment_id: 99, audio: reply, text: '迟到旧音频' })
    await pause(300)
    assert.equal(await page.evaluate(() => window.__voiceTrace.filter(x => x.type === 'play').length), playsBefore)
    cases.push({ name: 'stale audio after real voice interruption', rejected: true })
    // Next complete user utterance must still pass the same live VAD instance.
    const next = received.length
    await page.evaluate(wav => window.__feedSpeech(wav), speech)
    await waitFor(() => received.slice(next).some(x => x.type === 'audio'), 'next utterance failed after interruption')
    cases.push({ name: 'next voice utterance', uploaded_utterances: received.slice(next).filter(x => x.type === 'audio').length })
    // Observe a real synthesized Chinese backchannel; this is not a human corpus.
    await startReply()
    const backBefore = received.length, backInput = await page.evaluate(wav => window.__feedSpeech(wav), backchannel)
    await pause(backInput.duration * 1000 + 1400)
    cases.push({ name: 'synthesized Chinese backchannel observation', text: backchannelText, duration_ms: backInput.duration * 1000, interrupted: received.slice(backBefore).some(x => x.type === 'interrupt'), note: 'Single synthetic sample; does not establish semantic backchannel understanding.' })
    // Disconnect the controlled peer and verify actual capture tracks are released.
    const connectionCount = connections
    socket.close({ code: 1012, reason: 'controlled voice audit disconnect' })
    await page.getByRole('button', { name: '开启语音', exact: true }).waitFor()
    await page.waitForFunction(() => window.__micStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended')))
    await waitFor(() => connections > connectionCount, 'WebSocket did not reconnect')
    await page.getByRole('button', { name: '开启语音', exact: true }).click()
    await page.getByRole('button', { name: '正在聆听', exact: true }).waitFor({ timeout: 45000 })
    const reconnected = received.length
    await page.evaluate(wav => window.__feedSpeech(wav), speech)
    await waitFor(() => received.slice(reconnected).some(x => x.type === 'audio'), 'voice failed after explicit microphone restart')
    cases.push({ name: 'disconnect and explicit voice restart', reconnected: true, old_tracks_released: true, uploaded_utterances: received.slice(reconnected).filter(x => x.type === 'audio').length })
    await page.getByRole('button', { name: '正在聆听', exact: true }).click()
    assert.deepEqual(errors, [])
    const result = { method: 'Actual production browser/Silero/AudioWorklet/WebAudio; generated virtual microphone PCM; mocked WS peer; no ASR/LLM or physical AEC claim. Times start at virtual buffer playback, not human voiced phoneme.', cases, errors, events: received }
    fs.writeFileSync(path.join(out, 'browser-turns.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result, null, 2))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
