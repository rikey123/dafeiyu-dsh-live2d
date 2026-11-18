import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MossVoiceOptions } from './MossVoicePicker'
import { mossVoiceGroups, parseMossVoiceCatalog } from './mossVoices'

const payload = { model: 'MOSS-TTS-Nano', source: 'installed_manifest', default_voice: 'Junhao', voices: [
  { id: 'Junhao', name: 'CN 欢迎关注模思智能', group: 'Chinese Male' },
  { id: 'Lingyu', name: 'CN 深夜电台', group: 'Chinese Female' },
  { id: 'Ava', name: 'EN The Bitter Lesson', group: 'English Female' },
] }
const catalog = parseMossVoiceCatalog(payload)

describe('manifest-driven MOSS voices', () => {
  it('groups real IDs by language and gender without guessing voice names', () => {
    expect(mossVoiceGroups(catalog.voices).map(([name]) => name)).toEqual(['中文男声', '中文女声', '英文女声'])
    const html = renderToStaticMarkup(<select value="Lingyu" onChange={() => {}}><MossVoiceOptions value="Lingyu" catalog={catalog}/></select>)
    expect(html).toContain('默认（Junhao · 欢迎关注模思智能）')
    expect(html).toContain('<option value="Lingyu" selected="">Lingyu · 深夜电台</option>')
    expect(html).toContain('<optgroup label="英文女声">')
    expect(html).not.toContain('<input')
  })
  it('preserves unknown saved IDs without silently changing the voice', () => {
    const html = renderToStaticMarkup(<select value="old-id" onChange={() => {}}><MossVoiceOptions value="old-id" catalog={catalog}/></select>)
    expect(html).toContain('<option value="old-id" disabled="" selected="">')
    expect(html).toContain('当前模型不包含，请重新选择')
  })
  it('does not fabricate voice lists while offline', () => {
    const html = renderToStaticMarkup(<MossVoiceOptions value="Lingyu"/>)
    expect(html).toContain('尚未核验')
    expect(html).not.toContain('深夜电台')
    expect(html).not.toContain('optgroup')
  })
  it.each([null, {}, { ...payload, model: 'MOSS-Live' }, { ...payload, voices: [] },
    { ...payload, voices: [payload.voices[0], payload.voices[0]] }, { ...payload, default_voice: 'absent' },
    { ...payload, voices: [{ id: 'x', group: 'x', name: 2 }] }])('rejects malformed catalog %j', value => {
    expect(() => parseMossVoiceCatalog(value)).toThrow()
  })
})
