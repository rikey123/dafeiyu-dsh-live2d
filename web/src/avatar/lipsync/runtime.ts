import type { Profile } from 'wlipsync'
import fixedWasmUrl from '../../../vendor/wlipsync/wlipsync.wasm?url'
import lipWorkletUrl from 'wlipsync/audio-processor.js?url&no-inline'
import localProfileUrl from './local-vits-profile.bin?url&no-inline'
import genericProfile from './profile.json'

export type LipProfile = 'airi' | 'local-vits'
let runtime: Promise<{ module: typeof import('wlipsync/wlipsync.js'); wasm: WebAssembly.Module }> | undefined
let legacyProfile: Promise<Profile> | undefined
const worklets = new WeakMap<BaseAudioContext, Promise<void>>()

/** Share immutable resources across reconnects, not live AudioNodes/contexts.
 * Rejected loads are evicted so a transient failure can be retried. */
function loadRuntime() {
  return runtime ??= Promise.all([
    import('wlipsync/wlipsync.js'),
    fetch(fixedWasmUrl).then(async response => {
      if (!response.ok) throw new Error(`口型 WASM HTTP ${response.status}`)
      return WebAssembly.compile(await response.arrayBuffer())
    }),
  ]).then(([module, wasm]) => ({ module, wasm })).catch(error => { runtime = undefined; throw error })
}

function loadProfile(name: LipProfile): Promise<Profile> {
  if (name === 'airi') return Promise.resolve(genericProfile as Profile)
  return legacyProfile ??= fetch(localProfileUrl).then(async response => {
    if (!response.ok) throw new Error(`口型模板 HTTP ${response.status}`)
    return (await loadRuntime()).module.parseBinaryProfile(await response.arrayBuffer())
  }).catch(error => { legacyProfile = undefined; throw error })
}

export async function createRealtimeLipNode(context: AudioContext, profile: LipProfile) {
  let worklet = worklets.get(context)
  if (!worklet) {
    worklet = context.audioWorklet.addModule(lipWorkletUrl).catch(error => { worklets.delete(context); throw error })
    worklets.set(context, worklet)
  }
  const [{ module, wasm }, acousticProfile] = await Promise.all([loadRuntime(), loadProfile(profile), worklet])
  if (context.state === 'closed') throw new Error('口型音频上下文已关闭')
  const node = new module.WLipSyncAudioNode(context, acousticProfile, wasm)
  node.blockSize = 256
  node.smoothness = .025
  return node
}
