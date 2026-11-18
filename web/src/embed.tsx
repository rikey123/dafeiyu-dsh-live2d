import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { App } from './App'
import type { NativeConversationBridge } from './nativeConversation'
export type { NativeConversationBridge } from './nativeConversation'
import { configureRuntime } from './runtime'
import { shadowCss } from './embedCss'
import css from './style.css?inline'

export type DafeiyuOptions = { apiBase?: string; assetBase?: string; active?: boolean; harnessProvider?: 'dsh'; nativeConversation?: NativeConversationBridge }
let mounted = false
const ownedHosts = new WeakSet<HTMLElement>()
/** One instance per bundle. The caller controls the host dimensions. */
export function mountDafeiyu(host: HTMLElement, options: DafeiyuOptions = {}) {
  if (mounted) throw new Error('Dafeiyu is already mounted')
  if (host.shadowRoot && !ownedHosts.has(host)) throw new Error('Dafeiyu host already has a shadow root')
  const shadow = host.shadowRoot || host.attachShadow({ mode: 'open' })
  ownedHosts.add(host)
  const style = document.createElement('style'); style.textContent = shadowCss(css)
  const container = document.createElement('div'); container.className = 'embed-container'
  const node = document.createElement('div'); node.id = 'root'; container.appendChild(node)
  shadow.append(style, container)
  const oldTheme = host.getAttribute('data-theme')
  const root = createRoot(node)
  configureRuntime({ apiBase: options.apiBase ?? '/dafeiyu', assetBase: options.assetBase ?? '/dafeiyu' })
  mounted = true
  let disposed = false, active = options.active !== false, rendered = false, lastActive = false
  const render = () => {
    const shouldRender = active && !document.hidden
    if (disposed || (!rendered && !shouldRender) || (rendered && shouldRender === lastActive)) return
    rendered = true; lastActive = shouldRender
    if (!shouldRender && document.fullscreenElement === host) void document.exitFullscreen().catch(() => {})
    // Activity is not ownership: keep UI state and the expensive Live2D root.
    // App pauses visual loops only. Authorized interaction runs until an
    // explicit stop or actual disposal, independently of slot/tab visibility.
    flushSync(() => root.render(<App embedHost={host} active={shouldRender} nativeConversation={options.nativeConversation}/>))
  }
  const visibilityChanged = () => render()
  document.addEventListener('visibilitychange', visibilityChanged)
  const observer = new ResizeObserver(entries => { host.style.setProperty('--dafeiyu-host-width', `${entries[0].contentRect.width}px`) })
  observer.observe(host)
  render()
  return {
    setActive(value: boolean) { if (disposed || active === value) return; active = value; render() },
    dispose() {
      if (disposed) return
      disposed = true; document.removeEventListener('visibilitychange', visibilityChanged); observer.disconnect()
      host.style.removeProperty('--dafeiyu-host-width')
      if (document.fullscreenElement === host) void document.exitFullscreen().catch(() => {})
      flushSync(() => root.unmount()); shadow.replaceChildren()
      if (oldTheme === null) host.removeAttribute('data-theme'); else host.setAttribute('data-theme', oldTheme)
      mounted = false
    },
  }
}
