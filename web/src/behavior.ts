export type Behavior = {
  emotion?: 'neutral' | 'happy' | 'sad' | 'surprised';
  expression?: 'natural' | 'blush' | 'heart_eyes' | 'dizzy' | 'squeezed' | 'smug' | 'tears' | 'sweat' | 'shadow';
  gesture?: 'none' | 'chest' | 'finger' | 'grass'; energy?: number;
}
export const behaviorExpressions = { natural: '', blush: '脸红', heart_eyes: '爱心眼', dizzy: '圈圈眼', squeezed: '＞＜', smug: '屑屑眼', tears: '流泪', sweat: '流冷汗', shadow: '黑脸' }
export const behaviorSources = { 'clef-omni': 'Clef Omni', 'doubao-systemone': '豆包 System One' }
export type BehaviorSource = keyof typeof behaviorSources
export type AppliedBehavior = Behavior & { source: BehaviorSource }
export function isBehaviorSource(value: unknown): value is BehaviorSource { return typeof value === 'string' && Object.prototype.hasOwnProperty.call(behaviorSources, value) }
export function parseBehavior(raw: unknown): Behavior | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return
  const value = raw as Record<string, unknown>
  if (!Object.keys(value).length || Object.keys(value).some(key => !['emotion', 'expression', 'gesture', 'energy'].includes(key))) return
  if (value.emotion !== undefined && !['neutral', 'happy', 'sad', 'surprised'].includes(value.emotion as string)) return
  if (value.expression !== undefined && (typeof value.expression !== 'string' || !Object.prototype.hasOwnProperty.call(behaviorExpressions, value.expression))) return
  if (value.gesture !== undefined && !['none', 'chest', 'finger', 'grass'].includes(value.gesture as string)) return
  if (value.energy !== undefined && (typeof value.energy !== 'number' || !Number.isFinite(value.energy) || value.energy < 0 || value.energy > 1)) return
  return value as Behavior
}

/** An urgent decision may precede start; it never activates before PCM consumption. */
export class BehaviorQueue {
  private pending = new Map<string, AppliedBehavior>()
  private started = new Set<string>()
  private received = new Set<string>()
  private retired = new Set<string>()
  current?: string
  start(epoch: string) { if (!this.retired.has(epoch)) this.started.add(epoch) }
  receive(epoch: string, raw: unknown, source: BehaviorSource = 'clef-omni') {
    if (this.retired.has(epoch) || this.received.has(epoch)) return
    const parsed = parseBehavior(raw); if (!parsed || !isBehaviorSource(source)) return
    const value = { ...parsed, source }
    this.received.add(epoch); this.pending.set(epoch, value)
    while (this.pending.size > 64) this.retire(this.pending.keys().next().value!)
    return this.current === epoch ? value : undefined
  }
  consume(epoch: string) {
    if (!this.started.has(epoch) || this.retired.has(epoch) || this.current === epoch) return
    this.current = epoch
    return { behavior: this.pending.get(epoch) }
  }
  finish(epoch: string) { const active = this.current === epoch; this.retire(epoch); return active }
  clear() { for (const epoch of new Set([...this.started, ...this.pending.keys()])) this.retire(epoch); this.current = undefined }
  private retire(epoch: string) {
    this.pending.delete(epoch); this.started.delete(epoch); this.received.delete(epoch); this.retired.add(epoch)
    if (this.current === epoch) this.current = undefined
    while (this.retired.size > 128) this.retired.delete(this.retired.values().next().value!)
  }
}
