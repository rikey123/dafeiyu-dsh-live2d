import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SystemOnePreferences, systemOneDefaults, decisionReasons, initiativeDefaults, initiativeParameters } from './systemoneSettings'

it('defaults to Ark, explains independent credentials and never claims live readiness', () => {
  const html = renderToStaticMarkup(<SystemOnePreferences settings={systemOneDefaults} saved={systemOneDefaults} native={false} onChange={() => {}} />)
  expect(html).toContain('方舟 API Key')
  expect(html).toContain('doubao-seed-2-1-lite-260915')
  expect(html).toContain('不会采集图片或视频')
  expect(html).toContain('不自动跨供应商回退')
  expect(html).toContain('默认阈值尚未校准')
  expect(html).toMatch(/<button[^>]+disabled=""/)
})

it('blocks testing an unsaved provider or endpoint even when both keys exist', () => {
  const configured = { ...systemOneDefaults, systemone_ark_api_key_set: true, systemone_api_key_set: true }
  for (const settings of [{ ...configured, systemone_provider: 'tokentosea' as const }, { ...configured, systemone_ark_model: 'ep-new' }]) {
    const html = renderToStaticMarkup(<SystemOnePreferences settings={settings} saved={configured} native={false} onChange={() => {}} />)
    expect(html).toMatch(/<button[^>]+disabled=""/)
  }
  const saved = renderToStaticMarkup(<SystemOnePreferences settings={configured} saved={configured} native={false} onChange={() => {}} />)
  expect(saved).not.toMatch(/<button[^>]+disabled=""/)
})

it('distinguishes provider restriction from a bad key and retains explicit overseas consent', () => {
  const settings = { ...systemOneDefaults, systemone_provider: 'tokentosea' as const }
  const html = renderToStaticMarkup(<SystemOnePreferences settings={settings} saved={settings} native={false} onChange={() => {}} />)
  expect(html).toContain('TokenToSea 海外服务')
  expect(decisionReasons.region_restricted).not.toBe(decisionReasons.authentication)
})

it('keeps assistant initiative opt-in and explains limits and the independent local preview', () => {
  expect(systemOneDefaults.systemone_initiative_enabled).toBe(false)
  const settings = { ...systemOneDefaults, systemone_enabled: true, systemone_initiative_enabled: true }
  const html = renderToStaticMarkup(<SystemOnePreferences settings={settings} saved={settings} native={false} onChange={() => {}} />)
  expect(html).toContain('允许助手主动接话')
  expect(html).toContain('最多判断 3 次')
  expect(html).toContain('不依赖额外 ASR 模型')
  expect(html).toContain('建议约 48 字符，完整句优先，不强制截断')
  expect(html).toContain('默认概率尚未真人校准')
})

it('disables initiative without duplex or while owner-only filtering is active', () => {
  const settings = { ...systemOneDefaults, systemone_enabled: true }
  for (const props of [{ conversationMode: 'pipeline' }, { ownerOnly: true }, { native: true }]) {
    const html = renderToStaticMarkup(<SystemOnePreferences settings={settings} saved={settings} native={false} onChange={() => {}} {...props} />)
    expect(html).toMatch(/<input[^>]*aria-label="允许助手主动接话"[^>]*disabled=""/)
  }
})

it('exposes primary parameters while initiative is off, with consistent bounds and defaults', () => {
  const html = renderToStaticMarkup(<SystemOnePreferences settings={systemOneDefaults} saved={systemOneDefaults} native={false} onChange={() => {}} />)
  const fields = html.slice(html.indexOf('<section aria-label="主动接话参数"'))
  const advanced = fields.indexOf('<details>')
  for (const spec of initiativeParameters) {
    const index = fields.indexOf(`aria-label="${spec.label}"`)
    expect(index).toBeGreaterThan(0)
    expect(index < advanced).toBe(!spec.advanced)
    expect(fields).toContain(`min="${spec.min}" max="${spec.max}" step="${spec.step}"`)
    expect(systemOneDefaults[spec.key]).toBe(initiativeDefaults[spec.key])
    expect(initiativeDefaults[spec.key]).toBeGreaterThanOrEqual(spec.min)
    expect(initiativeDefaults[spec.key]).toBeLessThanOrEqual(spec.max)
  }
  expect(fields).toContain('恢复主动接话默认参数')
  expect(html).toContain('与上方“助手主动接话”的意愿阈值相互独立')
  expect(html).toContain('再次开启麦克风后使用新参数')
})

it('renders custom values and summaries instead of hardcoded limits', () => {
  const settings = { ...systemOneDefaults, systemone_initiative_max_probes: 5,
    systemone_initiative_max_reply_chars: 24, systemone_initiative_wait_threshold: .1 }
  const html = renderToStaticMarkup(<SystemOnePreferences settings={settings} saved={settings} native={false} onChange={() => {}} />)
  expect(html).toContain('最多判断 5 次')
  expect(html).toContain('建议约 24 字符，完整句优先，不强制截断')
  expect(html).toContain('高于 0.1 就不开口')
})
