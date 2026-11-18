export type MossVoice = { id: string; name: string; group: string }
export type MossVoiceCatalog = {
  model: 'MOSS-TTS-Nano'; source: 'service' | 'installed_manifest'; default_voice: string; voices: MossVoice[];
}

export function parseMossVoiceCatalog(value: unknown): MossVoiceCatalog {
  const data = value as Partial<MossVoiceCatalog> | null
  if (!data || data.model !== 'MOSS-TTS-Nano' || !['service', 'installed_manifest'].includes(data.source ?? '')
    || !Array.isArray(data.voices) || !data.voices.length || data.voices.length > 256) throw new Error('MOSS 音色清单格式无效')
  const seen = new Set<string>()
  for (const voice of data.voices) {
    if (!voice || [voice.id, voice.name, voice.group].some(v => typeof v !== 'string' || !v.trim() || v.length > 200 || /[\x00-\x1f]/.test(v))
      || voice.id === 'default' || seen.has(voice.id)) throw new Error('MOSS 音色条目无效')
    seen.add(voice.id)
  }
  if (!data.default_voice || !seen.has(data.default_voice)) throw new Error('MOSS 默认音色无效')
  return data as MossVoiceCatalog
}

const groupNames: Record<string, string> = {
  'Chinese Male': '中文男声', 'Chinese Female': '中文女声',
  'English Male': '英文男声', 'English Female': '英文女声',
  'Japanese Male': '日文男声', 'Japanese Female': '日文女声',
}
export function mossVoiceGroups(voices: MossVoice[]) {
  const groups = new Map<string, MossVoice[]>()
  for (const voice of voices) {
    const group = groupNames[voice.group] ?? voice.group
    if (!groups.has(group)) groups.set(group, [])
    groups.get(group)!.push(voice)
  }
  return [...groups.entries()]
}

export const mossVoiceLabel = (voice: MossVoice) => `${voice.id} · ${voice.name.replace(/^(CN|EN|JP)\s+/, '')}`
