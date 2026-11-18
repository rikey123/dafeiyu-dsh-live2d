import { describe, expect, it } from 'vitest'
import { serviceDetail } from './serviceStatus'

describe('optional service status', () => {
  it.each([['loading', '加载中'], ['warming', '预热中'], ['error', '加载失败']])('does not present %s as ready', (state, label) => {
    const detail = serviceDetail({ ready: false, state, resident: false })
    expect(detail).toContain(label)
    expect(detail).not.toContain('已就绪')
    expect(detail).not.toContain('常驻显存')
  })

  it('identifies a verified resident prewarmed model', () => {
    expect(serviceDetail({ ready: true, warmed_up: true, resident: true })).toContain('已就绪 · 已预热 · 模式期间常驻显存')
  })
  it('distinguishes requested precision from an unloaded model', () => {
    const detail = serviceDetail({ ready: false, model_name: 'Fun-CosyVoice3-0.5B', model_version: '3', precision_requested: 'fp16', precision: null })
    expect(detail).toContain('未就绪')
    expect(detail).toContain('模型：Fun-CosyVoice3-0.5B')
    expect(detail).toContain('模型版本：3')
    expect(detail).toContain('请求精度：fp16')
    expect(detail).not.toContain('实际精度')
  })

  it('reports actual precision only when returned by the service', () => {
    expect(serviceDetail({ ready: true, precision_requested: 'fp16', precision: 'fp32' })).toContain('请求精度：fp16 · 实际精度：fp32')
  })
})
