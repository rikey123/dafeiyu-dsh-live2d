import { expect, it, vi } from 'vitest'
import { SessionIdentity } from './sessionIdentity'

it('coalesces creation across suspend/resume and reuses the same session', async () => {
  let resolve!: (id: string) => void
  const create = vi.fn(() => new Promise<string>(done => { resolve = done }))
  const identity = new SessionIdentity()
  const first = identity.ensure(create), resumed = identity.ensure(create)
  expect(first).toBe(resumed)
  await Promise.resolve()
  resolve('original')
  expect(await resumed).toBe('original')
  expect(await identity.ensure(create)).toBe('original')
  expect(create).toHaveBeenCalledOnce()
})

it.each(['', 'selected'])('does not revive a late creation after explicit session selection (%s)', async selected => {
  let resolve!: (id: string) => void
  const identity = new SessionIdentity()
  const old = identity.ensure(() => new Promise<string>(done => { resolve = done }))
  await Promise.resolve()
  identity.select(selected)
  const current = identity.ensure(async () => 'new')
  resolve('obsolete')
  expect(await old).toBeUndefined()
  expect(await current).toBe(selected || 'new')
  expect(identity.id).toBe(selected || 'new')
})

it('retries a failed creation instead of caching a rejected promise', async () => {
  const identity = new SessionIdentity()
  await expect(identity.ensure(async () => { throw Error('unavailable') })).rejects.toThrow('unavailable')
  expect(await identity.ensure(async () => 'recovered')).toBe('recovered')
})
