import { expect, it } from 'vitest'
import { settingsUpdate } from './settingsUpdate'

it('saves both values of the experimental setting without overwriting owner voice state', () => {
  for (const enabled of [true, false]) {
    const update = settingsUpdate({ streaming_asr_preview: enabled, owner_voice_only: true, api_key_set: true })
    expect(JSON.parse(JSON.stringify(update))).toEqual({ streaming_asr_preview: enabled })
  }
})

it('never submits server-only TTS key presence and preserves deliberate key deletion', () => {
  const update = settingsUpdate({ tts_mode: 'api', tts_api_key_set: true, tts_api_key: '', clear_tts_api_key: true })
  expect(update).toEqual({ tts_mode: 'api', tts_api_key: '', clear_tts_api_key: true })
})

it('redacts the MOSS key status and preserves independent key updates', () => {
  expect(settingsUpdate({ moss_live_api_key_set: true, moss_live_api_key: 'replacement', conversation_mode: 'moss_live' })).toEqual({ moss_live_api_key: 'replacement', conversation_mode: 'moss_live' })
})

it('keeps Ark and TokenToSea credentials independent and removes read-only markers', () => {
  expect(settingsUpdate({ systemone_provider: 'ark', systemone_api_key_set: true, systemone_ark_api_key_set: true,
    systemone_ark_api_key: '', clear_systemone_ark_api_key: true })).toEqual({ systemone_provider: 'ark', systemone_ark_api_key: '', clear_systemone_ark_api_key: true })
})

it('omits DSH owned model configuration and presentation markers', () => {
  expect(settingsUpdate({ harness_provider: 'dsh', memory_owner: 'dsh', screen_model_ready: true, llm_base_url: 'old', llm_model: 'old', llm_api_key: 'old', system_prompt: 'persona', temperature: 0.7 })).toEqual({ system_prompt: 'persona' })
})
