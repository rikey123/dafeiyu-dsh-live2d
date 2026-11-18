import { afterEach, describe, expect, it, vi } from 'vitest'
import { audioInputs, microphoneError } from './microphone'

afterEach(() => vi.unstubAllGlobals())

describe('microphone diagnostics', () => {
  it.each([
    ['NotFoundError', '未找到可用麦克风'],
    ['NotAllowedError', '访问被拒绝'],
    ['NotReadableError', '独占设备'],
    ['OverconstrainedError', '重新选择'],
    ['SecurityError', 'HTTPS'],
  ])('explains %s and keeps the original browser code', (code, hint) => {
    const message = microphoneError(new DOMException('native message', code))
    expect(message).toContain(hint)
    expect(message).toContain(code)
  })
  it('retains unexpected errors for diagnosis', () => {
    expect(microphoneError(new Error('Worklet failed'))).toBe('Worklet failed')
    expect(microphoneError(null)).toBe('null')
  })
  it('lists inputs without acquiring a stream or requesting permissions', async () => {
    const input = { kind: 'audioinput', deviceId: 'usb-mic' }
    const getUserMedia = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: { enumerateDevices: vi.fn().mockResolvedValue([input, { kind: 'audiooutput' }]), getUserMedia } })
    expect(await audioInputs()).toEqual([input])
    expect(getUserMedia).not.toHaveBeenCalled()
  })
  it('explains an unavailable mediaDevices API', async () => {
    vi.stubGlobal('navigator', {})
    await expect(audioInputs()).rejects.toMatchObject({ name: 'SecurityError' })
  })
})
