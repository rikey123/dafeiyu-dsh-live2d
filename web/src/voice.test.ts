import { afterEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ callbacks: {} as Record<string, (...args: any[]) => void>, resume: vi.fn(), sendText: vi.fn(), sendClientMessage: vi.fn(), media: null as any, createLip: vi.fn(), initDevices: vi.fn(), connect: vi.fn(), disconnect: vi.fn(), enableCam: undefined as boolean | undefined }))
vi.mock('./avatar/lipsync/runtime', () => ({ createRealtimeLipNode: state.createLip }))
vi.mock('@pipecat-ai/client-js', () => ({
  PipecatClient: class { constructor(options: { callbacks: typeof state.callbacks; enableCam?: boolean }) { state.callbacks = options.callbacks; state.enableCam = options.enableCam } sendText = state.sendText; sendClientMessage = state.sendClientMessage; initDevices = state.initDevices; connect = state.connect; disconnect = state.disconnect },
}))
vi.mock('@pipecat-ai/websocket-transport', () => ({
  WavMediaManager: class { constructor() { state.media = this }; _wavStreamPlayer = { context: { state: 'suspended', resume: state.resume } }; async interruptBotAudio() {} }, WebSocketTransport: class {},
}))

import { VoiceSession } from './voice'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

function connectionFixture(initiativeStatus?: (value: string) => void, screenRequest?: (value: {stream_id:string; request_id:string}) => void, screenSample?: (value: {stream_id:string}) => void, idleStatus?: (value:string)=>void) {
  vi.stubGlobal('location', { protocol: 'http:', host: '127.0.0.1:8765' })
  state.initDevices.mockReset().mockResolvedValue(undefined)
  state.connect.mockReset().mockResolvedValue(undefined)
  state.disconnect.mockReset().mockResolvedValue(undefined)
  state.sendClientMessage.mockReset()
  const noop = () => {}, connected = vi.fn(), disconnected = vi.fn(), error = vi.fn()
  const session = new VoiceSession({ connected, disconnected, error, userText: noop, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop, initiativeStatus, screenRequest, screenSample, idleStatus })
  return { session, connected, disconnected, error }
}

describe('realtime mouth media integration', () => {
  it('requires live consumption, closes on stop and ignores retired epochs and classifier frames', async () => {
    const { session } = connectionFixture()
    const gain = { gain: { value: 1, setTargetAtTime: vi.fn() }, connect: vi.fn(), disconnect: vi.fn(), context: null as any }
    const analyser = { getFloatTimeDomainData: (samples: Float32Array) => samples.fill(.1), connect: vi.fn() }
    const context = { currentTime: 1, state: 'running', createGain: () => gain, createAnalyser: () => analyser, destination: {} }
    gain.context = context
    const node = { port: { onmessage: vi.fn() }, volume: 1, weights: { A: 1 }, connect: vi.fn(), disconnect: vi.fn() }
    state.createLip.mockResolvedValueOnce(node)
    const player = { context, analyser, stream: null as any, connect: vi.fn(), onConsumed: (_samples: number, _epoch: string) => {} }
    state.media._wavStreamPlayer = player
    await state.media.initialize()
    await vi.waitFor(() => expect(state.media.lipStatus).toContain('wLipSync'))
    player.stream = { port: { postMessage: vi.fn() } }
    const start = (epoch: string) => state.callbacks.onServerMessage({ type: 'voice.playback.start', epoch, sample_rate: 24000 })
    const classify = (timestamp: number) => node.port.onmessage({ data: { timestamp } })
    start('old'); classify(1)
    expect(session.vowels()?.A).toBe(0)
    player.onConsumed(128, 'old')
    context.currentTime = 1.016
    expect(session.vowels()?.A).toBeGreaterThan(0)
    context.currentTime = 1.1
    session.stop()
    player.onConsumed(128, 'old'); classify(1.05)
    expect(session.vowels()?.A).toBe(0)
    await Promise.resolve() // Complete the native stop receipt before a new epoch.
    start('new'); context.currentTime = 1.2
    player.onConsumed(128, 'old'); classify(1.2)
    expect(session.vowels()?.A).toBe(0)
    player.onConsumed(128, 'new')
    context.currentTime = 1.216
    expect(session.vowels()?.A).toBeGreaterThan(0)
    session.setVolume(0)
    expect(session.vowels()?.A).toBe(0)
    session.setVolume(1); context.currentTime = 1.24
    player.onConsumed(128, 'new'); classify(1.24)
    expect(session.vowels()?.A).toBeGreaterThan(0)
  })
})

describe('voice connection lifecycle', () => {
  it('routes server sampling pulses without granting capture and ignores them after shutdown', async () => {
    const sample=vi.fn(), {session}=connectionFixture(undefined,undefined,sample)
    const message={type:'voice.screen.sample',stream_id:'current-stream'}
    state.callbacks.onServerMessage(message)
    state.callbacks.onServerMessage({...message,stream_id:42})
    expect(sample).toHaveBeenCalledExactlyOnceWith({stream_id:'current-stream'})
    expect(state.sendClientMessage).not.toHaveBeenCalled()
    await session.disconnect()
    state.callbacks.onServerMessage(message)
    expect(sample).toHaveBeenCalledOnce()
  })
  it('routes screen requests only while connected', async () => {
    const request = vi.fn(), {session} = connectionFixture(undefined, request)
    const message = {type:'voice.screen.request', stream_id:'stream', request_id:'request'}
    state.callbacks.onServerMessage(message)
    expect(request).toHaveBeenCalledWith({stream_id:'stream', request_id:'request'})
    state.callbacks.onServerMessage({...message, purpose:'tool'})
    expect(request).toHaveBeenLastCalledWith({stream_id:'stream', request_id:'request', purpose:'tool'})
    state.callbacks.onServerMessage({...message, purpose:'intent'})
    expect(request).toHaveBeenLastCalledWith({stream_id:'stream', request_id:'request', purpose:'intent'})
    state.callbacks.onServerMessage({...message, purpose:'idle'})
    expect(request).toHaveBeenLastCalledWith({stream_id:'stream', request_id:'request', purpose:'idle'})
    state.callbacks.onServerMessage({...message, purpose:'unknown'})
    state.callbacks.onServerMessage({...message, purpose:null})
    state.callbacks.onServerMessage({...message, request_id:42})
    expect(request).toHaveBeenCalledTimes(4)
    await session.disconnect()
    state.callbacks.onServerMessage(message)
    expect(request).toHaveBeenCalledTimes(4)
  })
  it('routes validated initiative diagnostics and ignores messages after disconnect', async () => {
    const status = vi.fn()
    const { session } = connectionFixture(status)
    const message = { type: 'voice.initiative', source: 'doubao-systemone', status: 'accepted', intent: 'empathize', desire: .98 }
    state.callbacks.onServerMessage(message)
    expect(status).toHaveBeenCalledOnce()
    expect(status.mock.calls[0][0]).toContain('不代表已经播放')
    state.callbacks.onServerMessage({ ...message, desire: 2 })
    expect(status).toHaveBeenCalledOnce()
    await session.disconnect()
    state.callbacks.onServerMessage(message)
    expect(status).toHaveBeenCalledOnce()
  })
  it('routes idle diagnostics without turning them into voice failures and stops after disconnect', async () => {
    const idle=vi.fn(), {session,error}=connectionFixture(undefined,undefined,undefined,idle)
    const event={type:'voice.idle',status:'waiting',reason:'busy'}
    state.callbacks.onServerMessage(event)
    expect(idle).toHaveBeenLastCalledWith('对话或任务正在进行')
    state.callbacks.onServerMessage({...event,status:'unavailable',reason:'private upstream failure'})
    expect(idle).toHaveBeenCalledTimes(2)
    expect(error).not.toHaveBeenCalled()
    await session.disconnect()
    state.callbacks.onServerMessage(event)
    expect(idle).toHaveBeenCalledTimes(2)
  })
  it('does not send playback messages after transport shutdown begins', async () => {
    const { session } = connectionFixture()
    await session.disconnect()
    state.media.onPlaybackStopped([{ epoch: 'old', consumed_samples: 5 }])
    state.media.onPlaybackComplete('old', 5)
    expect(state.sendClientMessage).not.toHaveBeenCalled()
  })
  it('closes the output context even when a media cleanup callback throws', async () => {
    const { session } = microphoneFixture()
    const context = { state: 'running', close: vi.fn().mockResolvedValue(undefined) }
    state.media._wavStreamPlayer.context = context
    state.media.onPlaybackStopped = () => { throw new Error('callback failed') }
    await expect(state.media.disconnect()).rejects.toThrow('callback failed')
    expect(context.close).toHaveBeenCalledOnce()
    // The session still supports explicit client shutdown after cleanup.
    state.disconnect.mockResolvedValue(undefined)
    await session.disconnect()
  })
  it('disables camera initialization for this audio-only transport', () => {
    connectionFixture()
    expect(state.enableCam).toBe(false)
  })
  it('propagates audio initialization errors without opening a socket', async () => {
    const { session } = connectionFixture()
    state.initDevices.mockRejectedValueOnce(new Error('AudioWorklet failed'))
    await expect(session.connect('test')).rejects.toThrow('AudioWorklet failed')
    expect(state.connect).not.toHaveBeenCalled()
    expect(state.disconnect).toHaveBeenCalledOnce()
  })
  it('closes a timed-out attempt and ignores late bot-ready callbacks', async () => {
    vi.useFakeTimers()
    const { session, connected } = connectionFixture()
    state.connect.mockReturnValueOnce(new Promise(() => {}))
    const rejected = expect(session.connect('test')).rejects.toThrow('等待语音服务就绪')
    state.callbacks.onTransportStateChanged('ready')
    await vi.advanceTimersByTimeAsync(20000)
    await rejected
    expect(state.disconnect).toHaveBeenCalledOnce()
    state.callbacks.onBotReady()
    expect(connected).not.toHaveBeenCalled()
    await session.disconnect()
    expect(state.disconnect).toHaveBeenCalledOnce()
  })
  it('reports a rejected handshake immediately with the original server reason', async () => {
    const { session, error } = connectionFixture()
    state.connect.mockReturnValueOnce(new Promise(() => {}))
    const rejected = expect(session.connect('test')).rejects.toThrow('该会话已在另一个窗口使用')
    state.callbacks.onError({ data: { error: '该会话已在另一个窗口使用', fatal: true } })
    await rejected
    expect(state.disconnect).toHaveBeenCalledOnce()
    expect(error).not.toHaveBeenCalled() // the connection promise owns this error
  })
  it('does not open a late socket after cancellation during initialization', async () => {
    const { session } = connectionFixture()
    let finish!: () => void
    state.initDevices.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve }))
    const rejected = expect(session.connect('test')).rejects.toThrow('已取消')
    await session.disconnect()
    finish()
    await rejected
    expect(state.connect).not.toHaveBeenCalled()
  })
  it('ends an established session on a fatal transport error so the app can retry', async () => {
    const { session, disconnected, error } = connectionFixture()
    await session.connect('test')
    state.callbacks.onError({ data: { error: '服务已关闭', fatal: true } })
    await vi.waitFor(() => expect(disconnected).toHaveBeenCalledOnce())
    expect(error).toHaveBeenCalledWith('服务已关闭')
    expect(state.disconnect).toHaveBeenCalledOnce()
  })
})

describe('voice input', () => {
  it('shows a final transcription once when the same input also produces a backchannel', () => {
    const userText = vi.fn()
    const noop = () => {}
    new VoiceSession({ connected: noop, disconnected: noop, error: noop, userText, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop })
    const input = { text: '好的', final: true, timestamp: 'same' }
    state.callbacks.onUserInput({ ...input, input_type: 'transcription' })
    state.callbacks.onUserInput({ ...input, input_type: 'backchannel' })
    state.callbacks.onUserInput({ ...input, input_type: 'chat' })
    state.callbacks.onUserInput({ ...input, final: false, input_type: 'transcription' })
    state.callbacks.onUserInput({ ...input, text: '  ', input_type: 'transcription' })
    expect(userText.mock.calls).toEqual([['好的']])
  })
  it('requests audio resume synchronously from a text send gesture before sending', async () => {
    state.resume.mockReset().mockResolvedValue(undefined)
    state.sendText.mockReset().mockResolvedValue(undefined)
    const noop = () => {}
    const session = new VoiceSession({ connected: noop, disconnected: noop, error: noop, userText: noop, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop })
    const sending = session.sendText('你好')
    expect(state.resume).toHaveBeenCalledOnce()
    expect(state.sendText).not.toHaveBeenCalled()
    await sending
    expect(state.sendText).toHaveBeenCalledWith('你好', { run_immediately: true })
  })
  it('unlocks output synchronously without submitting text or enabling capture, and refuses a closed session', async () => {
    state.resume.mockReset().mockResolvedValue(undefined)
    state.sendText.mockReset(); state.sendClientMessage.mockReset(); state.disconnect.mockResolvedValue(undefined)
    const noop = () => {}, session = new VoiceSession({ connected: noop, disconnected: noop, error: noop, userText: noop, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop })
    const unlocking = session.resumeOutput()
    expect(state.resume).toHaveBeenCalledOnce()
    await unlocking
    expect(state.sendText).not.toHaveBeenCalled()
    expect(state.sendClientMessage).not.toHaveBeenCalled()
    await session.disconnect()
    await expect(session.resumeOutput()).rejects.toThrow('语音连接已关闭')
    expect(state.resume).toHaveBeenCalledOnce()
  })
  it('reports an insufficient owner sample without treating it as a transport error', () => {
    const ownerRejected = vi.fn(), error = vi.fn(), noop = () => {}
    new VoiceSession({ connected: noop, disconnected: noop, error, ownerRejected, userText: noop, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop })
    state.callbacks.onServerMessage({ type: 'voice.speaker', accepted: null, reason: 'insufficient_speech' })
    expect(ownerRejected).toHaveBeenCalledWith(expect.stringContaining('声音太短'))
    expect(error).not.toHaveBeenCalled()
  })
  it('forwards the official TTS started event', () => {
    const ttsStarted = vi.fn(), noop = () => {}
    new VoiceSession({ connected: noop, disconnected: noop, error: noop, userText: noop, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop, ttsStarted })
    state.callbacks.onBotTtsStarted(); expect(ttsStarted).toHaveBeenCalledOnce()
  })
  it('drops text stopped during audio resume and permits a later submission', async () => {
    let resolveResume!: () => void
    state.resume.mockReset().mockReturnValueOnce(new Promise<void>(resolve => { resolveResume = resolve })).mockResolvedValue(undefined)
    state.sendText.mockReset().mockResolvedValue(undefined)
    const noop = () => {}, session = new VoiceSession({ connected: noop, disconnected: noop, error: noop, userText: noop, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop })
    const old = session.sendText('旧消息'); expect(state.resume).toHaveBeenCalledOnce(); session.stop(); resolveResume(); await old
    expect(state.sendText).not.toHaveBeenCalled()
    await session.sendText('新消息'); expect(state.sendText).toHaveBeenCalledOnce(); expect(state.sendText).toHaveBeenCalledWith('新消息', { run_immediately: true })
  })
})

function microphoneFixture() {
  const noop = () => {}
  state.resume.mockReset().mockResolvedValue(undefined)
  const session = new VoiceSession({ connected: noop, disconnected: noop, error: noop, userText: noop, botText: noop, emotion: noop, botStart: noop, botStop: noop, userStart: noop, userStop: noop })
  const track = { readyState: 'live', stop: vi.fn() }
  const context = { state: 'running', close: vi.fn().mockResolvedValue(undefined), createGain: () => ({ gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() }), destination: {} }
  const recorder = { stream: null as any, analyser: null as any, processor: null as any, record: vi.fn().mockResolvedValue(undefined), begin: vi.fn(async (_device: string) => {
    recorder.stream = { getTracks: () => [track], getAudioTracks: () => [track] }
    recorder.analyser = { context, connect: vi.fn(), disconnect: vi.fn() }
    recorder.processor = { disconnect: vi.fn() }
  }), end: vi.fn(async () => { recorder.stream = null; recorder.processor = null; return { url: 'blob:test' } }) }
  state.media._wavRecorder = recorder
  state.media._startRecording = vi.fn().mockResolvedValue(undefined)
  return { session, recorder, track, context }
}

describe('microphone lifecycle', () => {
  it('does not acquire a microphone when shutdown wins an output-resume race', async () => {
    const { session, recorder } = microphoneFixture()
    let resume!: () => void
    state.resume.mockReturnValueOnce(new Promise<void>(resolve => { resume = resolve }))
    const enabling = session.setMic(true)
    await session.disconnect()
    resume(); await enabling
    expect(recorder.begin).not.toHaveBeenCalled()
    await expect(session.setMic(true)).rejects.toThrow('closed')
  })
  it('releases a late microphone acquisition and never re-enables capture after shutdown', async () => {
    const { session, recorder, track } = microphoneFixture()
    state.sendClientMessage.mockClear()
    const begin = recorder.begin.getMockImplementation()!
    let finish!: () => void
    recorder.begin.mockImplementationOnce(async device => { await new Promise<void>(resolve => { finish = resolve }); await begin(device) })
    state.media._wavStreamPlayer.context = { state: 'running', close: vi.fn().mockResolvedValue(undefined) }
    state.disconnect.mockImplementationOnce(() => state.media.disconnect())
    const enabling = session.setMic(true)
    await vi.waitFor(() => expect(recorder.begin).toHaveBeenCalledOnce())
    const closing = session.disconnect()
    finish(); await Promise.all([enabling, closing])
    expect(track.stop).toHaveBeenCalled()
    expect(state.media._micEnabled).toBe(false)
    expect(state.sendClientMessage.mock.calls).not.toContainEqual(['voice.capture', { active: true }])
  })
  it('uses system default explicitly and releases the stream and context on disable', async () => {
    const { session, recorder, track, context } = microphoneFixture()
    await session.setMic(true)
    expect(recorder.begin).toHaveBeenCalledWith('')
    await session.setMic(false)
    expect(track.stop).toHaveBeenCalled()
    expect(context.close).toHaveBeenCalledOnce()
    expect(recorder.stream).toBeNull()
    expect(recorder.analyser).toBeNull()
  })
  it('preserves the native error and permits retry after a failed acquisition', async () => {
    const { session, recorder } = microphoneFixture()
    const missing = new DOMException('Requested device not found', 'NotFoundError')
    recorder.begin.mockRejectedValueOnce(missing)
    await expect(session.setMic(true)).rejects.toBe(missing)
    expect(state.media._micEnabled).toBe(false)
    await session.setMic(true, 'usb-mic')
    expect(recorder.begin).toHaveBeenLastCalledWith('usb-mic')
    expect(state.media._micEnabled).toBe(true)
    await session.setMic(false)
  })
  it('releases a stream when worklet recording fails', async () => {
    const { session, track, context, recorder } = microphoneFixture()
    state.media._startRecording.mockRejectedValueOnce(new Error('worklet failed'))
    await expect(session.setMic(true)).rejects.toThrow('worklet failed')
    expect(track.stop).toHaveBeenCalled()
    expect(context.close).toHaveBeenCalledOnce()
    expect(recorder.stream).toBeNull()
  })
  it('serializes disable and re-enable while acquisition is pending', async () => {
    const { session, recorder, track } = microphoneFixture()
    state.sendClientMessage.mockClear()
    const begin = recorder.begin.getMockImplementation()!
    let resolve!: () => void
    recorder.begin.mockImplementationOnce(async device => { await new Promise<void>(done => { resolve = done }); await begin(device) })
    const enabling = session.setMic(true)
    await vi.waitFor(() => expect(recorder.begin).toHaveBeenCalledOnce())
    const disabling = session.setMic(false), next = session.setMic(true, 'new-mic')
    expect(recorder.begin).toHaveBeenCalledOnce()
    resolve(); await Promise.all([enabling, disabling, next])
    expect(state.sendClientMessage.mock.calls.filter(([type]) => type === 'voice.capture')).toEqual([
      ['voice.capture', { active: false }], ['voice.capture', { active: true }],
    ])
    expect(track.stop).toHaveBeenCalled()
    expect(recorder.begin).toHaveBeenCalledTimes(2)
    expect(recorder.begin).toHaveBeenLastCalledWith('new-mic')
    expect(state.media._micEnabled).toBe(true)
    await session.setMic(false)
  })
  it('uses the same default selection and native errors for owner recording', async () => {
    const { session, recorder } = microphoneFixture()
    const denied = new DOMException('Permission denied', 'NotAllowedError')
    recorder.begin.mockRejectedValueOnce(denied)
    await expect(session.startEnrollment()).rejects.toBe(denied)
    expect(recorder.begin).toHaveBeenCalledWith('')
    expect(state.media.enrolling).toBe(false)
    await session.setMic(true)
    await session.setMic(false)
  })
})
