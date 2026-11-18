// DeepSeek-chan (大肥鱼) skin layers.
// Parameter IDs come from the supplied model's cdi3/exp3 files; gesture poses are the
// final keyframe values of the model's own "切出来" motion3 files, blended by weight.

export type Wardrobe = {
  glasses: 'none' | 'mono' | 'frame'
  basin: boolean
  teeth: boolean
  tail: boolean
  longSkirt: boolean
  chestCloth: boolean
  barefoot: boolean
  size: number
  gesture: Gesture
  reactive: boolean
}
export type Gesture = 'none' | 'chest' | 'grass' | 'finger'
export type Activity = 'idle' | 'listening' | 'thinking' | 'speaking'

export const defaultWardrobe: Wardrobe = { glasses: 'none', basin: false, teeth: false, tail: false, longSkirt: false, chestCloth: false, barefoot: false, size: 0, gesture: 'none', reactive: true }

/** Face expressions exposed by the skin (exp3 names) with short UI labels. */
export const faceExpressions: { name: string; label: string }[] = [
  { name: '', label: '自然' }, { name: '脸红', label: '脸红' }, { name: '爱心眼', label: '爱心眼' },
  { name: '圈圈眼', label: '圈圈眼' }, { name: '＞＜', label: '＞＜' }, { name: '屑屑眼', label: '屑屑眼' },
  { name: '流泪', label: '流泪' }, { name: '流冷汗', label: '冷汗' }, { name: '黑脸', label: '黑脸' },
]

const poses: Record<Exclude<Gesture, 'none'>, Record<string, number>> = {
  chest: { Movement2: 1, Param62: 0.034, Param59: 0.476, Param60: 0.86, Param61: 0.002 },
  grass: { Movement1: 1, Param36: 0.04, Param39: 0.2, Param41: -0.732 },
  finger: { Movement3: 1, Param40: 1, Param39: 0.322, Param41: 0.702 },
}
export const gestureLabels: Record<Gesture, string> = { none: '默认', chest: '抚胸', grass: '狗尾草', finger: '竖食指' }

/** Every parameter this module may drive, so released layers can ease back to default. */
export const wardrobeParameters = ['key8', 'key9', 'key10', 'key11', 'key12', 'Clothes1', 'Clothes2', 'Clothes3', 'Clothes4', 'Clothes5', 'LeanInput', ...new Set(Object.values(poses).flatMap(Object.keys))]

/** Absolute offsets (added to each parameter's default) for the current outfit and activity. */
export function wardrobeTargets(w: Wardrobe, activity: Activity, automaticGesture?: Gesture): Record<string, number> {
  const out: Record<string, number> = {}
  if (w.glasses === 'frame') out.key11 = 1
  if (w.glasses === 'mono') out.key12 = 1
  if (w.basin) out.key10 = 1
  if (w.teeth) out.key9 = 1
  if (w.tail) out.Clothes5 = -1
  if (w.longSkirt) out.Clothes1 = -1
  if (w.chestCloth) out.Clothes3 = 1
  if (w.barefoot) out.Clothes4 = 1
  if (w.size) out.Clothes2 = Math.max(0, Math.min(1, w.size))
  let gesture = w.gesture
  if (w.reactive) {
    if (gesture === 'none' && automaticGesture !== undefined) gesture = automaticGesture
    if (activity === 'listening') out.LeanInput = -12
    if (activity === 'thinking') { out.key8 = 1; if (gesture === 'none') gesture = 'finger' }
  }
  if (gesture !== 'none') Object.assign(out, poses[gesture])
  return out
}

export function loadWardrobe(raw: string | null): Wardrobe {
  try {
    const value = raw ? JSON.parse(raw) as Partial<Wardrobe> : {}
    const merged = { ...defaultWardrobe, ...value }
    if (!['none', 'mono', 'frame'].includes(merged.glasses)) merged.glasses = 'none'
    if (!['none', 'chest', 'grass', 'finger'].includes(merged.gesture)) merged.gesture = 'none'
    merged.size = Number.isFinite(merged.size) ? Math.max(0, Math.min(1, merged.size)) : 0
    return merged
  } catch { return { ...defaultWardrobe } }
}

/** Eases current layer weights toward targets; returns parameters that still need writing. */
export function easeLayers(current: Map<string, number>, targets: Record<string, number>, dt: number, rate = 7) {
  const k = 1 - Math.exp(-dt * rate)
  for (const id of new Set([...current.keys(), ...Object.keys(targets)])) {
    const target = targets[id] ?? 0, value = current.get(id) ?? 0
    const next = Math.abs(target - value) < 1e-3 ? target : value + (target - value) * k
    if (next === 0 && target === 0) current.delete(id); else current.set(id, next)
  }
  return current
}
