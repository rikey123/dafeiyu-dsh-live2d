/** URL configuration is local to this frontend bundle; standalone keeps root paths. */
let apiBase = ''
let assetBase = ''
export function configureRuntime(options: { apiBase?: string; assetBase?: string } = {}) {
  apiBase = (options.apiBase ?? '').replace(/\/$/, '')
  assetBase = (options.assetBase ?? '').replace(/\/$/, '')
}
export function apiUrl(path: string) { return `${apiBase}${path.startsWith('/') ? path : `/${path}`}` }
export function assetUrl(path: string) {
  if (!path.startsWith('/') || path.startsWith('//') || !assetBase || path === assetBase || path.startsWith(`${assetBase}/`)) return path
  return `${assetBase}${path}`
}
/** Only the frontend's public model namespace moves with the plugin. Explicit
 * URLs and other same-origin model services continue to belong to their caller. */
export function modelAssetUrl(path: string) { return path.startsWith('/models/') ? assetUrl(path) : path }
export function isManagedModel(path: string) {
  return !!assetBase && (path.startsWith('/models/') || path.startsWith(`${assetBase}/models/`))
}
export function voiceUrl(session: string) {
  const url = new URL(apiUrl('/ws/voice'), `${location.protocol}//${location.host}/`)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('session_id', session)
  return url.toString()
}

let voiceCleanup: Promise<void> = Promise.resolve()
export function trackVoiceCleanup(cleanup: Promise<void>) {
  voiceCleanup = Promise.allSettled([voiceCleanup, cleanup]).then(() => {})
}
export function waitForVoiceCleanup() { return voiceCleanup }
