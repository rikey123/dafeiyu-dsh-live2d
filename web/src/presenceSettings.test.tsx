import { expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { idleFields, presenceDefaults, PresencePreferences } from './presenceSettings'
import { screenDefaults } from './screenCompanion'
import { settingsUpdate } from './settingsUpdate'

it('round trips presence defaults and values through DSH settings serialization', () => {
  expect(presenceDefaults).toEqual({companion_interests:'',idle_companion_enabled:false,idle_companion_after_s:120,idle_companion_cooldown_s:180,idle_companion_max_per_hour:6,idle_companion_include_screen:true,idle_companion_max_reply_chars:64})
  const saved = {...presenceDefaults, screen_companion_mode:screenDefaults.screen_companion_mode, companion_interests:'游戏\n电影', idle_companion_enabled:true}
  expect({...presenceDefaults,...settingsUpdate({...saved,harness_provider:'dsh'})}).toEqual(saved)
})
it('renders multiline interests and bounded independent idle controls, including for MOSS', () => {
  const html = renderToStaticMarkup(<PresencePreferences settings={presenceDefaults} native={false} onChange={vi.fn()}/>)
  expect(html).toContain('maxLength="2000"')
  expect(html).toContain('textarea')
  expect(html).toContain('无需开启屏幕陪玩或分享屏幕')
  for (const [key,label,min,max] of idleFields) {
    expect(html).toContain(`aria-label="${label}" type="number" required="" min="${min}" max="${max}" step="1" value="${presenceDefaults[key]}"`)
  }
  const native = renderToStaticMarkup(<PresencePreferences settings={presenceDefaults} native={true} onChange={vi.fn()}/>)
  expect(native).toMatch(/aria-label="空闲时主动聊天"[^>]*disabled=""/)
  const standalone=renderToStaticMarkup(<PresencePreferences settings={presenceDefaults} native={false} dsh={false} onChange={vi.fn()}/>)
  expect(standalone).toMatch(/aria-label="空闲时主动聊天"[^>]*disabled=""/)
  expect(standalone).toContain('需要使用 DSH 插件模式')
})
