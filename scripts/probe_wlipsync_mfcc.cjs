/* Isolated diagnostic of the pinned upstream WASM; never connects to audio UI.
 * Compares the original npm WASM with the source-rebuilt coefficient fix.
 * Checks all twelve exported MFCC slots with six classes, outside audio UI.
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict'), crypto = require('node:crypto')
const root = path.resolve(__dirname, '..')
;(async () => {
  const results = []
  for (const [name, file] of [['original-npm-1.3.1', 'web/node_modules/wlipsync/dist/wlipsync.wasm'], ['source-MFCC_NUM-fix', 'web/vendor/wlipsync/wlipsync.wasm']]) {
  const memory = new WebAssembly.Memory({ initial: 4 }), wasm = fs.readFileSync(path.join(root, file))
  const { instance } = await WebAssembly.instantiate(wasm, { env: { memory } })
  const api = instance.exports
  api.load_profile(16000, 1024, 30, 2, 6, 48, 0); api.set_input(16000)
  const samples = new Float32Array(memory.buffer, api.get_input_buffer(), api.get_input_buffer_size())
  for (let i = 0; i < 1024; i++) samples[i] = .1 * Math.sin(2 * Math.PI * 220 * i / 16000)
  const mfcc = new Float32Array(memory.buffer, api.mfccOut.value, 12)
  mfcc.fill(123456); api.execute(1024)
  results.push({ name, file, sha256: crypto.createHash('sha256').update(wasm).digest('hex'), classes: 6, mfcc_after_execute: Array.from(mfcc), unchanged_coefficients: Array.from(mfcc).filter(x => x === 123456).length })
  assert(mfcc.slice(0, 6).every(x => Number.isFinite(x) && x !== 123456))
  }
  assert.equal(results[0].unchanged_coefficients, 6, 'Original defect no longer reproduces; investigate pinned dependency')
  assert.equal(results[1].unchanged_coefficients, 0, 'Source repair still leaves incomplete coefficients')
  const result = { source: 'mrxz/wlipsync fixed source commit 177f3ac4095dbad81be0a800a8c6f975abe4ae04 plus MFCC_NUM loop bound repair', results, passed: true, limitation: 'Isolated exported-WASM diagnostic, not a phoneme accuracy benchmark; production buffers were not modified. The fix alone does not establish Chinese classification accuracy.' }
  const output = path.join(root, 'artifacts/wlipsync-mfcc-repair.json')
  fs.mkdirSync(path.dirname(output), { recursive: true }); fs.writeFileSync(output, JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
})().catch(error => { console.error(error); process.exitCode = 1 })
