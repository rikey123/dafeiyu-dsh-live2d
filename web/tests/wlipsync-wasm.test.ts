import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

async function untouched(path: string) {
  const memory = new WebAssembly.Memory({ initial: 4 })
  const { instance } = await WebAssembly.instantiate(readFileSync(path), { env: { memory } })
  const api = instance.exports as Record<string, any>
  api.load_profile(16000, 1024, 30, 2, 6, 48, 0); api.set_input(16000)
  const samples = new Float32Array(memory.buffer, api.get_input_buffer(), api.get_input_buffer_size())
  for (let i = 0; i < 1024; i++) samples[i] = .1 * Math.sin(2 * Math.PI * 220 * i / 16000)
  const coefficients = new Float32Array(memory.buffer, api.mfccOut.value, 12)
  coefficients.fill(123456); api.execute(1024)
  return Array.from(coefficients).filter(value => value === 123456).length
}
it('updates all twelve MFCCs with six phoneme classes', async () => {
  expect(await untouched('node_modules/wlipsync/dist/wlipsync.wasm')).toBe(6)
  expect(await untouched('vendor/wlipsync/wlipsync.wasm')).toBe(0)
})
