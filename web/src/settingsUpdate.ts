export function settingsUpdate<T extends { api_key_set?: boolean; tts_api_key_set?: boolean; moss_live_api_key_set?: boolean; systemone_api_key_set?: boolean; systemone_ark_api_key_set?: boolean; owner_voice_only?: boolean; harness_provider?: string; memory_owner?: string; screen_model_ready?: boolean }>(settings: T) {
  const { api_key_set: _keySet, tts_api_key_set: _ttsKeySet, moss_live_api_key_set: _mossKeySet, systemone_api_key_set: _decisionKeySet, systemone_ark_api_key_set: _arkKeySet, owner_voice_only: _ownerVoiceOnly, harness_provider: _harnessProvider, memory_owner: _memoryOwner, screen_model_ready:_screenReady, ...update } = settings
  if (settings.harness_provider === 'dsh') {
    const { llm_base_url: _base, llm_model: _model, llm_api_key: _key, temperature: _temperature, ...dshUpdate } = update as typeof update & { llm_base_url?: unknown; llm_model?: unknown; llm_api_key?: unknown; temperature?: unknown }
    return dshUpdate
  }
  return update
}
