import { beforeEach, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ nodes: [] as any[], parse: vi.fn() }))
vi.mock('wlipsync/wlipsync.js', () => ({
  WLipSyncAudioNode: class {
    blockSize = 512; smoothness = .05
    constructor(...args: any[]) { state.nodes.push({ node: this, args }) }
  },
  parseBinaryProfile: state.parse,
}))

beforeEach(() => {
  vi.resetModules(); state.nodes.length = 0
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) }))
  vi.spyOn(WebAssembly, 'compile').mockResolvedValue({ compiled: true } as unknown as WebAssembly.Module)
})
function context() {
  return { state: 'running', audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) } } as unknown as AudioContext
}

it('shares WASM across reconnects but gives each context its own worklet/node', async () => {
  const { createRealtimeLipNode } = await import('./runtime')
  const a = context(), b = context()
  const nodes = await Promise.all([createRealtimeLipNode(a, 'airi'), createRealtimeLipNode(a, 'airi'), createRealtimeLipNode(b, 'airi')])
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(WebAssembly.compile).toHaveBeenCalledTimes(1)
  expect(a.audioWorklet.addModule).toHaveBeenCalledTimes(1)
  expect(b.audioWorklet.addModule).toHaveBeenCalledTimes(1)
  expect(new Set(nodes).size).toBe(3)
  expect(nodes[0].blockSize).toBe(256)
  expect(nodes[0].smoothness).toBe(.025)
  expect(state.nodes[0].args[2]).toEqual({ compiled: true })
})

it('does not cache a failed WASM fetch forever', async () => {
  const { createRealtimeLipNode } = await import('./runtime')
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 503 } as Response)
  await expect(createRealtimeLipNode(context(), 'airi')).rejects.toThrow('503')
  await expect(createRealtimeLipNode(context(), 'airi')).resolves.toBeDefined()
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('does not construct a node after its context was closed during loading', async () => {
  const { createRealtimeLipNode } = await import('./runtime')
  const closed = { ...context(), state: 'closed' } as AudioContext
  await expect(createRealtimeLipNode(closed, 'airi')).rejects.toThrow('已关闭')
  expect(state.nodes).toHaveLength(0)
})

it('retries worklet registration after a transient failure', async () => {
  const { createRealtimeLipNode } = await import('./runtime')
  const ctx = context()
  vi.mocked(ctx.audioWorklet.addModule).mockRejectedValueOnce(new Error('worklet failed'))
  await expect(createRealtimeLipNode(ctx, 'airi')).rejects.toThrow('worklet failed')
  await expect(createRealtimeLipNode(ctx, 'airi')).resolves.toBeDefined()
  expect(ctx.audioWorklet.addModule).toHaveBeenCalledTimes(2)
})
