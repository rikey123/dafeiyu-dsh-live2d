import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReconnectBackoff } from './reconnect'

describe('connection retry', () => {
  afterEach(() => vi.useRealTimers())
  it('backs off, avoids duplicate attempts and resets after a successful connection', () => {
    vi.useFakeTimers(); const backoff = new ReconnectBackoff(), retry = vi.fn()
    expect(backoff.schedule(retry)).toBe(1000); expect(backoff.schedule(retry)).toBeUndefined(); vi.advanceTimersByTime(999); expect(retry).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1); expect(retry).toHaveBeenCalledTimes(1)
    backoff.schedule(retry); vi.advanceTimersByTime(1999); expect(retry).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1); expect(retry).toHaveBeenCalledTimes(2)
    backoff.reset(); backoff.schedule(retry); vi.advanceTimersByTime(1000); expect(retry).toHaveBeenCalledTimes(3)
  })
  it('cancels a pending retry on session switch or unmount', () => {
    vi.useFakeTimers(); const backoff = new ReconnectBackoff(), retry = vi.fn()
    backoff.schedule(retry); backoff.cancel(); vi.advanceTimersByTime(60000); expect(retry).not.toHaveBeenCalled()
  })
})
