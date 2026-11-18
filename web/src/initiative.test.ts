import { expect, it } from 'vitest'
import { initiativeStatus } from './initiative'

const event = { type: 'voice.initiative', source: 'doubao-systemone', status: 'accepted', intent: 'empathize', desire: .96 }
it('shows actual provider, uncalibrated willingness and distinguishes acceptance from playback', () => {
  expect(initiativeStatus(event)).toContain('豆包 System One')
  expect(initiativeStatus(event)).toContain('已请求及时共情，不代表已经播放')
  expect(initiativeStatus(event)).toContain('96%（未校准）')
  expect(initiativeStatus({ ...event, source: 'clef-omni', status: 'waiting', reason: 'respect_floor' })).toContain('Clef Omni · 继续聆听：尊重话语权')
  expect(initiativeStatus({ ...event, status: 'unavailable' })).toContain('继续聆听')
})
it('rejects unknown states, providers, intents and malformed probabilities', () => {
  for (const patch of [{ status: 'speaking' }, { source: 'rules' }, { intent: 'execute_command' },
    { desire: NaN }, { desire: Infinity }, { desire: 2 }, { desire: '0.9' }, { source: '__proto__' }]) {
    expect(initiativeStatus({ ...event, ...patch })).toBeUndefined()
  }
  expect(initiativeStatus(null)).toBeUndefined()
})
