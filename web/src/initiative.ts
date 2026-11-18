const sources: Record<string, string> = { 'doubao-systemone': '豆包 System One', 'clef-omni': 'Clef Omni' }
const intents: Record<string, string> = { wait: '继续聆听', acknowledge: '接话回应', empathize: '及时共情', clarify: '必要澄清', correct: '及时提醒' }
const reasons: Record<string, string> = { respect_floor: '尊重话语权', low_desire: '开口意愿不足', low_confidence: '判断不确定', no_usable_speech: '尚无可靠识别文本' }

/** Diagnostic only: acceptance means generation requested, not audio heard. */
export function initiativeStatus(data: unknown): string | undefined {
  if (!data || typeof data !== 'object') return
  const value = data as Record<string, unknown>
  if (value.type !== 'voice.initiative' || typeof value.source !== 'string' || !Object.hasOwn(sources, value.source)) return
  if (!['accepted', 'waiting', 'unavailable'].includes(String(value.status))) return
  if (value.desire !== undefined && (typeof value.desire !== 'number' || !Number.isFinite(value.desire) || value.desire < 0 || value.desire > 1)) return
  if (value.intent !== undefined && value.intent !== null && (typeof value.intent !== 'string' || !Object.hasOwn(intents, value.intent))) return
  const probability = typeof value.desire === 'number' ? ` · 开口意愿 ${(value.desire * 100).toFixed(0)}%（未校准）` : ''
  const status = value.status === 'accepted' ? `已请求${intents[String(value.intent)] || '主动接话'}，不代表已经播放`
    : value.status === 'waiting' ? `继续聆听${typeof value.reason === 'string' && Object.hasOwn(reasons, value.reason) ? `：${reasons[value.reason]}` : ''}`
      : '判断不可用，继续聆听'
  return `${sources[value.source]} · ${status}${probability}`
}
