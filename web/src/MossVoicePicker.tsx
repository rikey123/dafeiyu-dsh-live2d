import { apiUrl } from './runtime'
import { useEffect, useState } from 'react'
import { mossVoiceGroups, mossVoiceLabel, parseMossVoiceCatalog, type MossVoiceCatalog } from './mossVoices'

/** Pure options also used by SSR tests; saved IDs never silently become default. */
export function MossVoiceOptions({ catalog, value }: { catalog?: MossVoiceCatalog; value: string }) {
  const defaultVoice = catalog?.voices.find(voice => voice.id === catalog.default_voice)
  const unknown = value && value !== 'default' && !catalog?.voices.some(voice => voice.id === value)
  return <>
    <option value="default">默认{defaultVoice ? `（${mossVoiceLabel(defaultVoice)}）` : '（模型首个音色）'}</option>
    {unknown && <option value={value} disabled>已保存：{value}（{catalog ? '当前模型不包含，请重新选择' : '尚未核验'}）</option>}
    {catalog && mossVoiceGroups(catalog.voices).map(([group, voices]) => <optgroup key={group} label={group}>
      {voices.map(voice => <option key={voice.id} value={voice.id}>{mossVoiceLabel(voice)}</option>)}
    </optgroup>)}
  </>
}

export function MossVoicePicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const [catalog, setCatalog] = useState<MossVoiceCatalog>(), [error, setError] = useState('')
  const [loading, setLoading] = useState(true), [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setCatalog(undefined)
    void (async () => {
      try {
        const response = await fetch(apiUrl('/api/tts/voices'), { signal: controller.signal })
        const data = await response.json()
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`)
        const next = parseMossVoiceCatalog(data)
        if (!controller.signal.aborted) setCatalog(next)
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
      } finally { if (!controller.signal.aborted) setLoading(false) }
    })()
    return () => controller.abort()
  }, [attempt])
  const unknown = catalog && value && value !== 'default' && !catalog.voices.some(voice => voice.id === value)
  return <div className="moss-voice-picker">
    <label>MOSS 内置音色<select aria-label="MOSS 内置音色" value={value || 'default'} disabled={loading || !catalog} onChange={event => onChange(event.target.value)}>
      <MossVoiceOptions catalog={catalog} value={value}/>
    </select><small>{loading ? '正在读取模型音色清单，不加载推理模型…' : catalog ? `共 ${catalog.voices.length} 个预置音色 · ${catalog.source === 'installed_manifest' ? '本机模型清单' : '已配置服务清单'}` : '音色清单暂不可用，保留已保存的选择。'}</small></label>
    {error && <small role="alert">{error}</small>}
    {unknown && <small role="alert">已保存的音色不在当前模型清单中，请重新选择后保存。</small>}
    <button type="button" disabled={loading} onClick={() => setAttempt(count => count + 1)}>刷新 MOSS 音色</button>
    <small>名称和分组来自模型预置清单，并非质量或语言能力保证。选择后需保存；仅影响 CPU MOSS，GPU 参考音色、API 和 MOSS-Live 独立配置。修改 MOSS 服务地址后请先保存并重新打开设置。</small>
  </div>
}
