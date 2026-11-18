import { expect, it, vi } from 'vitest'
import { applyMouth, mouthTargets } from './adapter'
import { createWLipSyncVowelDriver } from './vowel-driver'

it('maps equal-volume distinct classifier frames to distinct mouth shapes and resets', () => {
  const driver = createWLipSyncVowelDriver(() => 1000)
  const a = mouthTargets(driver.update({ volume: 1, weights: { A: 1 } }, .2), .4)
  driver.reset()
  const o = mouthTargets(driver.update({ volume: 1, weights: { O: 1 } }, .2), .4)
  expect(a.MouthPuckerWiden).toBeGreaterThan(o.MouthPuckerWiden)
  expect(o.MouthFunnel).toBeGreaterThan(a.MouthFunnel)
  driver.reset()
  expect(Object.values(driver.update({ volume: 0, weights: {} }, .2))).toEqual([0, 0, 0, 0, 0])
})
it('clamps to actual moc bounds and skips virtual IDs', () => {
  const setParameterValueById = vi.fn()
  const core = { _model: { parameters: { ids: ['ParamMouthOpenY'] } }, getParameterIndex: () => 0, getParameterMinimumValue: () => 0, getParameterMaximumValue: () => .5, getParameterDefaultValue: () => 0, setParameterValueById }
  applyMouth(core, { ParamMouthOpenY: 1, MouthFunnel: .4 })
  expect(setParameterValueById.mock.calls).toEqual([['ParamMouthOpenY', .5]])
})
it('uses only generic mouth controls for other models', () => {
  const targets = mouthTargets({ A: 0, E: 0, I: 0, O: .5, U: 0 }, .5, 'default')
  expect(targets.ParamMouthForm).toBe(-.25)
  expect(targets).not.toHaveProperty('MouthFunnel')
})
