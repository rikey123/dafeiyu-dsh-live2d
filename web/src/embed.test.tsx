import { afterEach, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ render: vi.fn(), unmount: vi.fn(), flush: vi.fn((f: () => void) => f()), observe: vi.fn(), disconnect: vi.fn() }))
vi.mock('react-dom/client', () => ({ createRoot: () => ({ render: state.render, unmount: state.unmount }) }))
vi.mock('react-dom', () => ({ flushSync: state.flush }))
vi.mock('./App', () => ({ App: () => null }))
vi.mock('./style.css?inline', () => ({ default: ':root {color:red}' }))
import { mountDafeiyu } from './embed'

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })
function fixture(hidden = false) {
  const listeners = new Map<string, () => void>()
  const doc = { hidden, fullscreenElement: null, addEventListener: (name: string, fn: () => void) => listeners.set(name, fn), removeEventListener: (name: string) => listeners.delete(name), createElement: () => ({ appendChild: vi.fn(), style: {}, textContent: '', className: '', id: '' }) }
  vi.stubGlobal('document', doc)
  vi.stubGlobal('ResizeObserver', class { observe = state.observe; disconnect = state.disconnect })
  const shadow = { append: vi.fn(), replaceChildren: vi.fn() }
  const fakeHost = { shadowRoot: null as typeof shadow | null, attachShadow() { fakeHost.shadowRoot = shadow; return shadow }, getAttribute: () => null, removeAttribute: vi.fn(), style: { removeProperty: vi.fn() } }
  const host = fakeHost as unknown as HTMLElement
  return {host, doc, listeners}
}
it('retains the same App type on inactive/hidden, unmounting only on disposal', () => {
  const {host, doc, listeners} = fixture()
  const instance = mountDafeiyu(host, { harnessProvider: 'dsh' })
  const type = state.render.mock.calls[0][0].type
  expect(state.render).toHaveBeenCalledOnce()
  expect(() => mountDafeiyu(host)).toThrow('already mounted')
  instance.setActive(false); expect(state.render.mock.lastCall?.[0].props.active).toBe(false)
  doc.hidden = true; instance.setActive(true); expect(state.render).toHaveBeenCalledTimes(2)
  doc.hidden = false; listeners.get('visibilitychange')?.(); expect(state.render).toHaveBeenCalledTimes(3)
  doc.hidden = true; listeners.get('visibilitychange')?.(); expect(state.render.mock.lastCall?.[0].props.active).toBe(false)
  expect(state.render.mock.calls.every(([element]) => element?.type === type && element.props.embedHost === host)).toBe(true)
  expect(state.unmount).not.toHaveBeenCalled()
  instance.dispose(); expect(state.unmount).toHaveBeenCalledOnce(); expect(state.disconnect).toHaveBeenCalledOnce()
  doc.hidden = false
  const again = mountDafeiyu(host); again.dispose()
  expect(listeners.size).toBe(0)
})

it('does not initialize while first mounted inactive/hidden and ignores activity after disposal', () => {
  const {host, doc, listeners} = fixture(true)
  const instance = mountDafeiyu(host, {active:false})
  instance.setActive(true)
  expect(state.render).not.toHaveBeenCalled()
  doc.hidden = false; listeners.get('visibilitychange')?.()
  expect(state.render).toHaveBeenCalledOnce()
  expect(state.render.mock.lastCall?.[0].props.active).toBe(true)
  listeners.get('visibilitychange')?.()
  expect(state.render).toHaveBeenCalledOnce()
  instance.dispose(); instance.dispose(); instance.setActive(false)
  expect(state.unmount).toHaveBeenCalledOnce()
  expect(state.render).toHaveBeenCalledOnce()
})

it('passes the same native bridge through visibility updates', () => {
  const {host} = fixture()
  const bridge = { mount: vi.fn(() => () => {}) }
  const instance = mountDafeiyu(host, { nativeConversation: bridge })
  expect(state.render.mock.lastCall?.[0].props.nativeConversation).toBe(bridge)
  instance.setActive(false)
  expect(state.render.mock.lastCall?.[0].props.nativeConversation).toBe(bridge)
  instance.dispose()
})
