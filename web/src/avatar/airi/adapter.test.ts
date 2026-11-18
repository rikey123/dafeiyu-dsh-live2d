import { describe, expect, it } from 'vitest'
import { createMagicController } from './adapter'

describe('AIRI MAGIC adapter', () => {
  it('fits the real profiles, respects the motion ownership boundary, transitions and disposes', () => {
    const writes: [string, number][] = []
    const started = performance.now()
    const controller = createMagicController({ setParameterValueById: (id, value) => writes.push([id, value]) })
    console.log(`Cold MAGIC fit: ${(performance.now() - started).toFixed(1)} ms`)
    for (let i = 0; i < 200; i++) controller.update(1 / 60, i > 60 && i < 140)
    expect(writes.length).toBeGreaterThan(0)
    expect(new Set(writes.map(([id]) => id))).toEqual(new Set(['ParamAngleX', 'ParamAngleY', 'ParamAngleZ', 'ParamBodyAngleX', 'ParamBodyAngleY', 'ParamBodyAngleZ']))
    expect(writes.every(([id, value]) => Number.isFinite(value) && Math.abs(value) <= (id.includes('Body') ? 6 : 18))).toBe(true)
    expect(writes.some(([, value]) => Math.abs(value) > .001)).toBe(true)
    controller.dispose()
    const count = writes.length
    controller.update(1, true)
    expect(writes).toHaveLength(count)
  })
  it('scales generated body motion and offset continuously, and reaches neutral at zero strength', () => {
    const full: Record<string, number> = {}, half: Record<string, number> = {}
    const a = createMagicController({ setParameterValueById: (id, value) => { full[id] = value } }, { seed: 4 })
    const b = createMagicController({ setParameterValueById: (id, value) => { half[id] = value } }, { seed: 4 })
    let fullOffset = { x: 0, y: 0 }, halfOffset = { x: 0, y: 0 }
    for (let i = 0; i < 300; i++) { fullOffset = a.update(1 / 60, false, 1); halfOffset = b.update(1 / 60, false, .5) }
    expect(Math.abs(full.ParamBodyAngleX)).toBeGreaterThan(.01)
    expect(half.ParamBodyAngleX).toBeCloseTo(full.ParamBodyAngleX * .5)
    expect(halfOffset.x).toBeCloseTo(fullOffset.x * .5)
    expect(halfOffset.y).toBeCloseTo(fullOffset.y * .5)
    const neutral = a.update(1 / 60, false, 0)
    expect(Math.abs(neutral.x) + Math.abs(neutral.y)).toBe(0)
    expect(Object.values(full).every(value => value === 0)).toBe(true)
  })
  it('drives DeepSeek physics inputs instead of overwritten output parameters', () => {
    const ids = new Set<string>(), values: Record<string, number> = {}
    const controller = createMagicController({ setParameterValueById: (id, value) => { ids.add(id); values[id] = value } }, { profile: 'deepseek' })
    for (let i = 0; i < 300; i++) controller.update(1 / 60, false)
    expect(ids).toEqual(new Set(['AngleX', 'AngleY', 'AngleZ', 'PositionX', 'PositionY', 'PositionZ']))
    expect(values.PositionZ).toBeCloseTo(values.AngleZ)
    expect(Math.abs(values.PositionZ)).toBeGreaterThan(.001)
    controller.update(1 / 60, false, 0)
    expect(Object.values(values).every(value => value === 0)).toBe(true)
  })
})
