import { PresencePreferences, presenceDefaults, type PresenceSettings } from './presenceSettings'
import { PersonaSetting } from './personaSettings'
import { NativeConversationSlot, type NativeConversationBridge } from './nativeConversation'
import { ScreenControl, ScreenPreferences, screenDefaults, screenAvailability, handleScreenStatus, type ScreenSettings, type ScreenStatus } from './screenCompanion'
import { apiUrl, modelAssetUrl, isManagedModel, waitForVoiceCleanup, trackVoiceCleanup } from './runtime'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Check, History, Maximize2, Mic, MicOff, Plus, ScrollText, Send, Settings2, Shirt, Square, SwatchBook, Trash2, Volume2, X } from 'lucide-react'
import { Avatar } from './Avatar'
import { VoiceSession, type MicDiagnostics } from './voice'
import { audioInputs, microphoneError } from './microphone'
import { ReconnectBackoff } from './reconnect'
import { SessionIdentity } from './sessionIdentity'
import { OwnerVoice } from './OwnerVoice'
import { settingsUpdate } from './settingsUpdate'
import { localMemories, type Memory } from './memory'
import { SystemOnePreferences, systemOneDefaults, decisionReasons, type SystemOneSettings, type SavedDecisionConfig } from './systemoneSettings'
import { behaviorExpressions, behaviorSources, type AppliedBehavior } from './behavior'
import { TTSPreferences, ttsDefaults, type TTSSettings, type TTSStatus } from './ttsSettings'
import { Backdrop } from './ui/Backdrop'
import { Waveform } from './ui/Waveform'
import { WardrobePanel } from './ui/WardrobePanel'
import { loadTheme, subtitleTail, themes, timecode, type Theme } from './ui/theme'
import { loadWardrobe, wardrobeTargets, type Activity, type Wardrobe } from './avatar/wardrobe'

type Message = { id: string; role: 'user' | 'assistant'; content: string; interrupted?: boolean; created_at?: string }
type Session = { id: string; title: string; created_at: string }
type Settings = TTSSettings & SystemOneSettings & ScreenSettings & PresenceSettings & { llm_base_url: string; llm_model: string; llm_api_key: string; api_key_set?: boolean; owner_voice_only?: boolean; harness_provider?: string; memory_owner?: string; streaming_asr_preview?: boolean; system_prompt: string; speech_base_url: string; temperature: number }
import type { OptionalService } from './serviceStatus'
type Status = { conversation?: { mode?: TTSSettings['conversation_mode'] }; tts?: TTSStatus; llm?: { ready: boolean; detail?: string; model?: string; needs_api_key?: boolean }; speech?: { ready: boolean; detail?: string; asr?: { device?: string; detail?: string }; tts?: { device?: string; detail?: string } }; optional?: { index_tts?: OptionalService; moss_tts?: OptionalService } }
const defaults: Settings = { ...ttsDefaults, ...systemOneDefaults, ...screenDefaults, ...presenceDefaults, llm_base_url: 'https://api.deepseek.com/v1', llm_model: 'deepseek-chat', llm_api_key: '', system_prompt: '', speech_base_url: 'http://127.0.0.1:8766', voice: '', temperature: 0.7, tts_engine: 'local', cosyvoice_url: 'http://127.0.0.1:8770' }
const labels: Record<string, string> = { idle: '准备就绪', listening: '正在聆听', transcribing: '正在识别', thinking: '正在思考', preparing: '正在准备语音', speaking: '正在回应', disconnected: '连接中断' }
const defaultModel = '/models/deepseek/avatar.model3.json'
const initialModel = () => { const saved = localStorage.getItem('avatar-model-url'); return saved === null || saved === '/models/haru/Haru.model3.json' ? defaultModel : saved }
const emotionLabels: Record<string, string> = { neutral: '平静', happy: '开心', sad: '难过', surprised: '惊讶' }
const store = { get: (key: string) => { try { return localStorage.getItem(key) } catch { return null } }, set: (key: string, value: string) => { try { localStorage.setItem(key, value) } catch { /* storage unavailable */ } } }
const uid = () => `${Date.now()}-${Math.random()}`
const json = async (path: string, init?: RequestInit) => { const r = await fetch(apiUrl(path), init); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); return r.json() }

export function App({ embedHost, active = true, nativeConversation }: { embedHost?: HTMLElement; active?: boolean; nativeConversation?: NativeConversationBridge } = {}) {
  const embedded = !!embedHost
  const nativeChat = embedded ? nativeConversation : undefined
  // Panel/tab visibility controls rendering only, never an authorized interaction.
  const [documentVisible, setDocumentVisible] = useState(() => !document.hidden)
  const renderActive = active && documentVisible
  const mountedRef = useRef(true)
  const identityRef = useRef(new SessionIdentity())
  const [session, setSession] = useState(''), [sessions, setSessions] = useState<Session[]>([]), [messages, setMessages] = useState<Message[]>([])
  const [state, setState] = useState('idle'), [connected, setConnected] = useState(false), [listening, setListening] = useState(false), [playing, setPlaying] = useState(false)
  const [settings, setSettings] = useState<Settings>(defaults), [status, setStatus] = useState<Status>({}), [panel, setPanel] = useState<'settings' | 'history' | 'avatar' | null>(null)
  const voiceOnly = status.conversation?.mode === 'moss_live'
  const [input, setInput] = useState(''), [notice, setNotice] = useState(''), [emotion, setEmotion] = useState('neutral'), [micLevel, setMicLevel] = useState(0), [expression, setExpression] = useState('')
  const [memories, setMemories] = useState<Memory[]>([]), [memoryInput, setMemoryInput] = useState(''), [memoryError, setMemoryError] = useState('')
  const [motionEnabled, setMotionEnabled] = useState(() => { const stored = localStorage.getItem('avatar-motion-enabled'); return stored === null ? !window.matchMedia('(prefers-reduced-motion: reduce)').matches : stored === 'true' })
  const [motionStrength, setMotionStrength] = useState(() => { const raw = localStorage.getItem('avatar-motion-strength'); const value = raw === null ? .6 : Number(raw); return Number.isFinite(value) ? Math.max(.1, Math.min(1, value)) : .6 })
  const [modelUrl, setModelUrl] = useState(initialModel), [stage, setStage] = useState(false), [volume, setVolume] = useState(0.85), [devices, setDevices] = useState<MediaDeviceInfo[]>([]), [deviceId, setDeviceId] = useState('')
  const [micTransition, setMicTransition] = useState(false)
  const [micDiagnostics, setMicDiagnostics] = useState<MicDiagnostics>()
  const [deviceNotice, setDeviceNotice] = useState('')
  const [canContinue, setCanContinue] = useState(false)
  const [behavior, setBehavior] = useState<AppliedBehavior>(), [decisionStatus, setDecisionStatus] = useState('')
  const [screenSaved, setScreenSaved] = useState<Settings>(defaults), [screenStatus, setScreenStatus] = useState<ScreenStatus>(), [screenStop, setScreenStop] = useState(0)
  const [initiativeStatus, setInitiativeStatus] = useState('')
  const [idleStatus, setIdleStatus] = useState('')
  const [savedDecision, setSavedDecision] = useState<SavedDecisionConfig>(systemOneDefaults)
  const shownEmotion = behavior?.emotion || emotion
  const [theme, setTheme] = useState<Theme>(() => loadTheme(store.get('ui-theme'))), [wardrobe, setWardrobe] = useState<Wardrobe>(() => loadWardrobe(store.get('avatar-wardrobe')))
  const [logOpen, setLogOpen] = useState(() => { const saved = store.get('ui-log-open'); return saved === null ? (embedHost?.clientWidth ?? window.innerWidth) > 980 : saved === 'true' }), [connectedAt, setConnectedAt] = useState(0), [now, setNow] = useState(() => Date.now())
  const [lipDiagnostics, setLipDiagnostics] = useState('元音口型初始化中')
  const [lipProfile, setLipProfile] = useState<'local-vits' | 'airi'>(() => localStorage.getItem('lip-profile') === 'local-vits' ? 'local-vits' : 'airi')
  const lipProfileRef = useRef(lipProfile); lipProfileRef.current = lipProfile
  const volumeRef = useRef(volume); volumeRef.current = volume
  const voiceRef = useRef<VoiceSession>(), versionRef = useRef(0), micBusy = useRef(false), endRef = useRef<HTMLDivElement>(null), retryRef = useRef(new ReconnectBackoff())
  const messagesRef = useRef(messages); messagesRef.current = messages
  const refreshSessions = useCallback(() => { void json('/api/sessions').then(setSessions).catch(() => {}) }, [])
  const refreshStatus = useCallback(() => { void json('/api/status').then((value: Status) => { setStatus(value); if (!embedHost && value.llm?.needs_api_key) setNotice('请先在设置中填写有效的模型 API 密钥。') }).catch(() => setStatus({})) }, [embedHost])
  useEffect(() => {
    if (!renderActive || (status.tts?.state !== 'loading' && status.tts?.state !== 'warming')) return
    const timer = window.setInterval(refreshStatus, 2000)
    return () => window.clearInterval(timer)
  }, [renderActive, status.tts?.state, refreshStatus])
  const refreshDevices = useCallback(async () => {
    try { const inputs = await audioInputs(); setDevices(inputs); setDeviceNotice(inputs.length ? '' : '浏览器未列出可用麦克风，请检查 Windows 的声音输入设备与网站权限。') }
    catch (error) { setDeviceNotice(microphoneError(error)) }
  }, [])
  useEffect(() => {
    void refreshDevices()
    navigator.mediaDevices?.addEventListener('devicechange', refreshDevices)
    return () => navigator.mediaDevices?.removeEventListener('devicechange', refreshDevices)
  }, [refreshDevices])
  const connect = useCallback(async function connect(requested = '') {
    if (!mountedRef.current) return
    if (requested && requested !== identityRef.current.id) identityRef.current.select(requested)
    window.dispatchEvent(new Event('screen-companion-stop')); setScreenStop(n => n + 1); setScreenStatus(undefined)
    retryRef.current.cancel()
    let retrySession = requested
    const version = ++versionRef.current, previous = voiceRef.current; voiceRef.current = undefined
    if (previous) trackVoiceCleanup(previous.disconnect())
    await waitForVoiceCleanup()
    if (version !== versionRef.current) return
    setConnected(false); setListening(false); setPlaying(false); setState('idle'); setMicDiagnostics(undefined); setCanContinue(false); setInitiativeStatus(''); setIdleStatus('')
    try {
      const id = await identityRef.current.ensure(async () => (await json('/api/sessions', { method: 'POST' })).id)
      if (!id) return
      retrySession = id
      if (version !== versionRef.current) return
      setSession(id)
      let botSpeaking = false
      const voice = new VoiceSession({
        connected: () => { if (version === versionRef.current) { retryRef.current.reset(); setConnected(true); setConnectedAt(Date.now()); setNotice('') } },
        disconnected: () => { if (version === versionRef.current) { window.dispatchEvent(new Event('screen-companion-stop')); setScreenStop(n => n + 1); setConnected(false); setListening(false); setMicDiagnostics(undefined); setPlaying(false); setState('disconnected'); const delay = retryRef.current.schedule(() => { if (version === versionRef.current) void connect(id) }); if (delay) setNotice(`语音连接中断，${delay / 1000} 秒后重试。`) } },
        error: message => { if (version === versionRef.current) { setNotice(message); setPlaying(false); setEmotion('neutral'); setState('idle') } },
        ownerRejected: message => { if (version === versionRef.current) { setNotice(message); setState(botSpeaking ? 'speaking' : 'listening') } },
        userText: text => { if (version === versionRef.current) { setState('thinking'); setCanContinue(false); setMessages(items => [...items, { id: uid(), role: 'user', content: text }]) } },
        botText: text => { if (version !== versionRef.current) return; setState(current => current === 'preparing' || current === 'speaking' ? current : 'thinking'); setMessages(items => { const copy = [...items], last = copy.at(-1); if (last?.role === 'assistant') copy[copy.length - 1] = { ...last, content: last.content + text }; else copy.push({ id: uid(), role: 'assistant', content: text }); return copy }) },
        emotion: value => { if (version === versionRef.current) setEmotion(value) },
        behavior: value => { if (version === versionRef.current) setBehavior(value) },
        decisionStatus: reason => { if (version === versionRef.current) setDecisionStatus(decisionReasons[reason] || '判断状态未知') },
        screenRequest: value => { if (version === versionRef.current) window.dispatchEvent(new CustomEvent('screen-companion-request', {detail:value})) },
        screenSample: value => { if (version === versionRef.current) window.dispatchEvent(new CustomEvent('screen-companion-sample', {detail:value})) },
        screenStatus: value => { if (version === versionRef.current) handleScreenStatus(value, () => window.dispatchEvent(new Event('screen-companion-stop')), setScreenStatus) },
        initiativeStatus: value => { if (version === versionRef.current) setInitiativeStatus(value) },
        idleStatus: value => { if (version === versionRef.current) setIdleStatus(value) },
        ttsStarted: () => { if (version === versionRef.current) setState('preparing') },
        botStart: () => { botSpeaking = true; if (version === versionRef.current) { setPlaying(true); setState('speaking') } },
        botStop: () => { botSpeaking = false; if (version === versionRef.current) { setPlaying(false); setEmotion('neutral'); setState('listening'); refreshSessions() } },
        userStart: () => { if (version === versionRef.current) setState('listening') },
        userStop: () => { if (version === versionRef.current) setState('transcribing') },
      }, lipProfileRef.current)
      voiceRef.current = voice; voice.setVolume(volumeRef.current); await voice.connect(id)
      if (version !== versionRef.current) await voice.disconnect()
    } catch (error) { if (version === versionRef.current) { setConnected(false); setNotice(`语音连接失败：${String(error)}`); retryRef.current.schedule(() => { if (version === versionRef.current) void connect(retrySession) }) } }
  }, [refreshSessions])
  // The retained application owns the connection. A keyed panel detach or a
  // hidden tab is not a stop command: keep mic, output, screen and generation.
  useLayoutEffect(() => {
    mountedRef.current = true
    void connect()
    return () => {
      mountedRef.current = false
      retryRef.current.cancel(); versionRef.current++
      window.dispatchEvent(new Event('screen-companion-stop'))
      const voice = voiceRef.current; voiceRef.current = undefined
      if (voice) trackVoiceCleanup(voice.disconnect())
    }
  }, [connect])
  useEffect(() => {
    const changed = () => setDocumentVisible(!document.hidden)
    document.addEventListener('visibilitychange', changed)
    return () => document.removeEventListener('visibilitychange', changed)
  }, [])
  useEffect(() => {
    let alive = true
    void json('/api/settings').then((x: Partial<Settings>) => {
      if (!alive) return
      const loaded = { ...defaults, ...x, llm_api_key: '', moss_live_api_key: '', clear_moss_live_api_key: false, tts_api_key: '', systemone_api_key: '', clear_systemone_api_key: false, systemone_ark_api_key: '', clear_systemone_ark_api_key: false }
      setSettings(loaded); setSavedDecision(loaded); setScreenSaved(loaded)
    }).catch(() => {})
    return () => { alive = false }
  }, [])
  useEffect(() => {
    if (!renderActive) return
    refreshStatus(); refreshSessions(); const timer = window.setInterval(refreshStatus, 15000)
    return () => window.clearInterval(timer)
  }, [renderActive, refreshSessions, refreshStatus])
  // Scroll only the transcript list; scrollIntoView would also scroll the clipped screen when the log is hidden.
  useEffect(() => { const list = endRef.current?.parentElement; if (list) list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' }) }, [messages])
  useEffect(() => { voiceRef.current?.setVolume(volume) }, [volume])
  useEffect(() => { if (!renderActive) return; const timer = window.setInterval(() => { setLipDiagnostics(voiceRef.current?.lipStatus() || '语音未连接'); setNow(Date.now()) }, 1000); return () => window.clearInterval(timer) }, [renderActive])
  useEffect(() => { const changed = () => { if (!document.fullscreenElement) setStage(false) }; document.addEventListener('fullscreenchange', changed); return () => document.removeEventListener('fullscreenchange', changed) }, [])
  const exitStage = useCallback(() => { setStage(false); if (document.fullscreenElement === (embedHost || document.documentElement)) void document.exitFullscreen().catch(() => {}) }, [embedHost])
  useEffect(() => { if (!stage) return; const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') exitStage() }; document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey) }, [stage, exitStage])
  useEffect(() => { if (panel === 'settings') void localMemories(embedded).then(setMemories).catch(() => setMemoryError('无法加载记忆。')) }, [panel, embedded])
  const interrupt = () => {
    const id = messagesRef.current.at(-1)?.role === 'assistant' ? messagesRef.current.at(-1)?.id : undefined
    voiceRef.current?.stop(); setPlaying(false); setState('idle'); setCanContinue(!voiceOnly)
    if (!id) return
    setMessages(items => items.map(item => item.id === id ? { ...item, interrupted: true } : item))
  }
  const continueAnswer = () => { if (voiceOnly || !connected || !voiceRef.current) return; const text = '请接着刚才中断的回答继续说，已说过的部分不用重复；如果缺少必要上下文，请先问我。'; setCanContinue(false); setState('thinking'); setMessages(items => [...items, { id: uid(), role: 'user', content: text }]); void voiceRef.current.sendText(text).catch(error => { setState('idle'); setNotice(`发送失败：${String(error)}`) }) }
  const switchMic = async () => {
    if (micBusy.current || !voiceRef.current || !connected) return
    micBusy.current = true; setMicTransition(true)
    const voice = voiceRef.current, version = versionRef.current
    try { const next = !listening; await voice.setMic(next, deviceId); if (version !== versionRef.current) { await voice.setMic(false); return }; setListening(next); setMicDiagnostics(next ? voice.micDiagnostics() : undefined); setNotice('') }
    catch (error) { if (version === versionRef.current) { setListening(false); setMicDiagnostics(undefined); setNotice(`麦克风启动失败：${microphoneError(error)}`) } }
    finally { micBusy.current = false; setMicTransition(false); void refreshDevices() }
  }
  const sendText = () => { if (voiceOnly) { setNotice('MOSS-Live 模式请开启麦克风对话；输入文字请先切换语音对话方式。'); return };
    const text = input.trim(); if (!text || !connected) return
    setCanContinue(false); setState('thinking'); setMessages(items => [...items, { id: uid(), role: 'user', content: text }]); setInput('')
    void voiceRef.current?.sendText(text).catch(error => { setState('idle'); setNotice(`发送失败：${String(error)}`) })
  }
  const newSession = () => { identityRef.current.select(); setSession(''); setMessages([]); void connect(); setPanel(null) }
  const selectSession = async (id: string) => { window.dispatchEvent(new Event('screen-companion-stop')); setScreenStop(n => n + 1); try { const entries = await json(`/api/sessions/${encodeURIComponent(id)}/messages`); setMessages(entries); void connect(id); setPanel(null) } catch { setNotice('无法读取会话记录。') } }
  const saveSettings = async () => {
    window.dispatchEvent(new Event('screen-companion-stop')); setScreenStop(n => n + 1)
    const invalid = (embedHost?.shadowRoot || document).querySelector<HTMLInputElement>('.systemone-parameters input:invalid, .screen-parameters input:invalid, .presence-parameters input:invalid')
    if (invalid) {
      // Advanced fields can be collapsed; expose the error before focusing it.
      invalid.closest('details')?.setAttribute('open', '')
      invalid.reportValidity()
      setNotice('请填写有效的交互参数，数值范围见各项说明。')
      return
    }
    try { const result = await json('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(settingsUpdate(embedded ? { ...settings, harness_provider: 'dsh', memory_owner: 'dsh' } : settings)) }); setSettings({ ...defaults, ...result, llm_api_key: '', moss_live_api_key: '', clear_moss_live_api_key: false, tts_api_key: '', clear_tts_api_key: false, systemone_api_key: '', clear_systemone_api_key: false, systemone_ark_api_key: '', clear_systemone_ark_api_key: false }); setSavedDecision(result); setScreenSaved({ ...defaults, ...result }); setDecisionStatus(''); localStorage.setItem('avatar-model-url', modelUrl.trim()); setNotice('设置已保存'); refreshStatus(); setPanel(null); void connect(session) } catch (e) { setNotice(`保存失败：${String(e)}`) }
  }
  const addMemory = async () => {
    const content = memoryInput.trim(); if (!content) return
    try { const entry = await json('/api/memories', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ content }) }); setMemories(items => [entry, ...items]); setMemoryInput(''); setMemoryError('') } catch { setMemoryError('保存记忆失败。') }
  }
  const removeMemory = async (id: string) => {
    try { await json(`/api/memories/${encodeURIComponent(id)}`, { method: 'DELETE' }); setMemories(items => items.filter(item => item.id !== id)); setMemoryError('') } catch { setMemoryError('删除记忆失败。') }
  }
  const requestFullscreen = () => { if (stage) { exitStage(); return }; setStage(true); void (embedHost || document.documentElement).requestFullscreen?.().catch(() => {}) }
  useEffect(() => { (embedHost || document.documentElement).dataset.theme = theme; if (!embedHost) document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themes[theme].color); store.set('ui-theme', theme) }, [theme, embedHost])
  useEffect(() => { store.set('avatar-wardrobe', JSON.stringify(wardrobe)) }, [wardrobe])
  useEffect(() => { store.set('ui-log-open', String(logOpen)) }, [logOpen])
  const busy = state === 'thinking' || state === 'transcribing' || state === 'preparing'
  const stateLabel = playing ? '正在回应' : busy ? labels[state] : listening ? labels[state] || '正在聆听' : '等待开始'
  const activity: Activity = playing ? 'speaking' : busy ? 'thinking' : listening ? 'listening' : 'idle'
  const layers = useMemo(() => modelUrl.includes('/models/deepseek/') ? wardrobeTargets(wardrobe, activity, behavior?.gesture) : {}, [wardrobe, activity, modelUrl, behavior?.gesture])
  const lastUser = [...messages].reverse().find(m => m.role === 'user'), lastBot = messages.at(-1)?.role === 'assistant' ? messages.at(-1) : undefined
  const mark = playing ? 'play' : listening ? 'rec' : 'pause'
  const deepseekModel = modelUrl.includes('/models/deepseek/')
  const drawerTitle = { settings: ['PREFERENCES', '设置'], history: ['ARCHIVE', '历史会话'], avatar: ['APPEARANCE', '形象'] } as const
  return <div className={`app ${stage ? 'stage-mode' : ''} ${logOpen ? 'log-open' : ''}`} data-activity={activity} data-active={renderActive}>
    <div className="bezel" aria-hidden="true"><i className="screw tl"/><i className="screw tr"/><i className="screw bl"/><i className="screw br"/><span className="bezel-led"/></div>
    <div className="screen">
      <Backdrop theme={theme} animated={motionEnabled && renderActive}/>
      <section className="stage-scene" aria-label="角色舞台">
        <div className="hologram-glow" aria-hidden="true"/>
        <Avatar active={renderActive} embeddedBuiltin={embedded && isManagedModel(modelUrl)} modelUrl={embedded ? modelAssetUrl(modelUrl) : modelUrl} level={() => voiceRef.current?.level() || 0} vowels={() => voiceRef.current?.vowels()} emotion={shownEmotion} listening={listening} expression={expression} autoExpression={deepseekModel && behavior?.expression ? behaviorExpressions[behavior.expression] : undefined} speaking={playing} motionEnabled={motionEnabled} motionStrength={Math.min(1, motionStrength * (behavior?.energy === undefined ? 1 : .5 + behavior.energy))} layers={layers} zoom={stage ? 1 : theme === 'yaya' ? .8 : .9}/>
        <div className="hologram-lines" aria-hidden="true"/>
      </section>
      <div className="fx" aria-hidden="true"><div className="fx-scan"/><div className="fx-noise"/><div className="fx-vignette"/></div>

      {stage && <button className="exit-stage" onClick={exitStage}><X size={16}/> 退出全屏</button>}

      <header className="topbar">
        <div className="brand"><span className="brand-glyph" aria-hidden="true">鱼</span><div><strong>大肥鱼</strong><small>DEEPSEEK-CHAN · {themes[theme].tagline}</small></div></div>
        <div className="top-status"><span className={`status-dot ${connected ? 'on' : ''}`}/><span>{connected ? '本地服务已连接' : '正在连接服务'}</span><span className="top-sep" aria-hidden="true"/><span className="top-model">{status.llm?.model || (embedded ? 'DSH' : settings.llm_model) || '未配置模型'}</span></div>
        <nav className="top-actions">
          <button className="tool" title={`切换为${themes[theme === 'yaya' ? 'replicant' : 'yaya'].name}`} aria-label="切换主题" onClick={() => setTheme(theme === 'yaya' ? 'replicant' : 'yaya')}><SwatchBook size={17}/><span>{themes[theme].name}</span></button>
          <button className="tool" title="形象" aria-label="形象" onClick={() => setPanel('avatar')}><Shirt size={17}/><span>形象</span></button>
          <button className={`tool ${logOpen ? 'active' : ''}`} title="对话记录" aria-label="对话记录" aria-pressed={logOpen} onClick={() => setLogOpen(!logOpen)}><ScrollText size={17}/><span>记录</span></button>
          <button className="tool" title="历史会话" aria-label="历史会话" onClick={() => { refreshSessions(); setPanel('history') }}><History size={17}/></button>
          <button className="tool" title="新对话" aria-label="新对话" onClick={newSession}><Plus size={17}/></button>
          <button className="tool" title="设置" aria-label="设置" onClick={() => { refreshStatus(); setPanel('settings') }}><Settings2 size={17}/></button>
          <button className="tool" title="全屏" aria-label="全屏" onClick={requestFullscreen}><Maximize2 size={16}/></button>
        </nav>
      </header>

      {screenSaved.screen_companion_enabled && <ScreenControl enabled={!screenAvailability(screenSaved, connected, micTransition, voiceOnly)} disabledReason={screenAvailability(screenSaved, connected, micTransition, voiceOnly)} settings={screenSaved} stopKey={screenStop} status={screenStatus} prepareAudio={() => { void voiceRef.current?.resumeOutput().catch(error => setNotice(`语音播放启动失败：${String(error)}`)) }} send={(type, data) => { if (!voiceRef.current) throw Error('语音未连接'); voiceRef.current.sendScreen(type, data) }}/>}
      <aside className="hud" aria-label="运行状态">
        <div className="hud-block"><h4><span>SUBJECT</span>对象</h4>
          <dl><dt>名称</dt><dd>DeepSeek-chan</dd><dt>会话</dt><dd>{session ? session.slice(0, 8).toUpperCase() : '——'}</dd><dt>消息</dt><dd>{messages.length}</dd></dl></div>
        <div className="hud-block"><h4><span>LINK</span>链路</h4>
          <dl>
            <dt>对话</dt><dd><span className={`status-dot ${status.llm?.ready ? 'on' : ''}`}/>{status.llm?.ready ? '就绪' : '未就绪'}</dd>
            <dt>识别</dt><dd><span className={`status-dot ${status.speech?.asr ? 'on' : ''}`}/>{status.speech?.asr?.device || '——'}</dd>
            <dt>合成</dt><dd><span className={`status-dot ${status.tts?.ready ? 'on' : ''}`}/>{status.tts?.provider || '待配置'} · {status.tts?.device || (status.tts?.configured ? '待验证' : '未就绪')}</dd>
            <dt>麦克风</dt><dd><span className={`status-dot ${listening ? 'on rec' : ''}`}/>{listening ? '开启' : '关闭'}</dd>
          </dl></div>
        <div className="hud-block"><h4><span>AFFECT</span>情绪</h4>
          <div className="affect"><strong>{expression || emotionLabels[shownEmotion] || shownEmotion}</strong><small>{expression ? '手动表情' : behavior ? behaviorSources[behavior.source] : '对话自动'}</small></div>
          <div className="meter" aria-hidden="true">{['neutral', 'happy', 'sad', 'surprised'].map(key => <i key={key} className={!expression && shownEmotion === key ? 'on' : ''} title={emotionLabels[key]}/>)}</div></div>
        <div className="hud-block"><h4><span>SYNC</span>口型</h4><p className="hud-note">{lipDiagnostics}</p></div>
      </aside>

      <section className="conversation" aria-label="对话记录">
        <div className="conversation-header"><h2><span>TRANSCRIPT</span>对话记录</h2><button className="tool" title="收起记录" aria-label="收起记录" onClick={() => setLogOpen(false)}><X size={15}/></button></div>
        {nativeChat ? <div className="message-list native-message-list"><NativeConversationSlot bridge={nativeChat} sessionId={session} target="messages"/></div> : <div className="message-list">{messages.length === 0 ? <div className="welcome"><span>NO SIGNAL YET</span><p>输入文字，或开启语音和她聊聊。</p></div> : messages.map(m => <div key={m.id} className={`message ${m.role}`}><div className="message-author">{m.role === 'assistant' ? '大肥鱼' : '你'} <span>{m.interrupted ? '已中断 · 以下为生成文本，未必全部播放' : ''}</span></div><div className="message-text">{m.content || (m.role === 'assistant' ? '...' : '')}</div></div>)}<div ref={endRef}/></div>}
      </section>

      <div className="subtitles">
        {lastUser && <p className="sub-user"><span>你</span>{subtitleTail(lastUser.content, 40)}</p>}
        {lastBot ? <p className="sub-bot">{subtitleTail(lastBot.content, 46) || '…'}</p> : busy ? <p className="sub-bot thinking">{stateLabel}<i/><i/><i/></p> : !messages.length && <p className="sub-bot idle">你好，我是大肥鱼。今天想聊点什么？</p>}
      </div>

      {notice && <div className="notice" role="status">{notice}<button aria-label="关闭提示" onClick={() => setNotice('')}><X size={14}/></button></div>}

      <footer className="console">
        <div className="timecode"><span className={`tc-mark ${mark}`} aria-hidden="true"/><span className="tc-time">{timecode(connected && connectedAt ? now - connectedAt : 0)}</span></div>
        <div className="console-state"><small>STATUS</small><strong><span className={`status-dot ${listening || playing ? 'on' : ''}`}/>{stateLabel}</strong></div>
        <Waveform level={() => voiceRef.current?.level() || 0} active={playing} running={renderActive}/>
        <div className="compose">
          <button className={`mic-btn ${listening ? 'listening' : ''}`} aria-label={listening ? '正在聆听' : '开启语音'} onClick={() => void switchMic()} disabled={!connected}>{listening ? <Mic size={16}/> : <MicOff size={16}/>}<span>{listening ? '正在聆听' : '开启语音'}</span></button>
          {nativeChat ? <><NativeConversationSlot bridge={nativeChat} sessionId={session} target="composer"/>{(playing || busy) && <button className="stop-btn" onClick={interrupt}><Square size={11} fill="currentColor"/> 停止</button>}</> : <>
          <input disabled={voiceOnly} placeholder={voiceOnly ? "MOSS-Live 模式请使用麦克风对话" : "说点什么，或开启语音..."} value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) sendText() }}/>
          {(playing || busy) ? <button className="stop-btn" onClick={interrupt}><Square size={11} fill="currentColor"/> 停止</button>
            : !voiceOnly && canContinue && connected && <button className="continue-btn" onClick={continueAnswer}>继续刚才的回答</button>}
          <button className="send-btn" title="发送" aria-label="发送" disabled={voiceOnly || !input.trim() || !connected} onClick={sendText}><Send size={16}/></button>
          </>}
        </div>
        <label className="volume" title="音量"><Volume2 size={15}/><input aria-label="音量" type="range" min="0" max="1" step="0.05" value={volume} onChange={e => setVolume(Number(e.target.value))}/></label>
      </footer>
    </div>

    {panel && <div className="overlay" onMouseDown={() => setPanel(null)}><aside className="drawer" onMouseDown={e => e.stopPropagation()}><div className="drawer-top"><div><span className="eyebrow">{drawerTitle[panel][0]}</span><h2>{drawerTitle[panel][1]}</h2></div><button className="tool" title="关闭" aria-label="关闭" onClick={() => setPanel(null)}><X size={18}/></button></div>
      {panel === 'avatar' ? <WardrobePanel wardrobe={wardrobe} onChange={setWardrobe} expression={expression} onExpression={setExpression} enabled={deepseekModel}/>
      : panel === 'history' ? <div className="drawer-content"><button className="wide-btn" onClick={newSession}><Plus size={17}/> 开始新对话</button><div className="session-list">{sessions.length ? sessions.map(s => <button key={s.id} className={`session-item ${s.id === session ? 'selected' : ''}`} onClick={() => void selectSession(s.id)}><History size={15}/><span><strong>{s.title || '新对话'}</strong><small>{s.created_at ? new Date(s.created_at).toLocaleString('zh-CN') : ''}</small></span></button>) : <p className="empty">还没有历史会话</p>}</div></div>
      : <div className="drawer-content settings-form">
        <section className="group"><h3>服务状态</h3><div className="service-status"><div><span className={`status-dot ${status.llm?.ready ? 'on' : ''}`}/> 对话模型 <small>{status.llm?.detail || (status.llm?.ready ? '可用' : '未就绪')}</small></div><div><span className={`status-dot ${status.speech?.ready ? 'on' : ''}`}/> 本地语音 <small>{status.speech?.detail || (status.speech?.ready ? '可用' : '未就绪')}</small></div>{status.speech?.asr && <div>语音识别 <small>{[status.speech.asr.device, status.speech.asr.detail].filter(Boolean).join(' · ')}</small></div>}{status.speech?.tts && <div>语音合成 <small>{[status.speech.tts.device, status.speech.tts.detail].filter(Boolean).join(' · ')}</small></div>}</div></section>
        <section className="group"><h3>对话模型</h3>{embedded ? <div className="service-status"><div>模型由 DSH 管理 <small>{status.llm?.detail || (status.llm?.ready ? '可用' : '等待 DSH 模型配置')}</small></div><div>模型 <small>{status.llm?.model || 'DSH'}</small></div><label>温度<input aria-label="DSH 温度" disabled value="由 DSH 管理" readOnly/></label><small>模型、密钥与温度请在 DSH 中配置。</small></div> : <><label>API 地址<input value={settings.llm_base_url} onChange={e => setSettings({ ...settings, llm_base_url: e.target.value })} placeholder="http://127.0.0.1:11434/v1"/></label><label>模型名称<input value={settings.llm_model} onChange={e => setSettings({ ...settings, llm_model: e.target.value })} placeholder="模型名称"/></label><label>API 密钥<input type="password" autoComplete="off" value={settings.llm_api_key} onChange={e => setSettings({ ...settings, llm_api_key: e.target.value })} placeholder={settings.api_key_set ? '已设置，留空保持不变' : '本地模型可留空'}/></label></>}<PersonaSetting embedded={embedded} value={settings.system_prompt} onChange={value => setSettings({ ...settings, system_prompt: value })}/></section>
        <section className="group"><h3>语音与设备</h3><label>本地语音服务<input value={settings.speech_base_url} onChange={e => setSettings({ ...settings, speech_base_url: e.target.value })}/></label><label>麦克风<select value={deviceId} onChange={e => setDeviceId(e.target.value)} disabled={listening}><option value="">系统默认</option>{deviceId && !devices.some(d => d.deviceId === deviceId) && <option value={deviceId}>已断开的设备（请重新选择）</option>}{devices.filter(d => d.deviceId).map(d => <option key={d.deviceId} value={d.deviceId}>{d.label || '麦克风（允许访问后显示名称）'}</option>)}</select><small>更换设备前请先关闭语音。</small></label><button type="button" onClick={() => void refreshDevices()}>刷新麦克风列表</button>{deviceNotice && <small role="status">{deviceNotice}</small>}
          {micDiagnostics && <div className="service-status"><div>浏览器麦克风设置 <small>{(['echoCancellation', 'noiseSuppression', 'autoGainControl'] as const).map((key, i) => `${['回声消除', '降噪', '自动增益'][i]}：${!micDiagnostics.supported[key] ? '不支持' : micDiagnostics.settings[key] === undefined ? '未报告' : micDiagnostics.settings[key] ? '开启' : '关闭'}`).join(' · ')}</small></div><div>采样率 <small>{!micDiagnostics.supported.sampleRate ? '不支持报告' : micDiagnostics.settings.sampleRate ? `${micDiagnostics.settings.sampleRate} Hz` : '未报告'}</small></div><small>浏览器报告开启不代表已测得回声消除效果。</small></div>}</section>
        <div className="group"><OwnerVoice voice={voiceRef.current} device={deviceId} stopChat={async () => { voiceRef.current?.stop(); await voiceRef.current?.setMic(false); setPlaying(false); setListening(false); setMicDiagnostics(undefined) }} onRemoved={() => void connect(session)}/></div>
        <PresencePreferences settings={settings} native={settings.conversation_mode === 'moss_live'} dsh={embedded || settings.harness_provider === 'dsh'} runtime={idleStatus} onChange={patch => setSettings({ ...settings, ...patch })}/>
        <ScreenPreferences settings={settings} onChange={patch => setSettings({ ...settings, ...patch })}/>
        <SystemOnePreferences settings={settings} saved={savedDecision} onChange={patch => setSettings({ ...settings, ...patch })} native={settings.conversation_mode === 'moss_live'} runtime={decisionStatus} conversationMode={settings.conversation_mode} ownerOnly={settings.owner_voice_only} initiativeRuntime={initiativeStatus}/>
        <section className="group"><h3>语音合成与口型</h3><label className="motion-setting"><input type="checkbox" checked={!!settings.streaming_asr_preview} onChange={e => setSettings({ ...settings, streaming_asr_preview: e.target.checked })}/>更快响应插话（实验）</label><small>启用后保存设置生效。开启仅回应本人声音时，仍会先核对声音，不使用提前打断。</small>
          <TTSPreferences settings={settings} onChange={patch => setSettings({ ...settings, ...patch })} status={status.tts} optional={status.optional}/>
          <small>口型：{lipDiagnostics}</small>
          <label>口型声线<select aria-label="口型声线" value={lipProfile} onChange={e => { const value = e.target.value === 'airi' ? 'airi' : 'local-vits'; localStorage.setItem('lip-profile', value); lipProfileRef.current = value; setLipProfile(value); void connect(session) }}><option value="airi">通用元音模板（当前 TTS）</option><option value="local-vits">旧 VITS 专用模板</option></select><small>通用模板未针对当前音色校准，口型为近似结果；旧 VITS 模板仅用于原声线。</small></label></section>
        <section className="group"><h3>角色形象</h3><label>Live2D 模型地址<input value={modelUrl} onChange={e => setModelUrl(e.target.value)} placeholder="/models/character/character.model3.json"/><small>默认使用提供的 DeepSeek-chan（大肥鱼）模型。其他模型需要 Cubism 4 与同源资源；留空显示示意角色。角色素材请按其作者提供的许可使用。</small></label><label className="motion-setting"><input type="checkbox" checked={motionEnabled} onChange={e => { setMotionEnabled(e.target.checked); localStorage.setItem('avatar-motion-enabled', String(e.target.checked)) }}/>自然动作</label><label>动作幅度<input type="range" min="0.1" max="1" step="0.1" aria-label="动作幅度" value={motionStrength} disabled={!motionEnabled} onChange={e => { const value = Number(e.target.value); setMotionStrength(value); localStorage.setItem('avatar-motion-strength', String(value)) }}/></label><small>关闭自然动作时同时停用雨幕动画。配件、表情和手势在顶栏“形象”中设置。</small><small>DeepSeek-chan（大肥鱼） · 原画及拆分：神宫凉子 · Live2D 建模：霓虹猫_NeonNeko · 来源：神宫凉子免费配布模型</small></section>
        {!embedded && <section className="group"><h3>记忆</h3><small>手动添加希望角色记住的信息，可随时删除。</small><div className="memory-compose"><input aria-label="添加记忆" maxLength={1000} value={memoryInput} onChange={e => setMemoryInput(e.target.value)} placeholder="例如：我喜欢听爵士乐" onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) void addMemory() }}/><button type="button" aria-label="添加记忆" title="添加记忆" disabled={!memoryInput.trim()} onClick={() => void addMemory()}><Plus size={18}/></button></div>{memoryError && <p className="memory-error" role="alert">{memoryError}</p>}<div className="memory-list">{memories.map(item => <div className="memory-item" key={item.id}><span>{item.content}</span><button type="button" title="删除记忆" aria-label="删除记忆" onClick={() => void removeMemory(item.id)}><Trash2 size={15}/></button></div>)}{!memories.length && <small>还没有添加记忆。</small>}</div></section>}
        <div className="settings-actions"><button className="wide-btn" onClick={() => void saveSettings()}><Check size={17}/> 保存设置</button></div>
      </div>}</aside></div>}
  </div>
}
