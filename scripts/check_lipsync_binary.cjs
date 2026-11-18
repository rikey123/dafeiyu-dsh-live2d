/* Verify official JSON precomputation and binary-profile loading are equivalent.
 * Uses original exported parser and the fixed WASM; no replacement classifier.
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict'), { pathToFileURL } = require('node:url')
const root = path.resolve(__dirname, '..')
;(async () => {
  global.AudioWorkletNode = class {} // Parser import only, no audio device.
  const { parseBinaryProfile } = await import(pathToFileURL(path.join(root, 'web/node_modules/wlipsync/dist/wlipsync.js')).href)
  const raw = JSON.parse(fs.readFileSync(path.join(root, 'web/src/avatar/lipsync/local-vits-profile.json'), 'utf8'))
  const bin = fs.readFileSync(path.join(root, 'web/src/avatar/lipsync/local-vits-profile.bin'))
  const compact = parseBinaryProfile(bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.byteLength))
  const wav = fs.readFileSync(path.join(root, 'artifacts/vowel-acceptance/equal-rms-vowels.wav'))
  assert.equal(wav.toString('ascii', 36, 40), 'data')
  const audio = Float32Array.from({ length: (wav.length - 44) / 2 }, (_, i) => wav.readInt16LE(44 + i * 2) / 32768)
  const outputs = []
  for (const profile of [raw, compact]) {
    const memory = new WebAssembly.Memory({ initial: 4 })
    const { instance } = await WebAssembly.instantiate(fs.readFileSync(path.join(root, 'web/vendor/wlipsync/wlipsync.wasm')), { env: { memory } })
    const api = instance.exports, pointer = api.load_profile(profile.targetSampleRate, profile.sampleCount, profile.melFilterBankChannels, profile.compareMethod, profile.mfccs.length, profile.mfccDataCount, profile.useStandardization ? 1 : 0)
    if (!profile.means) {
      new Float32Array(memory.buffer, pointer, profile.mfccs.length * profile.mfccDataCount * 12).set(profile.mfccs.flatMap(x => x.mfccCalibrationDataList.flatMap(f => f.array)))
      api.precompute_profile()
    } else {
      const ptrs = new Int32Array(memory.buffer, api.get_profile_ptrs(), 3)
      new Float32Array(memory.buffer, ptrs[0], profile.mfccs.length * 12).set(profile.mfccs.flatMap(x => x.values))
      new Float32Array(memory.buffer, ptrs[1], 12).set(profile.means)
      new Float32Array(memory.buffer, ptrs[2], 12).set(profile.stdDevs)
    }
    api.set_input(16000)
    const input = new Float32Array(memory.buffer, api.get_input_buffer(), api.get_input_buffer_size()), frames = []
    let cursor = 0
    for (let i = 0; i < audio.length; i += 128) {
      for (const sample of audio.subarray(i, i + 128)) { input[cursor] = sample; cursor = (cursor + 1) % input.length }
      if ((i + 128) % 512 === 0) frames.push(profile.mfccs[api.execute(cursor)].name)
    }
    outputs.push(frames)
  }
  assert.deepEqual(outputs[0], outputs[1], 'Binary template changed classification compared with raw calibration JSON')
  const result = { passed: true, frames: outputs[0].length, json_bytes: Buffer.byteLength(JSON.stringify(raw)), binary_bytes: bin.length, classification_identical: true, limitation: 'Identical behavior proves initialization/size optimization, not accurate phonemes. Fixed independent synthetic audio sequence, no microphone or physical timing.' }
  fs.mkdirSync(path.join(root, 'artifacts/lip-calibration-fixed'), { recursive: true })
  fs.writeFileSync(path.join(root, 'artifacts/lip-calibration-fixed/binary-equivalence.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
})().catch(e => { console.error(e); process.exitCode = 1 })
