import { describe, expect, it } from 'vitest'
import { mouthLevel, smoothMouth } from './mouth'

describe('output mouth signal', () => {
  it('follows output amplitude and closes for silence', () => {
    expect(mouthLevel(new Float32Array(1024))).toBe(0)
    expect(mouthLevel(new Float32Array(1024).fill(.05))).toBeCloseTo(.35)
    expect(mouthLevel(new Float32Array(1024).fill(.1))).toBeCloseTo(.7)
    expect(mouthLevel(new Float32Array(1024).fill(.5))).toBe(1)
  })
  it('has equivalent attack and release at 30 and 120 frames per second', () => {
    const run = (fps: number) => {
      let value = 0
      for (let i = 0; i < fps / 2; i++) value = smoothMouth(value, .8, 1 / fps)
      for (let i = 0; i < fps / 10; i++) value = smoothMouth(value, 0, 1 / fps)
      return value
    }
    expect(run(30)).toBeCloseTo(run(120), 8)
    expect(run(30)).toBeLessThan(.1)
  })
})
