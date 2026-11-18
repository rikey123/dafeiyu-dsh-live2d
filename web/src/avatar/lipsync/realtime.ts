import { createWLipSyncVowelDriver, type WLipSyncFrame, type WLipSyncVowelWeights } from './vowel-driver'

const empty = (): WLipSyncVowelWeights => ({ A: 0, E: 0, I: 0, O: 0, U: 0 })
const MAX_FRAME_AGE_S = .12

/** Validate before the upstream smoother sees a message. A late timestamp
 * must not rewind its delta time or replace the weights of a newer frame. */
export function bindClassifierMessages(port: MessagePort, gate: RealtimeLipSync, audioTime: () => number) {
  const upstream = port.onmessage
  const filtered: MessagePort['onmessage'] = event => {
    if (gate.frame(event.data?.timestamp, audioTime())) upstream?.call(port, event)
  }
  port.onmessage = filtered
  return () => { if (port.onmessage === filtered) port.onmessage = null }
}

/** Playback-clock gate around the upstream classifier. No text, forced
 * alignment or extra audio buffering. Reject stale pre-interruption frames. */
export class RealtimeLipSync {
  private driver = createWLipSyncVowelDriver()
  private resetAt = 0
  private frameAt = -Infinity
  private consumedAt = -Infinity
  private renderAt: number | undefined

  reset(audioTime: number) {
    this.resetAt = audioTime
    this.frameAt = this.consumedAt = -Infinity
    this.renderAt = undefined
    this.driver.reset()
  }

  consumed(audioTime: number) { this.consumedAt = audioTime }

  frame(timestamp: unknown, audioTime: number) {
    if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= this.resetAt || timestamp > audioTime + .02 || timestamp <= this.frameAt) return false
    this.frameAt = timestamp
    return true
  }

  playing(audioTime: number) { return audioTime >= this.consumedAt && audioTime - this.consumedAt <= MAX_FRAME_AGE_S }

  value(frame: WLipSyncFrame | undefined, audioTime: number, audible: boolean, running: boolean): WLipSyncVowelWeights | undefined {
    const elapsed = this.renderAt === undefined ? .016 : Math.min(.05, Math.max(0, audioTime - this.renderAt))
    this.renderAt = audioTime
    if (!running || !audible || !this.playing(audioTime)) {
      this.driver.reset()
      return empty()
    }
    // A failed/loading classifier explicitly uses RMS, never stale vowels.
    if (!frame || audioTime - this.frameAt > MAX_FRAME_AGE_S) {
      this.driver.reset()
      return undefined
    }
    return this.driver.update(frame, elapsed)
  }
}
