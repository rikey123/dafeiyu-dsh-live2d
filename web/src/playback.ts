export class PlaybackReceipt {
  private states = new Map<string, { consumed: number; boundary?: number }>()
  private held = false
  private invalid = new Set<string>()
  constructor(private readonly complete: (epoch: string, samples: number) => void) {}
  start(epoch: string) { if (this.states.has(epoch) || this.invalid.has(epoch)) return false; if (this.states.size >= 64) { this.interrupt(); return false }; this.states.set(epoch, { consumed: 0 }); return true }
  private retire(epoch: string) { this.states.delete(epoch); this.invalid.add(epoch); while (this.invalid.size > 128) this.invalid.delete(this.invalid.values().next().value!) }
  holdCompletion() { this.held = true }
  acceptsAudio(epoch: string) { return !this.held && this.states.has(epoch) }
  snapshot() { return [...this.states].map(([epoch, state]) => ({ epoch, consumed_samples: state.consumed })) }
  interrupt() { for (const epoch of this.states.keys()) this.retire(epoch); this.held = false }
  consume(samples: number, epoch: string) { const p = this.states.get(epoch); if (!p || !Number.isSafeInteger(samples) || samples <= 0) return; p.consumed += samples; if (p.boundary !== undefined && p.consumed > p.boundary) { this.retire(epoch); return }; this.check(epoch) }
  boundary(epoch: string, samples: number) { const p = this.states.get(epoch); if (!p) return false; if (p.boundary !== undefined || !Number.isSafeInteger(samples) || samples <= 0 || p.consumed > samples) { this.retire(epoch); return false }; p.boundary = samples; this.check(epoch); return true }
  private check(epoch: string) { const p = this.states.get(epoch); if (!this.held && p && p.boundary !== undefined && p.consumed === p.boundary) { this.retire(epoch); this.complete(epoch, p.consumed) } }
}
