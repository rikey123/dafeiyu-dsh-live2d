import { apiUrl } from './runtime'
import { useState } from 'react'

export type SystemOneProvider = 'ark' | 'tokentosea'
export type SystemOneSettings = {
  systemone_provider: SystemOneProvider; systemone_enabled: boolean;
  systemone_api_key: string; systemone_api_key_set?: boolean; clear_systemone_api_key?: boolean;
  systemone_ark_api_key: string; systemone_ark_api_key_set?: boolean; clear_systemone_ark_api_key?: boolean; systemone_ark_model: string;
  systemone_audio_enabled: boolean; systemone_timeout_ms: number; systemone_interrupt_threshold: number; systemone_confidence: number;
  systemone_initiative_enabled: boolean; systemone_initiative_threshold: number;
  systemone_initiative_min_speech_ms: number; systemone_initiative_cooldown_s: number;
  systemone_initiative_wait_threshold: number; systemone_initiative_max_reply_chars: number;
  systemone_initiative_probe_interval_ms: number; systemone_initiative_max_probes: number;
}
export type SavedDecisionConfig = Pick<SystemOneSettings, 'systemone_provider' | 'systemone_ark_model'>
export const initiativeDefaults = {
  systemone_initiative_threshold: .9, systemone_initiative_min_speech_ms: 3000,
  systemone_initiative_cooldown_s: 20, systemone_initiative_max_reply_chars: 48,
  systemone_initiative_wait_threshold: .2, systemone_initiative_probe_interval_ms: 3000,
  systemone_initiative_max_probes: 3,
}
export const initiativeParameters = [
  { key: 'systemone_initiative_threshold', label: '主动开口意愿阈值', min: .8, max: .99, step: 'any', advanced: false, hint: '越高越谨慎，越低越容易主动接话。' },
  { key: 'systemone_initiative_min_speech_ms', label: '至少聆听（毫秒）', min: 1500, max: 15000, step: '1', advanced: false, hint: '连续说话达到此时长才首次判断，不是实际接话延迟。' },
  { key: 'systemone_initiative_cooldown_s', label: '两次主动接话最短间隔（秒）', min: 10, max: 120, step: '1', advanced: false, hint: '越大越少抢话；跨发言生效，同一连接内计时。' },
  { key: 'systemone_initiative_max_reply_chars', label: '主动接话建议回复长度（字符）', min: 8, max: 80, step: '1', advanced: false, hint: '含标点，为大致建议长度；完整句优先，不强制截断。' },
  { key: 'systemone_initiative_wait_threshold', label: '等待保护概率阈值', min: 0, max: .5, step: 'any', advanced: true, hint: '要求继续等待的概率高于此值就不开口；越低越尊重话语权。' },
  { key: 'systemone_initiative_probe_interval_ms', label: '再次判断间隔（毫秒）', min: 1500, max: 10000, step: '1', advanced: true, hint: '按新收到的语音时长计；越短判断越频繁，可能增加识别负载和云端费用。' },
  { key: 'systemone_initiative_max_probes', label: '每段连续发言最多判断次数', min: 1, max: 6, step: '1', advanced: true, hint: '只限制尝试次数；每段发言仍最多主动接话一次。' },
] as const
export const systemOneDefaults: SystemOneSettings = {
  systemone_provider: 'ark', systemone_enabled: false, systemone_api_key: '', systemone_ark_api_key: '',
  systemone_ark_model: 'doubao-seed-2-1-lite-260915', systemone_audio_enabled: true,
  systemone_timeout_ms: 1200, systemone_interrupt_threshold: .75, systemone_confidence: .6,
  systemone_initiative_enabled: false, ...initiativeDefaults,
}
export const decisionReasons: Record<string, string> = {
  ok: '判断成功', missing_key: '尚未配置密钥', not_probed: '尚未测试', timeout: '请求超时，沿用本地规则',
  network: '网络不可用，沿用本地规则', authentication: '密钥无效', permission_denied: '账号无权限，请检查模型开通及接入点授权',
  region_restricted: '供应商地区限制，并非连接超时', model_not_open: '模型尚未开通', endpoint_not_found: '推理接入点不存在或不可访问',
  model_not_supported: '当前模型不支持此接口', billing: '账户余额或计费状态异常', invalid_request: '请求参数或接口权限不符',
  rate_limit: '服务限流，沿用本地规则', invalid_response: '返回格式或概率不符合协议',
  provider_failed: '服务端任务失败或待核对', http_error: '服务请求失败',
  circuit_open: '连续失败，暂时使用本地规则', busy: '并发已满，沿用本地规则', low_confidence: '判断不确定，沿用本地规则',
}
export function SystemOnePreferences({ settings, saved, onChange, native, runtime, conversationMode = 'duplex', ownerOnly = false, initiativeRuntime }: {
  settings: SystemOneSettings; saved: SavedDecisionConfig; onChange: (value: Partial<SystemOneSettings>) => void; native: boolean; runtime?: string;
  conversationMode?: string; ownerOnly?: boolean; initiativeRuntime?: string;
}) {
  const [testing, setTesting] = useState(false), [result, setResult] = useState('')
  const ark = settings.systemone_provider === 'ark'
  const key = ark ? settings.systemone_ark_api_key : settings.systemone_api_key
  const keySet = ark ? settings.systemone_ark_api_key_set : settings.systemone_api_key_set
  const clearing = ark ? settings.clear_systemone_ark_api_key : settings.clear_systemone_api_key
  const dirty = settings.systemone_provider !== saved.systemone_provider || (ark && settings.systemone_ark_model !== saved.systemone_ark_model)
  const label = ark ? '豆包 System One' : 'Clef Omni'
  const parameter = (spec: typeof initiativeParameters[number]) => <label key={spec.key}>
    {spec.label}<input aria-label={spec.label} aria-describedby={`${spec.key}-hint`} type="number" required
      min={spec.min} max={spec.max} step={spec.step}
      value={Number.isFinite(settings[spec.key]) ? settings[spec.key] : ''}
      onChange={e => onChange({ [spec.key]: e.target.valueAsNumber })}/>
    <small id={`${spec.key}-hint`}>默认 {initiativeDefaults[spec.key]}，范围 {spec.min}–{spec.max}。{spec.hint}</small>
  </label>
  const test = async () => {
    setTesting(true); setResult('')
    try {
      const response = await fetch(apiUrl('/api/systemone/test'), { method: 'POST' })
      const value = await response.json()
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '测试请求失败')
      const provider = value.provider === 'ark' ? '豆包 System One' : 'Clef Omni'
      setResult(`${provider} · ${decisionReasons[value.reason] || '请求失败'} · ${value.elapsed_ms} ms${value.ok ? '（文本接口测试，不代表真人打断延迟或概率已校准）' : ''}`)
    } catch (error) { setResult(error instanceof Error ? error.message : '测试失败') }
    finally { setTesting(false) }
  }
  return <section className="group systemone-parameters"><h3>智能交互判断 · System One</h3>
    <label>判断供应商<select aria-label="判断供应商" value={settings.systemone_provider} onChange={e => {
      const provider = e.target.value as SystemOneProvider
      const available = provider === 'ark' ? !settings.clear_systemone_ark_api_key && (settings.systemone_ark_api_key_set || settings.systemone_ark_api_key) : !settings.clear_systemone_api_key && (settings.systemone_api_key_set || settings.systemone_api_key)
      onChange({ systemone_provider: provider, systemone_enabled: settings.systemone_enabled && !!available && !native }); setResult('')
    }}><option value="ark">火山方舟 · 豆包（北京，Beta）</option><option value="tokentosea">TokenToSea · Clef Omni（海外，受地区策略限制）</option></select></label>
    <label className="motion-setting"><input type="checkbox" checked={settings.systemone_enabled} disabled={native && !settings.systemone_enabled} onChange={e => onChange({ systemone_enabled: e.target.checked })}/>启用 System One 判断</label>
    <small>判断插话与附和、回复情绪、表情和手势，回答仍由 DeepSeek 等已配置的对话模型生成。适用于 GPU、CPU 和 TTS API。关闭后沿用本地规则。</small>
    {native && <small>MOSS-Live 自行控制语音轮次。使用此判断层请切换到“全双工交互”或“轮流说话”。</small>}
    {ark && <><label>方舟模型 / 推理接入点 ID<input value={settings.systemone_ark_model} maxLength={128} placeholder="doubao-seed-2-1-lite-260915 或 ep-…" onChange={e => onChange({ systemone_ark_model: e.target.value })}/></label><small>请在方舟控制台开通豆包 Seed 2.1 Lite 260915。若账号要求推理接入点，请填写绑定该模型的 ep- ID。北京端点固定，不会把密钥发送到自定义地址。</small></>}
    <label>{ark ? '方舟 API Key' : 'TokenToSea API Key'}<input type="password" autoComplete="off" value={key} placeholder={keySet ? '已设置，留空保持不变' : `填写独立的${ark ? '方舟' : 'TokenToSea'} API Key`} onChange={e => onChange(ark ? { systemone_ark_api_key: e.target.value, clear_systemone_ark_api_key: false } : { systemone_api_key: e.target.value, clear_systemone_api_key: false })}/></label>
    <label className="motion-setting"><input type="checkbox" checked={!!clearing} onChange={e => onChange({ ...(ark ? { clear_systemone_ark_api_key: e.target.checked, systemone_ark_api_key: '' } : { clear_systemone_api_key: e.target.checked, systemone_api_key: '' }), ...(e.target.checked ? { systemone_enabled: false } : {}) })}/>清除当前供应商密钥并关闭功能</label>
    <label className="motion-setting"><input type="checkbox" checked={settings.systemone_audio_enabled} onChange={e => onChange({ systemone_audio_enabled: e.target.checked })}/>结合用户声音判断</label>
    <small>{settings.systemone_audio_enabled ? `启用功能并打开麦克风后，将发送最长 4 秒的用户声音片段及最近对话文本到${ark ? '火山方舟北京服务' : 'TokenToSea 海外服务'}。开启本人声音筛选时，验证通过后才发送；不会采集图片或视频。` : '仅发送识别文本、回复片段及最近对话；提前插话判断依赖下方的流式识别预览。'} 云端调用可能产生费用。两家密钥独立保存在本机后端，不自动跨供应商回退。</small>
    <label className="motion-setting"><input type="checkbox" aria-label="允许助手主动接话" checked={settings.systemone_initiative_enabled}
      disabled={!settings.systemone_enabled || native || conversationMode !== 'duplex' || ownerOnly}
      onChange={e => onChange({ systemone_initiative_enabled: e.target.checked })}/>允许助手主动接话（实验）</label>
    <small>你还在说话时，判断模型评估是否有强烈的及时共情、澄清、提醒或接话意愿；有把握才让 DeepSeek 回应一句，再把话语权交还你。不是每句话都抢答，也不会在没有发言时自行找话题。</small>
    <small>仅在全双工、已启用判断层且未开启本人声音筛选时生效。默认关闭；不会自动打开麦克风。没有流式识别预览时，复用本地识别器读取短音频快照，不依赖额外 ASR 模型；会增加本地识别和云端判断用量。</small>
    <section aria-label="主动接话参数"><h3>主动接话参数</h3>
      <small>功能未开启时也可预先配置。修改后点击底部“保存设置”，语音会话重连、麦克风保持关闭；再次开启麦克风后使用新参数。</small>
      {initiativeParameters.filter(spec => !spec.advanced).map(parameter)}
      <details><summary>主动接话高级参数</summary>
        {initiativeParameters.filter(spec => spec.advanced).map(parameter)}
      </details>
      <button type="button" onClick={() => onChange({ ...initiativeDefaults })}>恢复主动接话默认参数</button>
      <small>当前每段连续发言最多判断 {settings.systemone_initiative_max_probes} 次、主动接话 1 次，回复建议约 {settings.systemone_initiative_max_reply_chars} 字符，完整句优先，不强制截断。要求继续等待的概率高于 {settings.systemone_initiative_wait_threshold} 就不开口；“先听我说完”等明确要求始终优先。恢复默认只修改以上参数，不启用功能、不更改密钥，保存后生效。识别或判断失败只继续听，不用关键词强行触发。默认概率尚未真人校准。</small>
    </section>
    <small>主动接话：{initiativeRuntime || '本次连接尚无判断。'}</small>
    <details><summary>判断参数</summary>
      <label>单次判断时限（毫秒）<input type="number" required min="200" max="5000" step="1" value={Number.isFinite(settings.systemone_timeout_ms) ? settings.systemone_timeout_ms : ''} onChange={e => onChange({ systemone_timeout_ms: e.target.valueAsNumber })}/></label>
      <label>打断概率阈值<input type="number" required min="0.5" max="0.99" step="any" value={Number.isFinite(settings.systemone_interrupt_threshold) ? settings.systemone_interrupt_threshold : ''} onChange={e => onChange({ systemone_interrupt_threshold: e.target.valueAsNumber })}/></label>
      <small>此阈值用于“用户打断助手”，与上方“助手主动接话”的意愿阈值相互独立。</small>
      <label>表情动作置信度阈值<input type="number" required min="0.5" max="0.99" step="any" value={Number.isFinite(settings.systemone_confidence) ? settings.systemone_confidence : ''} onChange={e => onChange({ systemone_confidence: e.target.valueAsNumber })}/></label>
      <small>默认阈值尚未校准。概率不等于已验证的准确率；需用标注样本评估。超时、限流或低置信度沿用本地规则；连续失败暂停请求 15 秒。表情判断与合成并行，播放结束后不执行迟到动作。手动表情和手势优先。</small>
    </details>
    <small>{label} · {ark ? settings.systemone_ark_model : 'clef-omni'}。最近会话：{runtime || '尚无实测判断。'}</small>
    <button type="button" disabled={testing || dirty || !keySet || !!key || !!clearing} onClick={() => void test()}>{testing ? '正在测试…' : '测试已保存配置（一次云端调用）'}</button>
    <small>更换供应商、模型或密钥后请先保存。测试只发送一条固定示例文本，不发送聊天记录或音频。</small>
    {result && <small role="status">{result}</small>}
  </section>
}
