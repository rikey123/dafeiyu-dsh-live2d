export type Theme = 'yaya' | 'replicant'

export const themes: Record<Theme, { name: string; tagline: string; color: string }> = {
  yaya: { name: '数字生命', tagline: 'DIGITAL LIFE TERMINAL', color: '#1b201f' },
  replicant: { name: '霓虹全息', tagline: 'HOLOGRAPHIC COMPANION', color: '#12041f' },
}

export function loadTheme(raw: string | null): Theme { return raw === 'replicant' ? 'replicant' : 'yaya' }

/** HH:MM:SS for the connection timecode. */
export function timecode(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000)), pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`
}

/** Keeps the tail of a long streaming reply readable as a two-line subtitle. */
export function subtitleTail(text: string, max = 64) {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (clean.length <= max) return clean
  const cut = clean.slice(-max), boundary = cut.search(/[，。！？；、,.!?;]\s*/)
  return '…' + (boundary >= 0 && boundary < max / 3 ? cut.slice(boundary + 1).trimStart() : cut)
}
