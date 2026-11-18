import { useEffect, useRef, useState } from 'react'

export const screenDefaults = { screen_companion_enabled: false, screen_companion_mode: 'systemone' as 'systemone' | 'direct', screen_companion_style: 'balanced' as 'quiet' | 'balanced' | 'lively', screen_companion_interval_ms: 2500, screen_companion_change_threshold: .06, screen_companion_cooldown_s: 30, screen_companion_max_judgments_per_hour: 60, screen_companion_max_replies_per_hour: 12, screen_companion_speak_threshold: .9, screen_companion_wait_threshold: .2, screen_companion_max_reply_chars: 64, screen_companion_timeout_ms: 3000, screen_request_enabled: true, screen_request_threshold: .75, screen_request_timeout_ms: 2000, screen_companion_refresh_ms: 15000 }
export type ScreenSettings = typeof screenDefaults
const fields = [
 ['screen_request_threshold','按需截图意愿阈值',.5,.99,'any'], ['screen_request_timeout_ms','截图请求超时（毫秒）',500,5000,1], ['screen_companion_refresh_ms','静态画面刷新间隔（毫秒）',5000,120000,1], ['screen_companion_interval_ms','采样间隔（毫秒）',1000,10000,1], ['screen_companion_change_threshold','画面变化阈值',.01,.5,'any'], ['screen_companion_cooldown_s','回复冷却（秒）',10,300,1], ['screen_companion_max_judgments_per_hour','每小时最多判断次数',1,240,1], ['screen_companion_max_replies_per_hour','每小时最多回复次数',1,60,1], ['screen_companion_speak_threshold','开口意愿阈值',.5,.99,'any'], ['screen_companion_wait_threshold','等待阈值',0,.5,'any'], ['screen_companion_max_reply_chars','建议回复长度（字符）',8,120,1], ['screen_companion_timeout_ms','判断超时（毫秒）',500,10000,1],
] as const
export function ScreenPreferences({settings,onChange}: {settings: ScreenSettings; onChange: (patch: Partial<ScreenSettings>) => void}) {
 return <section className="group screen-parameters"><h3>屏幕陪玩</h3>
  <label className="motion-setting"><input type="checkbox" checked={settings.screen_companion_enabled} onChange={e => onChange({screen_companion_enabled:e.target.checked})}/>启用屏幕陪玩配置</label>
  <label className="motion-setting"><input type="checkbox" checked={settings.screen_request_enabled} onChange={e => onChange({screen_request_enabled:e.target.checked})}/>允许按需请求截图</label>
  <small>此开关用于用户提问时的 Jev 文本意图预判，与自动陪伴模式独立；DSH 自主调用看屏幕工具不受此开关影响。</small>
  <label>屏幕陪伴模式<select aria-label="屏幕陪伴模式" value={settings.screen_companion_mode} onChange={e => onChange({screen_companion_mode:e.target.value as ScreenSettings['screen_companion_mode']})}><option value="systemone">Jev 判断后陪伴</option><option value="direct">DSH 直接看画面</option></select></label>
  <small>直接模式适合视频或游戏等连续画面，跳过 Jev 的屏幕判断，DSH 视觉调用可能更频繁、费用更高；其他已启用的 System One 功能不受影响。仍需手动授权分享，并遵守采样、冷却和限额。</small>
  <small>保存只启用配置，不会自动采集。手动选择屏幕或窗口后，用户提问触发的按需截图会用于回答当前问题；自动陪玩截图根据所选模式经过 Jev 判断或直接发送给 DSH 视觉模型生成回复，使用原有语音合成。DSH 可能按原生附件在本地留存。手动屏幕查看无需开启 System One；Jev 模式的自动陪玩判断需要 System One。MOSS-Live 不支持。切页后已授权采集继续，手动停止或退出插件才释放。</small>
  {settings.screen_companion_mode !== 'direct' && <label>主动陪伴风格<select value={settings.screen_companion_style} onChange={e => onChange({screen_companion_style:e.target.value as ScreenSettings['screen_companion_style']})}><option value="quiet">安静：只说值得及时提醒的内容</option><option value="balanced">自然：允许有依据的日常陪伴评论</option><option value="lively">活跃：更积极地寻找交流机会</option></select></label>}
  <small>风格控制判断策略，阈值控制通过概率；不是定时强制说话。三种风格都尊重安静要求、隐私、忙碌、冷却和限额。“用户说话时主动接话”是 System One 中另一个独立开关。</small>
  {fields.filter(([key]) => settings.screen_companion_mode !== 'direct' || !['screen_companion_speak_threshold','screen_companion_wait_threshold','screen_companion_timeout_ms'].includes(key)).map(([key,label,min,max,step]) => <label key={key}>{settings.screen_companion_mode === 'direct' && key === 'screen_companion_max_judgments_per_hour' ? '每小时最多 DSH 看画面次数' : label}<input type="number" required min={min} max={max} step={step} value={Number.isFinite(settings[key]) ? settings[key] : ''} onChange={e => onChange({[key]:e.target.valueAsNumber})}/></label>)}{settings.screen_companion_mode !== 'direct' && <small>开口意愿阈值可设为 0.5–0.99，越低越容易触发主动评论；仍受等待、冷却和次数上限约束。</small>}</section>
}
export type ScreenStatus = {status: string; reason?: string; source?: string; model?: string; style?: ScreenSettings['screen_companion_style']; desire?: number; must_wait?: number; intent?: string|null; speak_threshold?: number; wait_threshold?: number; intent_confidence_threshold?: number; intent_confidence?: number; intent_probability?: number; non_wait_probability?: number; judgments?: number; replies?: number; frames?: number; rejected?: number; mode?: 'proactive'|'requested'|'direct'}
const explanations: Record<string,string> = {low_desire:'开口意愿未达到阈值',must_wait:'需要等待的概率超过阈值',wait_intent:'判断当前应继续等待',low_confidence:'非等待意图的概率不足或意图不明确',busy:'正在忙，暂时无法判断',interval:'距离上次判断太近，等待采样间隔',cooldown:'回复冷却中',budget:'已达到判断或回复请求的每小时限额',unchanged:'画面变化不足，继续等待',strong_desire:'已发起主动回复请求',direct:'画面已直送 DSH，由 DSH 决定是否开口'}
export function screenReason(status: ScreenStatus) { return explanations[status.reason ?? ''] ?? status.reason ?? status.status }
export function retainScreenDecision(previous: ScreenStatus | undefined, status: ScreenStatus): ScreenStatus | undefined {
 if (status.mode === 'requested' || status.reason?.startsWith('request_')) return previous
 return [status.desire,status.must_wait,status.intent_confidence,status.intent_probability,status.non_wait_probability].some(value => typeof value === 'number' && Number.isFinite(value)) ? status : previous
}
const numberText = (value: number | undefined) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '—'
const styleLabels = { quiet:'安静', balanced:'自然', lively:'活跃' }
export function screenDecisionText(status: ScreenStatus) {
 return `最近主动判断：${screenReason(status)} · 生效风格 ${status.style ? styleLabels[status.style] ?? '—' : '—'} · 开口意愿 ${numberText(status.desire)} / 生效阈值 ${numberText(status.speak_threshold)} · 需要等待概率 ${numberText(status.must_wait)} / 生效阈值 ${numberText(status.wait_threshold)} · 意图 ${status.intent ?? '—'} · 意图概率 ${numberText(status.intent_probability)} · 非等待概率 ${numberText(status.non_wait_probability)} / 生效阈值 ${numberText(status.intent_confidence_threshold)} · 意图语气分布置信度 ${numberText(status.intent_confidence)}（仅供参考，不单独决定开口）`
}
export function handleScreenStatus(status: ScreenStatus, stop: () => void, report: (status: ScreenStatus) => void) {
 if (status.status === 'unavailable' && !['timeout','network','circuit_open','busy','unchanged','interval','cooldown','budget','low_desire','must_wait','wait_intent','low_confidence','request_not_shared','request_disabled','request_low_intent','request_snapshot_timeout','request_attached','request_cancelled','request_intent_unavailable'].includes(status.reason ?? '')) stop()
 report(status)
}
export function screenAvailability(settings: ScreenSettings & {harness_provider?: string; screen_model_ready?:boolean; systemone_enabled: boolean; conversation_mode: string}, connected: boolean, _micTransition: boolean, voiceOnly: boolean) {
 if (settings.harness_provider !== 'dsh') return '屏幕陪玩需要 DSH，请先配置 DSH 并保存设置。'
 if (!settings.screen_companion_enabled) return '请先在设置中启用屏幕陪玩并保存。'
 if (settings.screen_model_ready !== true) return '当前 DSH 模型未确认支持图片输入，请先在 DSH 选择视觉模型并重新打开大肥鱼。'
 if (settings.conversation_mode === 'moss_live' || voiceOnly) return 'MOSS-Live 不支持屏幕陪玩，请切换语音对话方式。'
 if (!connected) return '等待语音连接就绪后才能分享屏幕。'
 return ''
}
type Send = (type: string, data: object) => void
type SnapshotRequest = {id: string; expiresAt: number}
export class ScreenCapture {
 private generation = 0; private stream?: MediaStream; private video?: HTMLVideoElement; private timer?: number; private previous?: Uint8ClampedArray; private encodingGeneration?: number; private encodingRequest?: SnapshotRequest; private seq = 0; private lastSent = 0; private pendingRequest?: SnapshotRequest; private seenRequests = new Set<string>(); private settings?: ScreenSettings; private id = ''; private send?: Send
 constructor(private update: (state: {active:boolean; pending:boolean; sent:number; filtered:number; error:string | undefined}) => void) {}
 private state = {active:false,pending:false,sent:0,filtered:0,error:undefined as string | undefined}
 private lastSample = Number.NEGATIVE_INFINITY
 private publish(patch: Partial<typeof this.state>) { Object.assign(this.state,patch); this.update({...this.state}) }
 start(settings: ScreenSettings, send: Send) {
  this.stop()
  const generation = ++this.generation
  this.publish({pending:true,error:undefined,sent:0,filtered:0})
  // This call must remain synchronous with the user's click.
  let request: Promise<MediaStream>
  try { request = navigator.mediaDevices.getDisplayMedia({video:true,audio:false}) } catch (e) { this.publish({pending:false,error:String(e)}); return }
  void request.then(async stream => {
   // Switching panels/tabs is not revocation of the user's explicit grant.
   if (generation !== this.generation) { stream.getTracks().forEach(t => t.stop()); return }
   this.stream=stream; this.send=send; this.settings=settings; this.id=crypto.randomUUID(); this.seq=0; this.seenRequests.clear(); this.lastSent=0; this.previous=undefined
   const track=stream.getVideoTracks()[0]; if (!track) { this.stop(); return }
   track.addEventListener('ended', () => { if (generation === this.generation) this.stop() }, {once:true})
   const video=document.createElement('video'); this.video=video; video.muted=true; video.playsInline=true; video.srcObject=stream
   try { await video.play() } catch (e) { if (generation === this.generation) { this.stop(); this.publish({error:String(e)}) }; return }
   if (generation !== this.generation) return
   try { send('voice.screen',{active:true,stream_id:this.id}) } catch (e) { this.stop(); this.publish({error:String(e)}); return }
   if (generation !== this.generation) return
   this.publish({pending:false,active:true})
   this.lastSample=Number.NEGATIVE_INFINITY
   const tick=() => this.sample(); tick(); this.timer=window.setInterval(tick,settings.screen_companion_interval_ms)
  }).catch(e => { if (generation === this.generation) { this.stop(); this.publish({error:String(e)}) } })
 }
 sample(request?: unknown) {
  if (!this.state.active || !this.settings || (request !== undefined && (!request || typeof request !== 'object' || (request as Record<string,unknown>).stream_id !== this.id))) return
  // Both the fallback interval and server pulses enter the same rate-limited,
  // single-flight encoder. A pulse can never acquire/reacquire a permission.
  const now=performance.now()
  if (now-this.lastSample < this.settings.screen_companion_interval_ms || this.encodingGeneration === this.generation) return
  this.lastSample=now
  void this.frame(this.generation,this.settings)
 }
 requestSnapshot(request: unknown) {
  if (!request || typeof request !== 'object') return
  const {stream_id, request_id, purpose} = request as Record<string, unknown>
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
  if (purpose !== undefined && purpose !== 'intent' && purpose !== 'tool' && purpose !== 'idle') return
  if (typeof stream_id !== 'string' || typeof request_id !== 'string' || !uuid.test(stream_id) || !uuid.test(request_id) || stream_id !== this.id || !this.state.active || !this.settings || (purpose !== 'tool' && purpose !== 'idle' && !this.settings.screen_request_enabled) || this.seenRequests.has(request_id) || this.encodingRequest?.id === request_id || this.pendingRequest?.id === request_id) return
  this.seenRequests.add(request_id)
  if (this.seenRequests.size > 256) this.seenRequests.delete(this.seenRequests.values().next().value!)
  const snapshot = {id:request_id, expiresAt:Date.now()+this.settings.screen_request_timeout_ms}
  if (this.encodingGeneration === this.generation) { this.pendingRequest = snapshot; return }
  void this.frame(this.generation, this.settings, snapshot)
 }
 private async frame(generation:number, settings:ScreenSettings, request?:SnapshotRequest) {
  if (this.encodingGeneration === generation || !this.video || !this.send || generation !== this.generation || (request && Date.now() >= request.expiresAt)) return
  this.encodingGeneration=generation; this.encodingRequest=request
  try {
   const video=this.video; if (!video.videoWidth || !video.videoHeight) return
   const thumb=document.createElement('canvas'); thumb.width=32; thumb.height=18; const ctx=thumb.getContext('2d'); if (!ctx) throw Error('无法读取画面')
   ctx.drawImage(video,0,0,32,18); const pixels=ctx.getImageData(0,0,32,18).data
   if (!request && this.previous && Date.now()-this.lastSent < settings.screen_companion_refresh_ms) { let sum=0; for(let i=0;i<pixels.length;i+=4) sum+=Math.abs(pixels[i]-this.previous[i])+Math.abs(pixels[i+1]-this.previous[i+1])+Math.abs(pixels[i+2]-this.previous[i+2]); if(sum/(32*18*3*255)<settings.screen_companion_change_threshold) { this.publish({filtered:this.state.filtered+1}); return } }
   const scale=Math.min(1,960/video.videoWidth,540/video.videoHeight); const canvas=document.createElement('canvas'); canvas.width=Math.max(1,Math.floor(video.videoWidth*scale)); canvas.height=Math.max(1,Math.floor(video.videoHeight*scale)); const out=canvas.getContext('2d'); if(!out) throw Error('无法编码画面'); out.drawImage(video,0,0,canvas.width,canvas.height)
   let blob: Blob | null = null
   for (const quality of [.8,.6,.4,.2]) { blob=await new Promise(resolve => canvas.toBlob(resolve,'image/jpeg',quality)); if(blob && blob.size<=256*1024) break }
   if (!blob || blob.type !== 'image/jpeg' || blob.size>256*1024) throw Error('画面编码超出大小限制')
   const bytes=new Uint8Array(await blob.arrayBuffer()); if(generation!==this.generation || (request && Date.now() >= request.expiresAt)) return
   let binary=''; for(let i=0;i<bytes.length;i+=8192) binary+=String.fromCharCode(...bytes.subarray(i,i+8192))
   if (request && Date.now() >= request.expiresAt) return
   this.send(request ? 'voice.screen.snapshot' : 'voice.screen.frame',{stream_id:this.id,seq:++this.seq,width:canvas.width,height:canvas.height,mime_type:'image/jpeg',data:btoa(binary), ...(request ? {request_id:request.id} : {})})
   if (generation !== this.generation) return
   this.lastSent=Date.now(); this.previous=new Uint8ClampedArray(pixels); this.publish({sent:this.state.sent+1})
  } catch(e) { if(generation===this.generation && (!request || Date.now() < request.expiresAt)) { this.stop(); this.publish({error:String(e)}) } } finally { if (this.encodingGeneration === generation) { this.encodingGeneration=undefined; this.encodingRequest=undefined; const pending=this.pendingRequest; this.pendingRequest=undefined; if (pending && generation===this.generation && this.state.active) void this.frame(generation,settings,pending) } }
 }
 stop(reason?: string) { const wasSharing = this.state.active || this.state.pending; ++this.generation; if(this.timer !== undefined) window.clearInterval(this.timer); this.timer=undefined; if(this.id && this.send) { try { this.send('voice.screen',{active:false,stream_id:this.id}) } catch {} }; this.id=''; this.pendingRequest=undefined; this.encodingRequest=undefined; this.seenRequests.clear(); this.settings=undefined; this.stream?.getTracks().forEach(t=>t.stop()); this.stream=undefined; if(this.video) { this.video.pause(); this.video.srcObject=null; this.video.remove() }; this.video=undefined; this.previous=undefined; this.send=undefined; this.encodingGeneration=undefined; this.publish({active:false,pending:false,...(reason && wasSharing ? {error:reason} : {})}) }
}
export function ScreenControl({enabled,disabledReason,settings,send,stopKey,status,prepareAudio}: {enabled:boolean; disabledReason?:string; settings:ScreenSettings; send:Send; stopKey:unknown; status?:ScreenStatus; prepareAudio?:()=>void}) {
 const [state,setState]=useState({active:false,pending:false,sent:0,filtered:0,error:undefined as string|undefined}); const ref=useRef<ScreenCapture>(); if(!ref.current) ref.current=new ScreenCapture(setState)
 const [latest,setLatest]=useState<ScreenStatus>(); const [decision,setDecision]=useState<ScreenStatus>(); const seen=useRef(status)
 const clear = () => { seen.current=status; setLatest(undefined); setDecision(undefined) }
 useEffect(() => { ref.current?.stop(); clear() },[stopKey,enabled])
 useEffect(() => { if (status && status !== seen.current) { seen.current=status; if (state.active || status.status === 'unavailable') setLatest(status); if (state.active) setDecision(previous => retainScreenDecision(previous,status)) } },[status,state.active])
 useEffect(() => { if (!state.active) setDecision(undefined) },[state.active])
 useEffect(() => {
  const stop = () => { ref.current?.stop(); setLatest(undefined); setDecision(undefined) }
  const request = (event: Event) => ref.current?.requestSnapshot((event as CustomEvent).detail)
  const sample = (event: Event) => ref.current?.sample((event as CustomEvent).detail)
  window.addEventListener('screen-companion-stop',stop)
  window.addEventListener('screen-companion-request',request)
  window.addEventListener('screen-companion-sample',sample)
  return () => {
   window.removeEventListener('screen-companion-stop',stop)
   window.removeEventListener('screen-companion-request',request)
   window.removeEventListener('screen-companion-sample',sample)
   ref.current?.stop()
  }
 },[])
 return <div className="screen-control" role="region" aria-label="屏幕陪玩">
  <button type="button" className={state.active ? 'screen-sharing' : 'tool'} disabled={!enabled && !state.active && !state.pending} onClick={() => { clear(); if (state.active || state.pending) ref.current?.stop(); else { prepareAudio?.(); ref.current?.start(settings,send) } }}>{state.active ? '● 屏幕分享中 · 立即停止' : state.pending ? '取消屏幕授权' : '开始屏幕陪玩'}</button>
  {(state.active || state.pending) && <small>切换页面后仍会继续语音与已授权的屏幕共享；请点击“立即停止”或浏览器的共享停止按钮结束共享。</small>}
  {disabledReason && <small>{disabledReason}</small>}
  {latest?.status === 'unavailable' && <small role="status">屏幕判断不可用{state.active ? '，分享仍在进行' : '，分享已停止'}。原因：{screenReason(latest)}</small>}
  {state.error && <small role="status">{state.error}</small>}
  <details><summary>已送帧 {state.sent} · 过滤帧 {state.filtered}</summary><small>{latest ? `当前状态：${screenReason(latest)} · ${latest.source ?? ''} / ${latest.model ?? ''} · 判断次数 ${latest.judgments ?? '—'} · 回复请求次数 ${latest.replies ?? '—'} · 服务收到帧 ${latest.frames ?? '—'} · 拒绝 ${latest.rejected ?? '—'} · 模式 ${latest.mode ?? '—'}` : state.active ? '分享中，等待服务判断。' : state.pending ? '等待屏幕授权。' : '屏幕分享未开始。'}{decision && <> <br/>{screenDecisionText(decision)}</>}</small></details>
 </div>
}
