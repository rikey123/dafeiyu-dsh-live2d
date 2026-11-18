export type Vowels = Record<'A' | 'E' | 'I' | 'O' | 'U', number>
import mappings from './mouth-mappings.json'
export type MouthCore = {
  _model?: { parameters?: { ids?: ArrayLike<string> } }
  getParameterIndex(id: string): number
  getParameterMinimumValue(index: number): number
  getParameterMaximumValue(index: number): number
  getParameterDefaultValue(index: number): number
  setParameterValueById(id: string, value: number): void
}
export function mouthTargets(v: Vowels | undefined, open: number, profile: 'default' | 'deepseek' = 'deepseek'): Record<string, number> {
  const values: Record<string, number> = { ...v, open }
  return Object.fromEntries(Object.entries(mappings[profile]).map(([id, weights]) => [id, Object.entries(weights).reduce((sum, [key, weight]) => sum + (values[key] ?? 0) * weight, 0)]))
}
export function applyMouth(core: MouthCore, targets: Record<string, number>) {
  const ids = core._model?.parameters?.ids
  if (!ids) return
  const existing = new Set(Array.from(ids))
  for (const [id, value] of Object.entries(targets)) {
    if (!existing.has(id) || !Number.isFinite(value)) continue
    const index = core.getParameterIndex(id), min = core.getParameterMinimumValue(index), max = core.getParameterMaximumValue(index), base = core.getParameterDefaultValue(index)
    if (Number.isFinite(min) && Number.isFinite(max) && Number.isFinite(base)) core.setParameterValueById(id, Math.max(min, Math.min(max, base + value)))
  }
}
