import { voiceUrl } from './runtime'
import { PipecatClient } from '@pipecat-ai/client-js'
import { WavMediaManager, WebSocketTransport } from '@pipecat-ai/websocket-transport'
import { mouthLevel } from './mouth'
import { enrollmentWav } from './enrollmentWav'
import type { WLipSyncAudioNode } from 'wlipsync'
import { createRealtimeLipNode } from './avatar/lipsync/runtime'
import { bindClassifierMessages, RealtimeLipSync } from './avatar/lipsync/realtime'
import { PlaybackReceipt } from './playback'
import { EmotionQueue } from './emotionQueue'
import emotionKeywords from './emotionKeywords.json'
import { BehaviorQueue, isBehaviorSource, type AppliedBehavior } from './behavior'
import { initiativeStatus } from './initiative'
import { presenceStatus } from './presenceStatus'

export type PlaybackDiagnostics = { queuedSamples: number; maxQueued: number; underruns: number; dropped: number; consumed: number; overflows: number }
type Player = { context: AudioContext | null; analyser: AnalyserNode | null; stream: AudioWorkletNode | null; playbackEpoch?: string; onConsumed?: (samples: number, epoch: string) => void; onTelemetry?: (data: PlaybackDiagnostics) => void; onOverflow?: (epoch: string) => void; connect: () => Promise<unknown> }
type Recorder = { stream: MediaStream | null; processor: AudioWorkletNode | null; analyser: AnalyserNode | null; source?: AudioNode | null; node?: AudioNode | null; recording?: boolean; begin: (id?: string) => Promise<unknown>; record: () => Promise<unknown>; end: () => Promise<{ blob: Blob; url: string; channelCount: number; sampleRate: number }> }
type Internals = { _wavRecorder: Recorder; _wavStreamPlayer: Player; _initialized: boolean; _micEnabled: boolean; _startRecording: () => Promise<void> }
export type MicDiagnostics = { settings: Pick<MediaTrackSettings, 'echoCancellation' | 'noiseSuppression' | 'autoGainControl' | 'sampleRate'>; supported: Pick<MediaTrackSupportedConstraints, 'echoCancellation' | 'noiseSuppression' | 'autoGainControl' | 'sampleRate'> }
const Manager = WavMediaManager as unknown as new (chunk: number, rate: number) => { initialize(): Promise<void>; disconnect(): Promise<void>; bufferBotAudio(data: ArrayBuffer | Int16Array, id?: string): Int16Array; interruptBotAudio(): Promise<unknown> }

/** Adapts the pinned official manager; its worklets own capture and playback. */
class VoiceMedia extends Manager {
  private disposed = false
  profileName: 'local-vits' | 'airi' = 'airi'
  private gain?: GainNode
  private connectedStream?: AudioWorkletNode
  private volume = .85
  private ducked = false
  private micVersion = 0
  private micOperation?: Promise<void>
  private captureSink?: GainNode
  private enrolling = false
  private enrollmentStart?: Promise<void>
  private outputAnalyser?: AnalyserNode
  private outputSamples = new Float32Array(1024)
  private lipNode?: WLipSyncAudioNode
  private lipSink?: GainNode
  private realtimeLip = new RealtimeLipSync()
  private releaseLipFrames?: () => void
  onPlaybackStopped?: (chunks: { epoch: string; consumed_samples: number }[]) => void
  onPlaybackComplete?: (epoch: string, samples: number) => void
  onPlaybackConsumed?: (epoch: string) => void
  onPlaybackOverflow?: () => void
  private playback = new PlaybackReceipt((epoch, samples) => { if (!this.playback.snapshot().length) this.resetLip(); this.onPlaybackComplete?.(epoch, samples) })
  private playbackStats: PlaybackDiagnostics = { queuedSamples: 0, maxQueued: 0, underruns: 0, dropped: 0, consumed: 0, overflows: 0 }
  lipStatus = '元音口型初始化中'
  private get internal() { return this as unknown as Internals }
  override async initialize() {
    if (this.disposed) throw new Error('语音连接已关闭')
    if (this.internal._initialized) return
    await this.internal._wavStreamPlayer.connect()
    if (this.disposed) {
      const context = this.internal._wavStreamPlayer.context
      if (context && context.state !== 'closed') await context.close()
      throw new Error('语音连接已关闭')
    }
    this.internal._initialized = true
    const player = this.internal._wavStreamPlayer
    player.onConsumed = (samples, epoch) => {
      if (this.playback.acceptsAudio(epoch)) {
        this.realtimeLip.consumed(player.context?.currentTime ?? 0)
        this.onPlaybackConsumed?.(epoch)
      }
      this.playback.consume(samples, epoch)
    }
    player.onTelemetry = data => { this.playbackStats = { queuedSamples: data.queuedSamples, maxQueued: data.maxQueued, underruns: data.underruns, dropped: data.dropped, consumed: data.consumed, overflows: data.overflows } }
    player.onOverflow = () => { this.playback.interrupt(); this.resetLip(); this.onPlaybackOverflow?.() }
    if (!player.context || !player.analyser) throw new Error('音频输出初始化失败')
    this.gain = player.context.createGain(); this.outputAnalyser = player.context.createAnalyser()
    this.outputAnalyser.fftSize = this.outputSamples.length
    this.gain.connect(this.outputAnalyser); this.outputAnalyser.connect(player.context.destination); this.updateGain()
    void this.initializeLip(player.context)
  }
  private async initializeLip(context: AudioContext) {
    try {
      const node = await createRealtimeLipNode(context, this.profileName)
      if (context.state === 'closed' || !this.gain) { node.disconnect(); return }
      if (this.disposed) { node.disconnect(); return }
      this.releaseLipFrames = bindClassifierMessages(node.port, this.realtimeLip, () => context.currentTime)
      this.lipNode = node; this.lipSink = context.createGain(); this.lipSink.gain.value = 0
      this.gain.connect(node); node.connect(this.lipSink); this.lipSink.connect(context.destination)
      this.lipStatus = `wLipSync 元音口型 · ${this.profileName === 'local-vits' ? '旧 VITS 专用' : '通用元音模板（未校准当前声线）'}`
    } catch (error) { this.lipStatus = `音量口型回退：${String(error)}` }
  }
  override bufferBotAudio(data: ArrayBuffer | Int16Array, id?: string) {
    if (!this.internal._initialized || !this.internal._wavStreamPlayer.context || this.internal._wavStreamPlayer.context.state === 'closed') return new Int16Array(0)
    const value = super.bufferBotAudio(data, id), player = this.internal._wavStreamPlayer
    if (player.stream && player.stream !== this.connectedStream && player.context && this.gain) { player.stream.disconnect(player.context.destination); player.stream.connect(this.gain); this.connectedStream = player.stream }
    return value
  }
  startPlayback(epoch: string) { if (!this.playback.start(epoch)) return false; const player = this.internal._wavStreamPlayer; player.playbackEpoch = epoch; player.stream?.port.postMessage({ event: 'epoch', epoch }); return true }
  playbackBoundary(epoch: string, samples: number) { if (!this.playback.boundary(epoch, samples)) return false; this.internal._wavStreamPlayer.stream?.port.postMessage({ event: 'flush' }); return true }
  override async interruptBotAudio() {
    this.playback.holdCompletion(); this.resetLip()
    try { return await super.interruptBotAudio() }
    finally { const chunks = this.playback.snapshot(); this.playback.interrupt(); this.onPlaybackStopped?.(chunks) }
  }
  async setMic(enabled: boolean, device?: string) {
    if (enabled && this.disposed) throw new Error('Voice session closed')
    if (enabled && this.enrolling) throw new Error('请先结束本人声音录制')
    const version = ++this.micVersion
    const previous = this.micOperation
    const internal = this.internal, recorder = internal._wavRecorder
    const operation = (async () => {
      await previous?.catch(() => {})
      if (enabled && version !== this.micVersion) return
      await this.releaseCapture()
      if (!enabled || version !== this.micVersion) return
      try {
      // Empty string explicitly means system default; undefined reuses the
      // upstream recorder's remembered device, which may have been unplugged.
      await recorder.begin(device || '')
      if (version !== this.micVersion) { await this.releaseCapture(); return }
      if (!recorder.analyser) throw new Error('麦克风音频处理器不可用')
      this.captureSink = recorder.analyser.context.createGain(); this.captureSink.gain.value = 0
      recorder.analyser.connect(this.captureSink); this.captureSink.connect(recorder.analyser.context.destination)
      const context = recorder.analyser.context as AudioContext
      if (context.state === 'suspended') await context.resume()
      internal._micEnabled = true; await internal._startRecording()
      if (version !== this.micVersion) { await this.releaseCapture(); return }
      if (!recorder.stream?.getAudioTracks().some(track => track.readyState === 'live')) throw new Error('麦克风不可用')
    } catch (error) { await this.releaseCapture(); throw error } })()
    this.micOperation = operation
    try { await operation } finally { if (this.micOperation === operation) this.micOperation = undefined }
  }
  private async releaseCapture() {
    const internal = this.internal, recorder = internal._wavRecorder
    const stream = recorder.stream, context = recorder.analyser?.context as AudioContext | undefined
    const nodes = [recorder.processor, recorder.source, recorder.node, recorder.analyser]
    internal._micEnabled = false
    try {
      if (recorder.processor && context?.state !== 'closed') {
        const result = await recorder.end()
        URL.revokeObjectURL(result.url)
      }
    } catch (error) { console.warn('麦克风结束录制失败，释放剩余资源', error) }
    finally {
      this.captureSink?.disconnect(); this.captureSink = undefined
      stream?.getTracks().forEach(track => track.stop())
      nodes.forEach(node => node?.disconnect())
      recorder.stream = null; recorder.processor = null; recorder.analyser = null
      recorder.source = null; recorder.node = null; recorder.recording = false
      if (context && context.state !== 'closed') await context.close().catch(() => {})
    }
  }
  async startEnrollment(device?: string) {
    if (this.disposed) throw new Error('Voice session closed')
    if (this.enrolling) throw new Error('正在录制')
    this.enrolling = true
    const recorder = this.internal._wavRecorder
    const start = (async () => { try {
      await this.setMic(false)
      if (this.disposed) throw new Error('Voice session closed')
      await recorder.begin(device || '')
      if (this.disposed) throw new Error('Voice session closed')
      if (!recorder.analyser) throw new Error('麦克风音频处理器不可用')
      this.captureSink = recorder.analyser.context.createGain(); this.captureSink.gain.value = 0
      recorder.analyser.connect(this.captureSink); this.captureSink.connect(recorder.analyser.context.destination)
      const context = recorder.analyser.context as AudioContext
      if (context.state === 'suspended') await context.resume()
      await recorder.record()
    } catch (error) { this.enrolling = false; await this.releaseCapture(); throw error } })()
    this.enrollmentStart = start
    try { await start } finally { if (this.enrollmentStart === start) this.enrollmentStart = undefined }
  }
  async stopEnrollment() {
    await this.enrollmentStart?.catch(() => {})
    if (!this.enrolling) return undefined
    this.enrolling = false
    this.captureSink?.disconnect(); this.captureSink = undefined
    const recorder = this.internal._wavRecorder
    try { const result = await recorder.end(); URL.revokeObjectURL(result.url); return enrollmentWav(await result.blob.arrayBuffer(), result.channelCount, result.sampleRate) } finally { await this.releaseCapture() }
  }
  override async disconnect() {
    this.disposed = true
    this.internal._initialized = false
    const context = this.internal._wavStreamPlayer.context
    this.resetLip()
    ++this.micVersion // Invalidate an in-flight microphone permission request immediately.
    const playbackStop = this.interruptBotAudio()
    try {
      await this.stopEnrollment()
      await this.setMic(false); await playbackStop
    } finally {
      try { this.releaseLipFrames?.(); this.releaseLipFrames = undefined; this.lipNode?.disconnect(); this.lipSink?.disconnect() }
      finally {
        this.lipNode = undefined; this.lipSink = undefined; this.gain = undefined
        if (context && context.state !== 'closed') await context.close()
        this.internal._initialized = false
      }
    }
  }
  setVolume(value: number) { this.volume = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0; if (this.volume === 0) this.resetLip(); this.updateGain() }
  async resumeOutput() {
    const context = this.internal._wavStreamPlayer.context
    if (context?.state === 'suspended') await context.resume()
  }
  duck(value: boolean) { this.ducked = value; this.updateGain() }
  private updateGain() { if (this.gain) this.gain.gain.setTargetAtTime(this.volume * (this.ducked ? .25 : 1), this.gain.context.currentTime, .03) }
  level() {
    const analyser = this.outputAnalyser
    const context = this.internal._wavStreamPlayer.context
    if (!analyser || !this.internal._wavStreamPlayer.stream || !context || context.state !== 'running' || !this.realtimeLip.playing(context.currentTime) || this.volume === 0) return 0
    analyser.getFloatTimeDomainData(this.outputSamples)
    return mouthLevel(this.outputSamples)
  }
  resetLip() { this.realtimeLip.reset(this.internal._wavStreamPlayer.context?.currentTime ?? 0) }
  vowels() {
    const context = this.internal._wavStreamPlayer.context
    return this.realtimeLip.value(this.lipNode, context?.currentTime ?? 0, this.volume > 0 && this.level() > .005, context?.state === 'running')
  }
  micDiagnostics(): MicDiagnostics | undefined {
    const track = this.internal._wavRecorder.stream?.getAudioTracks().find(item => item.readyState === 'live')
    if (!track) return undefined
    const { echoCancellation, noiseSuppression, autoGainControl, sampleRate } = track.getSettings()
    const supported = navigator.mediaDevices.getSupportedConstraints()
    return { settings: { echoCancellation, noiseSuppression, autoGainControl, sampleRate }, supported: { echoCancellation: supported.echoCancellation, noiseSuppression: supported.noiseSuppression, autoGainControl: supported.autoGainControl, sampleRate: supported.sampleRate } }
  }
  diagnostics() { return { ...this.playbackStats } }
}

type VoiceCallbacks = {
  behavior?: (value: AppliedBehavior | undefined) => void
  decisionStatus?: (reason: string) => void
  initiativeStatus?: (status: string) => void
  idleStatus?: (status: string) => void
  screenRequest?: (request: {stream_id: string; request_id: string; purpose?: 'tool'|'intent'|'idle'}) => void
  screenSample?: (request: {stream_id: string}) => void
  screenStatus?: (status: import('./screenCompanion').ScreenStatus) => void
  connected: () => void; disconnected: () => void; error: (message: string) => void
  userText: (text: string) => void; botText: (text: string) => void; emotion: (value: string) => void
  botStart: () => void; botStop: () => void; userStart: () => void; userStop: () => void
  ttsStarted?: () => void
  ownerRejected?: (message: string) => void
}
export class VoiceSession {
  private closed = false
  private closing?: Promise<void>
  private connectionFailure?: (error: Error) => void
  private connectionPhase = '初始化音频输出'
  private submissionVersion = 0
  private captureVersion = 0
  private emotions = new EmotionQueue()
  private behaviors = new BehaviorQueue()
  private onBehavior?: (value: AppliedBehavior | undefined) => void
  private onEmotion: (value: string) => void
  private media = new VoiceMedia(1024, 16000)
  private transport = new WebSocketTransport({ mediaManager: this.media as never, recorderSampleRate: 16000, playerSampleRate: 24000 })
  private client: PipecatClient
  constructor(cb: VoiceCallbacks, profileName: 'local-vits' | 'airi' = 'airi') {
    this.media.profileName = profileName
    this.onEmotion = cb.emotion
    this.onBehavior = cb.behavior
    const emotions = this.emotions
    const behaviors = this.behaviors
    this.media.onPlaybackConsumed = epoch => { const value = emotions.consume(epoch); if (value) cb.emotion(value); const next = behaviors.consume(epoch); if (next) cb.behavior?.(next.behavior) }
    this.media.onPlaybackOverflow = () => { emotions.clear(); behaviors.clear(); cb.behavior?.(undefined); cb.emotion('neutral'); this.client.sendClientMessage('voice.stop', {}); cb.error('音频积压过多，已停止本次回复，请重试。') }
    this.media.onPlaybackStopped = chunks => { if (!this.closed && chunks.length) this.client.sendClientMessage('voice.playback.stopped', { chunks }) }
    this.media.onPlaybackComplete = (epoch, samples) => { if (this.closed) return; emotions.finish(epoch); if (behaviors.finish(epoch)) cb.behavior?.(undefined); this.client.sendClientMessage('voice.playback', { epoch, consumed_samples: samples, sample_rate: 24000, completed: true }) }
    this.client = new PipecatClient({ transport: this.transport, enableMic: false, enableCam: false, callbacks: {
      onBotReady: () => { if (!this.closed) cb.connected() },
      onDisconnected: () => { if (!this.closed) { this.connectionFailure?.(new Error('语音连接已断开')); cb.disconnected() } },
      onTransportStateChanged: value => { this.connectionPhase = value === 'connecting' ? '建立本地语音连接' : value === 'ready' || value === 'connected' ? '等待语音服务就绪' : '初始化音频输出' },
      onError: message => {
        if (this.closed) return
        const data = message.data as { error?: unknown; message?: unknown; fatal?: boolean } | undefined
        const reason = String(data?.error ?? data?.message ?? '语音服务出错')
        if (this.connectionFailure) this.connectionFailure(new Error(reason))
        else {
          cb.error(reason)
          if (data?.fatal) void this.disconnect().finally(cb.disconnected).catch(() => {})
        }
      },
      onDeviceError: error => cb.error(`音频设备出错：${error.message}`),
      onUserInput: data => { if (data.final && data.input_type !== 'chat' && data.input_type !== 'backchannel' && data.text.trim()) cb.userText(data.text) },
      onBotLlmText: data => cb.botText(data.text),
      onBotTtsText: () => {},
      onBotTtsStarted: () => cb.ttsStarted?.(),
      onUserStartedSpeaking: cb.userStart,
      onUserStoppedSpeaking: cb.userStop,
      onServerMessage: data => {
        if (this.closed) return
        if (data?.type === 'voice.native.user' && typeof data.text === 'string' && data.text.trim()) cb.userText(data.text)
        if (data?.type === 'voice.screen.request' && typeof data.stream_id === 'string' && typeof data.request_id === 'string' && (data.purpose === undefined || data.purpose === 'tool' || data.purpose === 'intent' || data.purpose === 'idle')) cb.screenRequest?.({stream_id:data.stream_id, request_id:data.request_id, ...(data.purpose === undefined ? {} : {purpose:data.purpose})})
        if (data?.type === 'voice.screen.sample' && typeof data.stream_id === 'string') cb.screenSample?.({stream_id:data.stream_id})
        if (data?.type === 'voice.screen.status') cb.screenStatus?.(data)
        if (data?.type === 'voice.initiative') { const value = initiativeStatus(data); if (value) cb.initiativeStatus?.(value) }
        if (data?.type === 'voice.idle') { const value = presenceStatus(data); if (value) cb.idleStatus?.(value) }
        if (data?.type === 'voice.behavior' && typeof data.epoch === 'string') {
          if (typeof data.reason === 'string') cb.decisionStatus?.(data.reason)
          if (isBehaviorSource(data.source)) { const value = behaviors.receive(data.epoch, data.behavior, data.source); if (value) cb.behavior?.(value) }
        }
        if (data?.type === 'voice.playback.start' && typeof data.epoch === 'string' && data.sample_rate === 24000) {
          if (!this.media.startPlayback(data.epoch)) { this.stop(); cb.error('待播放片段过多，请重新连接后重试。'); return }
          emotions.start(data.epoch)
          behaviors.start(data.epoch)
          if (typeof data.text === 'string') emotions.push(data.epoch, Object.entries(emotionKeywords).find(([, words]) => words.some(word => data.text.includes(word)))?.[0] ?? 'neutral')
        }
        if (data?.type === 'voice.playback.unavailable') { this.stop(); cb.error('播放确认已达上限，请重新连接后重试。') }
        if (data?.type === 'voice.playback.boundary' && typeof data.epoch === 'string' && data.sample_rate === 24000 && typeof data.samples === 'number') {
          if (typeof data.text === 'string') emotions.push(data.epoch, Object.entries(emotionKeywords).find(([, words]) => words.some(word => data.text.includes(word)))?.[0] ?? 'neutral')
          if (!this.media.playbackBoundary(data.epoch, data.samples)) { this.stop(); cb.error('播放确认数据异常，请重新连接后重试。') }
        }
        if (data?.type === 'voice.duck') this.media.duck(Boolean(data.active))
        if (data?.type === 'voice.speaker' && data.accepted !== true) cb.ownerRejected?.(data.reason === 'insufficient_speech' ? '声音太短或不清晰，无法判断是否为本人，请说完整句子。' : data.reason === 'mismatch' ? '本次声音未通过本人声音筛选。' : '本人声音核对暂不可用，请检查本地语音服务。')
      },
      onBotStartedSpeaking: cb.botStart, onBotStoppedSpeaking: cb.botStop,
      onBotInterrupted: () => { emotions.clear(); behaviors.clear(); cb.behavior?.(undefined); cb.emotion('neutral'); this.media.duck(false); this.media.resetLip(); cb.botStop() },
    } })
  }
  async connect(session: string) {
    if (this.closed) throw new Error('语音连接已关闭')
    const url = voiceUrl(session)
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      await Promise.race([
        (async () => {
          // Explicit init propagates worklet failures; the SDK's implicit init
          // runs outside its rejection handler. Check cancellation before WS.
          await this.client.initDevices()
          if (this.closed) throw new Error('语音连接已取消')
          await this.client.connect({ wsUrl: url })
        })(),
        new Promise<never>((_, reject) => {
          this.connectionFailure = reject
          timer = setTimeout(() => reject(new Error(`语音连接超时：${this.connectionPhase}。请确认本地服务已启动后重试。`)), 20000)
        }),
      ])
    } catch (error) {
      this.connectionFailure = undefined
      await this.disconnect().catch(() => {})
      throw error
    } finally { if (timer) clearTimeout(timer); this.connectionFailure = undefined }
  }
  async setMic(enabled: boolean, device?: string) {
    if (enabled && this.closed) throw new Error('Voice session closed')
    const version = ++this.captureVersion
    if (!enabled && !this.closed) this.client.sendClientMessage('voice.capture', { active: false })
    try {
      if (enabled) await this.media.resumeOutput()
      if (enabled && this.closed) return
      await this.media.setMic(enabled, device)
      if (enabled && !this.closed && version === this.captureVersion) this.client.sendClientMessage('voice.capture', { active: true })
    } catch (error) {
      if (!this.closed && version === this.captureVersion) this.client.sendClientMessage('voice.capture', { active: false })
      throw error
    }
  }
  async disconnect() {
    if (this.closing) return this.closing
    this.closed = true; this.submissionVersion++; this.captureVersion++
    this.behaviors.clear(); this.onBehavior?.(undefined)
    this.connectionFailure?.(new Error('语音连接已取消'))
    this.closing = this.client.disconnect()
    return this.closing
  }
  sendScreen(type: string, data: object) { if (this.closed) throw new Error('语音连接已关闭'); this.client.sendClientMessage(type, data) }
  async resumeOutput() { if (this.closed) throw new Error('语音连接已关闭'); await this.media.resumeOutput() }
  async sendText(text: string) { const version = this.submissionVersion; await this.media.resumeOutput(); if (version !== this.submissionVersion) return; await this.client.sendText(text, { run_immediately: true }) }
  stop() { this.submissionVersion++; this.emotions.clear(); this.behaviors.clear(); this.onBehavior?.(undefined); this.onEmotion('neutral'); this.media.duck(false); this.media.resetLip(); void this.media.interruptBotAudio(); this.client.sendClientMessage('voice.stop', {}) }
  setVolume(value: number) { this.media.setVolume(value) }
  level() { return this.media.level() }
  vowels() { return this.media.vowels() }
  lipStatus() { return this.media.lipStatus }
  diagnostics() { return this.media.diagnostics() }
  micDiagnostics() { return this.media.micDiagnostics() }
  async startEnrollment(device?: string) { await this.media.startEnrollment(device) }
  async stopEnrollment() { return this.media.stopEnrollment() }
}



