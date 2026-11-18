import { expect, it } from 'vitest'
import { BehaviorQueue, parseBehavior, isBehaviorSource } from './behavior'
import { defaultWardrobe, wardrobeTargets } from './avatar/wardrobe'

it('holds early decisions until corresponding PCM and drops late/retired decisions', () => {
  const queue = new BehaviorQueue()
  expect(queue.receive('a', { emotion: 'sad', gesture: 'chest' })).toBeUndefined()
  expect(queue.consume('a')).toBeUndefined()
  queue.start('a')
  expect(queue.consume('a')?.behavior).toEqual({ emotion: 'sad', gesture: 'chest', source: 'clef-omni' })
  expect(queue.consume('a')).toBeUndefined()
  queue.finish('a')
  expect(queue.receive('a', { emotion: 'happy' })).toBeUndefined()
  queue.start('b'); queue.consume('b')
  expect(queue.receive('b', { energy: .2 })).toEqual({ energy: .2, source: 'clef-omni' })
  queue.clear()
  expect(queue.receive('b', { energy: 1 })).toBeUndefined()
  expect(queue.consume('b')).toBeUndefined()
})

it('only accepts allowlisted, finite model controls', () => {
  for (const raw of [{ emotion: 'angry' }, { gesture: 'arbitrary' }, { expression: '__proto__' }, { expression: null }, { energy: NaN }, { energy: 2 }, { param: 5 }]) expect(parseBehavior(raw)).toBeUndefined()
  expect(parseBehavior({ expression: 'natural', energy: 0 })).toEqual({ expression: 'natural', energy: 0 })
})

it('keeps the actual provider attached to PCM-aligned behavior and clears it on stop', () => {
  const queue = new BehaviorQueue()
  queue.receive('ark', { emotion: 'sad', gesture: 'chest' }, 'doubao-systemone')
  queue.start('ark')
  expect(queue.consume('ark')?.behavior).toEqual({ emotion: 'sad', gesture: 'chest', source: 'doubao-systemone' })
  queue.clear()
  expect(queue.receive('ark', { emotion: 'happy' }, 'doubao-systemone')).toBeUndefined()
  expect(isBehaviorSource('__proto__')).toBe(false)
  expect(isBehaviorSource('rules')).toBe(false)
})

it('manual poses and reactive opt out take priority over model gestures', () => {
  expect(wardrobeTargets(defaultWardrobe, 'speaking', 'chest').Movement2).toBe(1)
  expect(wardrobeTargets({ ...defaultWardrobe, gesture: 'finger' }, 'speaking', 'chest').Movement3).toBe(1)
  expect(wardrobeTargets({ ...defaultWardrobe, reactive: false }, 'speaking', 'chest').Movement2).toBeUndefined()
})
