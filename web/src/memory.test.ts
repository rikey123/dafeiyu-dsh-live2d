import { afterEach, expect, it, vi } from 'vitest'
import { localMemories } from './memory'
import { configureRuntime } from './runtime'
afterEach(() => { configureRuntime(); vi.unstubAllGlobals() })

it('masks the standalone memory store in DSH without issuing any request', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [{ id: 'local-secret', content: 'standalone only' }] })
  vi.stubGlobal('fetch', fetch)
  configureRuntime({ apiBase: '/dafeiyu' })
  expect(await localMemories(true)).toEqual([])
  expect(fetch).not.toHaveBeenCalled()
})

it('retains standalone memory for rollback', async () => {
  const entries = [{ id: 'one', content: 'local memory' }]
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => entries })
  vi.stubGlobal('fetch', fetch)
  expect(await localMemories(false)).toEqual(entries)
  expect(fetch).toHaveBeenCalledWith('/api/memories')
})
