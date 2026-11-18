export class EmotionQueue {
  private pending = new Map<string, string>()
  private active = new Set<string>()
  private seen = new Set<string>()
  start(epoch: string) { if (this.active.size >= 64) this.clear(); this.active.add(epoch) }
  push(epoch: string, value: string) { if (this.active.has(epoch) && !this.seen.has(epoch)) { this.seen.add(epoch); this.pending.set(epoch, value) } }
  consume(epoch: string) { const value = this.pending.get(epoch); this.pending.delete(epoch); return value }
  finish(epoch: string) { this.pending.delete(epoch); this.active.delete(epoch); this.seen.delete(epoch) }
  clear() { this.pending.clear(); this.active.clear(); this.seen.clear() }
}
