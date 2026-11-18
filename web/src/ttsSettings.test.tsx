import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { TTSPreferences, ttsDefaults } from './ttsSettings'

describe('speech mode preferences', () => {
  it('shows IndexTTS, MOSS CPU and independent duplex interaction', () => {
    const html = renderToStaticMarkup(<TTSPreferences settings={{ ...ttsDefaults, tts_mode: 'gpu' }} onChange={() => {}}/>)
    expect(html).toContain('IndexTTS-2.5')
    expect(html).toContain('MOSS-TTS-Nano ONNX')
    expect(html).toContain('全双工交互')
    expect(html).toContain('DeepSeek')
    expect(html).not.toContain('CosyVoice')
    expect(html).toContain('http://127.0.0.1:8770')
    expect(html).toContain('保存启用后立即加载并预热')
    expect(html).toContain('重新准备 GPU 模型')
    expect(html).not.toContain('MFA')
    expect(html).not.toContain('音素对齐<select')
    expect(html).toContain('随实际播放音频实时分析')
  })
  it('retains the API provider without local model controls', () => {
    const html = renderToStaticMarkup(<TTSPreferences settings={{ ...ttsDefaults, tts_mode: 'api' }} onChange={() => {}}/>)
    expect(html).toContain('TTS API 密钥')
    expect(html).toContain('DeepSeek 官方 TTS')
    expect(html).toContain('海星 · 女声（stella）')
    expect(html).toContain('暗潮 · 男声（tide）')
    expect(html).toContain('https://api.deepseek.com/v1')
    expect(html).toContain('朗读前过滤 Markdown')
    expect(html).toContain('DSH 登录凭据不等于 TTS API Key')
    expect(html).not.toContain('TTS 模型<input')
    expect(html).not.toContain('API 语速（0.25–4）')
    expect(html).not.toContain('IndexTTS-2.5 服务地址')
    expect(html).not.toContain('MOSS ONNX 服务地址')
    expect(html).not.toContain('GPU 语音模型')
  })
  it('retains explicitly selected compatible API configuration', () => {
    const html = renderToStaticMarkup(<TTSPreferences settings={{ ...ttsDefaults, tts_mode: 'api', tts_api_provider: 'openai_compatible', tts_api_model: 'custom-tts', tts_api_voice: 'custom-voice' }} onChange={() => {}}/>)
    expect(html).toContain('custom-tts')
    expect(html).toContain('custom-voice')
    expect(html).toContain('API 语速（0.25–4）')
    expect(html).not.toContain('DeepSeek 音色<select')
  })
  it('offers turbo without mixing its reference voice with MOSS presets', () => {
    const html = renderToStaticMarkup(<TTSPreferences settings={{ ...ttsDefaults, tts_mode: 'gpu', gpu_tts_model: 'gpt_sovits' }} onChange={() => {}}/>)
    expect(html).toContain('本地 GPU · GPT-SoVITS v5 turbo')
    expect(html).toContain('IndexTTS-2.5 · BF16')
    expect(html).toContain('四步合成')
    expect(html).not.toContain('MOSS 内置音色')
  })
  it.each(['cpu', 'auto', 'legacy'] as const)('offers a catalog select rather than free-text voice for %s', tts_mode => {
    const html = renderToStaticMarkup(<TTSPreferences settings={{ ...ttsDefaults, tts_mode, voice: 'Lingyu' }} onChange={() => {}}/>)
    expect(html).toContain('aria-label="MOSS 内置音色"')
    expect(html).toContain('刷新 MOSS 音色')
    expect(html).not.toContain('placeholder="default"')
    expect(html).toContain('value="Lingyu"')
  })
})

it('exposes an independent cloud speech model mode and hides local TTS controls', () => {
  const html = renderToStaticMarkup(<TTSPreferences settings={{ ...ttsDefaults, conversation_mode: 'moss_live', moss_live_api_key_set: true }} onChange={() => {}}/>)
  expect(html).toContain('MOSS-Live'); expect(html).toContain('DeepSeek')
  expect(html).toContain('moss-live-1.0-2026-11-02')
  expect(html).not.toContain('http://127.0.0.1:8770')
  expect(html).not.toContain('http://127.0.0.1:8772')
})
