import { describe, expect, it } from 'vitest'
import { defaultWardrobe, easeLayers, loadWardrobe, wardrobeParameters, wardrobeTargets } from './wardrobe'

describe('wardrobe layers', () => {
  it('maps outfit toggles to skin parameters', () => {
    const t = wardrobeTargets({ ...defaultWardrobe, glasses: 'mono', basin: true, tail: true, size: 2 }, 'idle')
    expect(t).toEqual({ key12: 1, key10: 1, Clothes5: -1, Clothes2: 1 })
  })
  it('reacts to activity only when enabled', () => {
    expect(wardrobeTargets(defaultWardrobe, 'thinking')).toMatchObject({ key8: 1, Movement3: 1 })
    expect(wardrobeTargets(defaultWardrobe, 'listening')).toEqual({ LeanInput: -12 })
    expect(wardrobeTargets({ ...defaultWardrobe, reactive: false }, 'thinking')).toEqual({})
  })
  it('keeps an explicit gesture while thinking', () => {
    const t = wardrobeTargets({ ...defaultWardrobe, gesture: 'grass' }, 'thinking')
    expect(t.Movement1).toBe(1); expect(t.Movement3).toBeUndefined()
  })
  it('declares every driven parameter', () => {
    const all = { ...defaultWardrobe, glasses: 'frame' as const, basin: true, teeth: true, tail: true, longSkirt: true, chestCloth: true, barefoot: true, size: 1 }
    for (const gesture of ['chest', 'grass', 'finger'] as const) for (const id of Object.keys(wardrobeTargets({ ...all, gesture }, 'thinking'))) expect(wardrobeParameters).toContain(id)
  })
  it('sanitizes stored values', () => {
    expect(loadWardrobe('{"glasses":"x","gesture":"y","size":"z"}')).toEqual(defaultWardrobe)
    expect(loadWardrobe('not json')).toEqual(defaultWardrobe)
  })
  it('eases toward targets and releases finished layers', () => {
    const layers = new Map<string, number>()
    easeLayers(layers, { key11: 1 }, 0.1); expect(layers.get('key11')).toBeGreaterThan(0); expect(layers.get('key11')).toBeLessThan(1)
    for (let i = 0; i < 60; i++) easeLayers(layers, { key11: 1 }, 0.1)
    expect(layers.get('key11')).toBe(1)
    for (let i = 0; i < 60; i++) easeLayers(layers, {}, 0.1)
    expect(layers.has('key11')).toBe(false)
  })
})
