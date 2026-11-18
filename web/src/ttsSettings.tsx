import { apiUrl } from './runtime'
import type { OptionalService } from './serviceStatus'
import { serviceDetail } from './serviceStatus'
import { useState } from 'react'
import { MossVoicePicker } from './MossVoicePicker'

export type TTSMode = 'legacy' | 'auto' | 'cpu' | 'gpu' | 'api'
export type TTSSettings = {
  conversation_mode: 'pipeline' | 'duplex' | 'moss_live';
  moss_live_api_key: string; moss_live_api_key_set?: boolean; clear_moss_live_api_key?: boolean; moss_live_voice: string; moss_live_model: string; index_tts_url: string; moss_tts_url: string;
  tts_mode: TTSMode; tts_api_base_url: string; tts_api_model: string; tts_api_voice: string;
  tts_api_provider: 'deepseek' | 'openai_compatible'; tts_api_filter_markdown: boolean;
  gpu_tts_model: 'index_tts' | 'gpt_sovits';
  tts_api_key: string; tts_api_key_set?: boolean; clear_tts_api_key?: boolean;
  tts_api_speed: number; tts_api_timeout: number;
  tts_engine: 'local' | 'cosyvoice'; cosyvoice_url: string; voice: string;
}
export type TTSStatus = { mode?: string; provider?: string; ready?: boolean; configured?: boolean; device?: string; detail?: string; verification?: string; state?: string }
export const ttsDefaults: TTSSettings = {
  conversation_mode: 'duplex', moss_live_api_key: '', moss_live_voice: '', moss_live_model: 'moss-live-1.0', index_tts_url: 'http://127.0.0.1:8770', moss_tts_url: 'http://127.0.0.1:8772',
  tts_mode: 'legacy', gpu_tts_model: 'index_tts', tts_engine: 'local', cosyvoice_url: 'http://127.0.0.1:8770', voice: '',
  tts_api_provider: 'deepseek', tts_api_filter_markdown: true,
  tts_api_base_url: 'https://api.deepseek.com/v1',
  tts_api_model: 'tts-1', tts_api_voice: 'stella', tts_api_key: '', tts_api_speed: 1, tts_api_timeout: 60,
}
export const ttsModeHelp: Record<TTSMode, string> = {
  legacy: '兼容原配置，跟随启动策略。选择下面的具体模式后，保存的选择优先。',
  auto: '每次回复前检查本地 GPU 是否可用，否则使用 CPU。不会自动调用付费 API。',
  cpu: '使用 MOSS-TTS-Nano 100M ONNX 与本地识别，不占用显卡。',
  gpu: '保存启用后立即加载并预热所选 CUDA 模型，模式期间常驻显存；切换其他模式后释放。GPU 不可用时明确报错。',
  api: '默认使用 DeepSeek 官方 TTS，将待朗读文本发往云端，可能产生费用。不占用本地显卡；保留其他兼容服务的旧配置。',
}
export function TTSPreferences({ settings, onChange, status, optional }: {
  settings: TTSSettings; onChange: (patch: Partial<TTSSettings>) => void;
  status?: TTSStatus; optional?: { index_tts?: OptionalService; moss_tts?: OptionalService };
}) {
  const [loading, setLoading] = useState(false), [loadNotice, setLoadNotice] = useState('')
  const prepare = async () => {
    setLoading(true); setLoadNotice('')
    try {
      const response = await fetch(apiUrl('/api/tts/load'), { method: 'POST' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`)
      setLoadNotice(result.detail)
    } catch (error) { setLoadNotice(error instanceof Error ? error.message : String(error)) }
    finally { setLoading(false) }
  }
  const native = settings.conversation_mode === 'moss_live'
  const deepseek = settings.tts_api_provider === 'deepseek'
  const local = !native && settings.tts_mode !== 'api'
  const gpuName = settings.gpu_tts_model === 'gpt_sovits' ? 'GPT-SoVITS v5 turbo' : 'IndexTTS-2.5'
  return <>
    <label>语音对话方式<select value={settings.conversation_mode} onChange={e => onChange({ conversation_mode: e.target.value as TTSSettings['conversation_mode'] })}>
      <option value="moss_live">全双工语音模型 · MOSS-Live + DeepSeek</option><option value="duplex">全双工交互 · DeepSeek 回答</option><option value="pipeline">轮流说话</option>
    </select><small>{native ? 'MOSS-Live 负责听说、轮次和自然打断；复杂任务委派给后台配置的 DeepSeek。仅语音，不采集视频。这是云端模式，需要独立密钥，可能产生费用。' : settings.conversation_mode === 'duplex' ? '持续收音，播放期间也可说话打断。回答由后台 DeepSeek 生成，声音由下方选定的模型或 API 合成。这是 ASR + DeepSeek + TTS 管线。' : '播放期间暂停识别，播放结束后继续收音；可随时手动停止。'}</small></label>
    {native && <>
      <label>MOSS-Live 密钥<input type="password" autoComplete="off" value={settings.moss_live_api_key} onChange={e => onChange({ moss_live_api_key: e.target.value, clear_moss_live_api_key: false })} placeholder={settings.moss_live_api_key_set ? '已设置，留空保持原密钥' : '填写 MOSS 平台 API Key'}/></label>
      <label className="check"><input type="checkbox" checked={Boolean(settings.clear_moss_live_api_key)} onChange={e => onChange({ clear_moss_live_api_key: e.target.checked, moss_live_api_key: '' })}/>清除 MOSS-Live 密钥</label>
      <label>语音模型<select value={settings.moss_live_model} onChange={e => onChange({ moss_live_model: e.target.value })}><option value="moss-live-1.0">MOSS-Live 1.0</option><option value="moss-live-1.0-2026-11-02">MOSS-Live 1.0 · 固定 2026-11-02 版本</option></select></label>
      <label>MOSS 音色 ID<input value={settings.moss_live_voice} onChange={e => onChange({ moss_live_voice: e.target.value })} placeholder="留空使用平台默认音色"/><small>填写平台提供的 voice ID；此模式使用云端原生声音。</small></label>
      <small>后台大模型沿用下方 DeepSeek 配置。本地 GPU/CPU TTS 服务会随模式切换释放；本地声纹筛选需关闭。请使用麦克风对话。</small>
    </>}
    {!native && <>
    <label>语音合成模式<select value={settings.tts_mode} onChange={e => onChange({ tts_mode: e.target.value as TTSMode })}>
      <option value="auto">自动（本地 GPU / CPU）</option><option value="cpu">本地 CPU · MOSS-TTS-Nano ONNX</option>
      <option value="gpu">本地 GPU · {gpuName}</option><option value="api">API · DeepSeek TTS</option>
      <option value="legacy">跟随启动策略（兼容原配置）</option>
    </select><small>{ttsModeHelp[settings.tts_mode]}</small></label>
    </>}
    <div className="service-status" role="status">当前保存配置 <small>{[status?.provider, status?.device, status?.detail].filter(Boolean).join(' · ') || '状态未报告'}</small></div>
    {!native && settings.tts_mode === 'api' && <>
      <label>TTS API 服务<select aria-label="TTS API 服务" value={settings.tts_api_provider} onChange={e => onChange(e.target.value === 'deepseek'
        ? { tts_api_provider: 'deepseek', tts_api_base_url: 'https://api.deepseek.com/v1', tts_api_voice: 'stella', tts_api_speed: 1 }
        : { tts_api_provider: 'openai_compatible', tts_api_base_url: 'https://api.openai.com/v1', tts_api_voice: 'alloy', tts_api_model: 'tts-1' })}>
        <option value="deepseek">DeepSeek 官方 TTS · 推荐</option><option value="openai_compatible">OpenAI 兼容服务 · 保留旧配置</option>
      </select><small>更换服务地址时需重新填写密钥或勾选清除，不会将已有密钥自动转发给新服务。</small></label>
      <label>TTS API 基础地址<input value={settings.tts_api_base_url} onChange={e => onChange({ tts_api_base_url: e.target.value })} placeholder={deepseek ? 'https://api.deepseek.com/v1' : 'https://api.openai.com/v1'}/><small>{deepseek ? '官方基础地址含 /v1，不含 /tools/tts。后端通过 WebSocket 接收 24kHz 单声道 PCM16；浏览器不会获得密钥。' : '填写服务商提供的基础地址（通常含 /v1），不包含 /audio/speech。支持返回 24kHz 单声道 PCM16 的兼容服务。'}</small></label>
      {deepseek ? <>
        <label>DeepSeek 音色<select aria-label="DeepSeek 音色" value={settings.tts_api_voice} onChange={e => onChange({ tts_api_voice: e.target.value })}>
          <option value="stella">海星 · 女声（stella）</option><option value="tide">暗潮 · 男声（tide）</option>
        </select></label>
        <label className="check"><input type="checkbox" checked={settings.tts_api_filter_markdown} onChange={e => onChange({ tts_api_filter_markdown: e.target.checked })}/>朗读前过滤 Markdown</label>
        <small>官方接口自动识别语种，无需填写模型，不支持调节语速。打断后立即关闭本次连接，不重试、不续传、不重播。</small>
      </> : <>
        <label>TTS 模型<input value={settings.tts_api_model} onChange={e => onChange({ tts_api_model: e.target.value })}/></label>
        <label>API 音色<input value={settings.tts_api_voice} onChange={e => onChange({ tts_api_voice: e.target.value })}/></label>
        <label>API 语速（0.25–4）<input type="number" min="0.25" max="4" step="0.05" value={settings.tts_api_speed} onChange={e => onChange({ tts_api_speed: Number(e.target.value) })}/></label>
      </>}
      <label>TTS API 密钥<input type="password" autoComplete="off" value={settings.tts_api_key} onChange={e => onChange({ tts_api_key: e.target.value, clear_tts_api_key: false })} placeholder={settings.tts_api_key_set ? '已设置，留空保持不变' : '填写独立的 TTS 服务密钥'}/></label>
      <label className="motion-setting"><input type="checkbox" checked={!!settings.clear_tts_api_key} onChange={e => onChange({ clear_tts_api_key: e.target.checked, tts_api_key: '' })}/>保存时清除 TTS 密钥</label>
      <label>请求超时（秒）<input type="number" min="5" max="180" value={settings.tts_api_timeout} onChange={e => onChange({ tts_api_timeout: Number(e.target.value) })}/></label>
      <small>使用 DeepSeek 开放平台 API Key 时也需在此独立填写；DSH 登录凭据不等于 TTS API Key，不读取或复用登录文件。密钥只保存在本机后端；状态查询不发起合成。API 模式使用实时口型。</small>
    </>}
    {local && <>
      {(settings.tts_mode === 'cpu' || settings.tts_mode === 'auto' || settings.tts_mode === 'legacy') && <MossVoicePicker value={settings.voice} onChange={voice => onChange({ voice })}/>}
      {(settings.tts_mode === 'cpu' || settings.tts_mode === 'auto' || settings.tts_mode === 'legacy') && <><label>MOSS ONNX 服务地址<input value={settings.moss_tts_url} onChange={e => onChange({ moss_tts_url: e.target.value })}/></label><div className="service-status">MOSS-TTS-Nano <small>{serviceDetail(optional?.moss_tts)}</small></div></>}
      {settings.tts_mode !== 'cpu' && <>
        <label>GPU 语音模型<select value={settings.gpu_tts_model} onChange={e => onChange({ gpu_tts_model: e.target.value as TTSSettings['gpu_tts_model'] })}><option value="gpt_sovits">GPT-SoVITS v5 turbo · 速度优先</option><option value="index_tts">IndexTTS-2.5 · BF16</option></select><small>{settings.gpu_tts_model === 'gpt_sovits' ? '使用 v5 turbo 四步合成，缓存参考音色并启用 CUDA Graph 自回归加速。GPU 模式启用时完成加载和预热，不把图捕获留到首次回复。' : '使用原生 BF16 与 KV cache，GPU 模式启用时完成加载和预热。'}</small></label>
        <label>GPU 语音服务地址<input value={settings.index_tts_url} onChange={e => onChange({ index_tts_url: e.target.value })}/></label><div className="service-status">{gpuName} <small>{serviceDetail(optional?.index_tts)}</small></div><small>使用服务端配置的参考录音，GPT-SoVITS 还需要录音的准确文本；不读取 MOSS 音色 ID。保存模型选择会释放旧模型，启动所选模型服务。</small>
        {settings.tts_mode === 'gpu' && <><button type="button" disabled={loading || status?.state === 'loading' || status?.state === 'warming'} onClick={() => void prepare()}>重新准备 GPU 模型</button><small>按已保存配置准备；更改模式或模型后请先保存。</small>{loadNotice && <small role="status">{loadNotice}</small>}</>}
      </>}
    </>}
    <small>口型始终随实际播放音频实时分析，不等待整句离线对齐。元音识别是近似结果，不是逐字音素时间轴。</small>
    <small>保存后重新建立语音连接，麦克风不会自动开启。GPU 模式立即加载和预热，请等待状态就绪后对话；自动 / CPU 模式按需加载。</small>
  </>
}
