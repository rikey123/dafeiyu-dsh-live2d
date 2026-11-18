/* Offline profile calibration using the pinned source-patched wLipSync WASM.
 * No replacement DSP/classifier. Inputs must be labelled mono PCM16 16k WAVs.
 * Usage: node scripts/calibrate_lipsync.cjs manifest.json output-profile.json
 * Manifest: [{name:'A', path:'absolute.wav'}, ...] (six AEIOUS entries).
 * The mfccOut symbol is an export of wlipsync 1.3.1; pin/check it explicitly.
 * This trains a voice-specific acoustic template, not phoneme timing/alignment.
 */
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto')
const root = path.resolve(__dirname, '..')
function wav(file) {
  const b = fs.readFileSync(file); let offset = 12, format, pcm
  if (b.toString('ascii', 0, 4) !== 'RIFF' || b.toString('ascii', 8, 12) !== 'WAVE') throw Error('Expected WAV')
  while (offset + 8 <= b.length) {
    const size = b.readUInt32LE(offset + 4), tag = b.toString('ascii', offset, offset + 4)
    if (tag === 'fmt ') format = [b.readUInt16LE(offset + 8), b.readUInt16LE(offset + 10), b.readUInt32LE(offset + 12), b.readUInt16LE(offset + 22)]
    if (tag === 'data') pcm = b.subarray(offset + 8, offset + 8 + size)
    offset += 8 + size + size % 2
  }
  if (String(format) !== '1,1,16000,16' || !pcm || pcm.length % 2) throw Error('Requires mono PCM16 16k WAV')
  return Float32Array.from({ length: pcm.length / 2 }, (_, i) => pcm.readInt16LE(i * 2) / 32768)
}
;(async () => {
  const [manifestPath, output] = process.argv.slice(2)
  if (!manifestPath || !output) throw Error('Usage: node scripts/calibrate_lipsync.cjs manifest.json output-profile.json')
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  if (manifest.length !== 6 || new Set(manifest.map(x => x.name)).size !== 6 || manifest.some(x => !/^[AEIOUS]$/.test(x.name))) throw Error('Exactly six AEIOUS labelled recordings required')
  const wasmPath = path.resolve(process.env.WLIPSYNC_WASM || path.join(root, 'web/vendor/wlipsync/wlipsync.wasm'))
  const wasm = fs.readFileSync(wasmPath)
  const memory = new WebAssembly.Memory({ initial: 4 })
  const { instance } = await WebAssembly.instantiate(wasm, { env: { memory } }), api = instance.exports
  if (!(api.mfccOut instanceof WebAssembly.Global)) throw Error('Pinned wLipSync MFCC export unavailable')
  const profile = { mfccNum: 12, mfccDataCount: 48, melFilterBankChannels: 30, targetSampleRate: 16000, sampleCount: 1024, useStandardization: false, compareMethod: 2, mfccs: [] }
  api.load_profile(16000, 1024, 30, 2, 6, 48, 0)
  new Float32Array(memory.buffer, api.profileStdDev.value, 12).fill(1)
  api.set_input(16000)
  const input = new Float32Array(memory.buffer, api.get_input_buffer(), api.get_input_buffer_size())
  const coefficients = new Float32Array(memory.buffer, api.mfccOut.value, 12)
  coefficients.fill(123456); api.execute(0)
  if (coefficients.some(x => !Number.isFinite(x) || x === 123456)) throw Error('Refusing incomplete MFCC extraction; use the fixed vendored WASM')
  const metadata = []
  for (const item of manifest) {
    input.fill(0); const samples = wav(item.path), frames = []; let cursor = 0
    for (let i = 0; i < samples.length; i += 128) {
      for (const sample of samples.subarray(i, i + 128)) { input[cursor] = sample; cursor = (cursor + 1) % input.length }
      if (i >= 1024 && (i + 128) % 512 === 0) {
        api.execute(cursor)
        const volume = new Float32Array(memory.buffer, api.get_volume_ptr(), 1)[0]
        if (volume > .025) frames.push(Array.from(new Float32Array(memory.buffer, api.mfccOut.value, 12)))
      }
    }
    if (frames.length < 16 || frames.some(f => f.some(x => !Number.isFinite(x)))) throw Error('Insufficient valid calibration frames: ' + item.name)
    const selected = Array.from({ length: 48 }, (_, i) => frames[Math.floor((i + .5) * frames.length / 48)])
    profile.mfccs.push({ name: item.name, mfccCalibrationDataList: selected.map(array => ({ array })) })
    metadata.push({ name: item.name, frames: frames.length, sha256: crypto.createHash('sha256').update(fs.readFileSync(item.path)).digest('hex') })
  }
  fs.writeFileSync(output, JSON.stringify(profile, null, 2) + '\n')
  fs.writeFileSync(output + '.meta.json', JSON.stringify({ engine: 'wlipsync@1.3.1 fixed MFCC_NUM source build', wasmPath: path.relative(root, wasmPath), wasmSha256: crypto.createHash('sha256').update(wasm).digest('hex'), inputs: metadata, limitation: 'Labelled synthetic isolated-vowel calibration; requires held-out/browser evaluation. Not forced alignment, consonant classification, or universal voice accuracy.' }, null, 2) + '\n')
  console.log('Calibrated six acoustic templates using upstream WASM:', output)
})().catch(error => { console.error(error); process.exitCode = 1 })
