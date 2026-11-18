import { describe, expect, it, vi } from 'vitest'
import { bindClassifierMessages, RealtimeLipSync } from './realtime'

const vowel = { volume: 1, weights: { A: 1 } }
const zero = { A: 0, E: 0, I: 0, O: 0, U: 0 }

describe('realtime playback-clock lip gate', () => {
  it('filters late messages before they mutate the upstream smoothing state', () => {
    const gate = new RealtimeLipSync(), upstream = vi.fn()
    const port = { onmessage: upstream } as unknown as MessagePort
    const release = bindClassifierMessages(port, gate, () => 2)
    const emit = (timestamp: number) => port.onmessage?.call(port, { data: { timestamp } } as MessageEvent)
    emit(1.95)
    expect(upstream).toHaveBeenCalledOnce()
    expect(upstream.mock.contexts[0]).toBe(port)
    emit(1.9); emit(1.95); emit(NaN); emit(3)
    expect(upstream).toHaveBeenCalledOnce()
    gate.reset(1.97)
    emit(1.96)
    expect(upstream).toHaveBeenCalledOnce()
    emit(1.99)
    expect(upstream).toHaveBeenCalledTimes(2)
    release(); release()
    expect(port.onmessage).toBeNull()
  })
  it('does not move before actual PCM consumption', () => {
    const gate = new RealtimeLipSync()
    gate.frame(1, 1)
    expect(gate.value(vowel, 1, true, true)).toEqual(zero)
    gate.consumed(1)
    expect(gate.value(vowel, 1.016, true, true)?.A).toBeGreaterThan(0)
  })
  it.each([[false, true], [true, false]])('closes immediately on mute/suspend (%s, %s)', (audible, running) => {
    const gate = new RealtimeLipSync()
    gate.frame(1, 1); gate.consumed(1)
    expect(gate.value(vowel, 1, true, true)?.A).toBeGreaterThan(0)
    expect(gate.value(vowel, 1.01, audible, running)).toEqual(zero)
  })
  it('discards delayed pre-stop frames and resumes only with fresh audio', () => {
    const gate = new RealtimeLipSync()
    gate.frame(1, 1); gate.consumed(1); gate.value(vowel, 1, true, true)
    gate.reset(1.1)
    expect(gate.frame(1.05, 1.2)).toBe(false)
    expect(gate.value(vowel, 1.2, true, true)).toEqual(zero)
    gate.consumed(1.21)
    expect(gate.value(vowel, 1.21, true, true)).toBeUndefined() // visible RMS fallback, not old A
    expect(gate.frame(1.22, 1.22)).toBe(true)
    expect(gate.value(vowel, 1.22, true, true)?.A).toBeGreaterThan(0)
  })
  it('closes on an output underrun without waiting for a bot-stop event', () => {
    const gate = new RealtimeLipSync()
    gate.frame(1, 1); gate.consumed(1)
    gate.value(vowel, 1, true, true)
    expect(gate.value(vowel, 1.13, true, true)).toEqual(zero)
  })
  it('uses RMS rather than frozen vowels when the classifier stops reporting', () => {
    const gate = new RealtimeLipSync()
    gate.frame(1, 1); gate.consumed(1.2)
    expect(gate.value(vowel, 1.2, true, true)).toBeUndefined()
  })
  it('ignores invalid, duplicate and out-of-order frame timestamps', () => {
    const gate = new RealtimeLipSync()
    for (const at of [NaN, Infinity, '1', -1, 10]) expect(gate.frame(at, 1)).toBe(false)
    expect(gate.frame(1, 1)).toBe(true)
    expect(gate.frame(1, 1)).toBe(false)
    expect(gate.frame(.9, 1)).toBe(false)
  })
})
