import { apiUrl, trackVoiceCleanup } from './runtime'
import { useEffect, useRef, useState } from 'react'
import { Mic, Square, Trash2, Upload } from 'lucide-react'
import type { VoiceSession } from './voice'
import { microphoneError } from './microphone'

type Status = { enabled: boolean; ready: boolean; enrolled: boolean; detail?: string }
async function request(path: string, init?: RequestInit) {
  const response = await fetch(apiUrl(path), init)
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `HTTP ${response.status}`) }
  return response.json()
}
export function OwnerVoice({ active = true, voice, device, stopChat, onRemoved }: { active?: boolean; voice?: VoiceSession; device: string; stopChat: () => Promise<void>; onRemoved: () => void }) {
  const [status, setStatus] = useState<Status>(), [files, setFiles] = useState<File[]>([]), [message, setMessage] = useState(''), [recording, setRecording] = useState(false), [busy, setBusy] = useState(false)
  const alive = useRef(true), current = useRef<VoiceSession>(), pending = useRef<Promise<void>>(), timer = useRef<number>()
  const activityVersion = useRef(0), activeRef = useRef(active); activeRef.current = active
  const refresh = async () => { const value = await request('/api/voice/owner/status'); if (alive.current) setStatus(value) }
  useEffect(() => { alive.current = true; void refresh().catch(error => setMessage(String(error))); return () => { alive.current = false; window.clearTimeout(timer.current); trackVoiceCleanup((async () => { await pending.current?.catch(() => {}); await current.current?.stopEnrollment().catch(() => {}) })()) } }, [])
  useEffect(() => {
    if (active) return
    activityVersion.current++; window.clearTimeout(timer.current)
    const recorder = current.current; current.current = undefined
    if (recorder) trackVoiceCleanup(recorder.stopEnrollment().then(() => {}))
    setRecording(false); setBusy(false)
  }, [active])
  const start = async () => {
    if (!activeRef.current || !voice || busy) return
    const version = activityVersion.current
    setBusy(true); setMessage('')
    const operation = (async () => { await stopChat(); if (!activeRef.current || version !== activityVersion.current) return; current.current = voice; await voice.startEnrollment(device); if (!alive.current || !activeRef.current || version !== activityVersion.current) { await voice.stopEnrollment(); if (current.current === voice) current.current = undefined; return }; setRecording(true); timer.current = window.setTimeout(() => void stop(), 10000) })()
    pending.current = operation
    try { await operation } catch (error) { if (alive.current && version === activityVersion.current) setMessage(microphoneError(error)); if (current.current === voice) current.current = undefined } finally { if (pending.current === operation) pending.current = undefined; if (alive.current && version === activityVersion.current) setBusy(false) }
  }
  const stop = async (keep = true) => {
    window.clearTimeout(timer.current); const recorder = current.current; if (!recorder) return
    current.current = undefined; setBusy(true)
    try { const blob = await recorder.stopEnrollment(); if (keep && blob && alive.current) setFiles(items => [...items, new File([blob], `voice-${items.length + 1}.wav`, { type: 'audio/wav' })]) } catch (error) { if (alive.current) setMessage(String(error)) } finally { if (alive.current) { setRecording(false); setBusy(false) } }
  }
  const enroll = async () => { setBusy(true); try { const data = new FormData(); files.forEach(file => data.append('files', file)); await request('/api/voice/owner/enroll', { method: 'POST', body: data }); setFiles([]); await refresh(); setMessage('本人声音已录入。') } catch (error) { setMessage(String(error)) } finally { setBusy(false) } }
  const toggle = async (enabled: boolean) => { setBusy(true); try { await request('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ owner_voice_only: enabled }) }); onRemoved(); await refresh() } catch (error) { setMessage(String(error)) } finally { setBusy(false) } }
  const remove = async () => { setBusy(true); try { await request('/api/voice/owner/enrollment', { method: 'DELETE' }); onRemoved(); await refresh(); setFiles([]) } catch (error) { setMessage(String(error)) } finally { setBusy(false) } }
  return <section><h3>本人声音</h3><small>{status ? (status.enrolled ? '已录入' : '尚未录入') + (status.detail ? ` · ${status.detail}` : '') : '正在读取状态'}</small><p><small>至少两段，每段建议 3–10 秒，至少包含 2 秒有效人声。上传 16 kHz 单声道 PCM16 WAV。仅保留声音特征，不保留录音；此功能不是身份认证。</small></p>
    <label className="motion-setting"><input type="checkbox" checked={!!status?.enabled} disabled={busy || (!status?.enabled && (!status?.ready || !status?.enrolled))} onChange={e => void toggle(e.target.checked)}/>仅回应本人声音</label>
    {!status?.ready || !status?.enrolled ? <small>请先准备声音模型并完成录入，才能开启筛选。</small> : <small>较短发言可能无法判断，请说完整句子。</small>}
    <div className="settings-actions">{recording ? <><button disabled={busy} onClick={() => void stop()}><Square size={16}/> 完成录音</button><button disabled={busy} onClick={() => void stop(false)}>取消</button></> : <button disabled={busy || !voice} onClick={() => void start()}><Mic size={16}/> 录制一段</button>}<label><Upload size={16}/> 选择 WAV<input type="file" accept=".wav,audio/wav" multiple disabled={busy || recording} onChange={e => { setFiles(Array.from(e.target.files || [])); e.target.value = '' }}/></label><button disabled={busy || recording || files.length < 2} onClick={() => void enroll()}>提交 {files.length} 段</button><button disabled={busy || recording || !status?.enrolled} onClick={() => void remove()}><Trash2 size={16}/> 删除本人声音</button></div>{message && <p role="status">{message}</p>}
  </section>
}
