/** RMS of the recent output waveform, scaled to the Live2D mouth range. */
export function mouthLevel(samples: Float32Array) {
  if (!samples.length) return 0
  let sum = 0
  for (const sample of samples) sum += sample * sample
  return Math.min(1, Math.sqrt(sum / samples.length) * 7)
}

/** Time-based attack/release follows AIRI's MIT-licensed vowel driver approach:
 * https://github.com/moeru-ai/airi/blob/main/packages/model-driver-lipsync/src/shared/wlipsync/vowel-driver.ts
 * Rates retain the previous 60 fps response; no vowel inference is performed. */
export function smoothMouth(current: number, target: number, seconds: number) {
  const rate = target > current ? 41.6 : 25.8
  const value = current + (target - current) * (1 - Math.exp(-rate * Math.max(0, seconds)))
  return value < .005 ? 0 : value
}
