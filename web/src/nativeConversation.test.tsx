import { expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ node: {} as HTMLDivElement, effect: undefined as undefined | (() => void | (() => void)) }))
vi.mock('react', async importOriginal => {
  const react = await importOriginal<typeof import('react')>()
  return { ...react, useRef: () => ({ current: state.node }), useLayoutEffect: (effect: typeof state.effect) => { state.effect = effect } }
})
import { NativeConversationSlot, type NativeConversationBridge } from './nativeConversation'

it('mounts both slots for the same session and cleans each on replacement or disposal', () => {
  const cleanups = [vi.fn(), vi.fn(), vi.fn()]
  const mount = vi.fn().mockReturnValueOnce(cleanups[0]).mockReturnValueOnce(cleanups[1]).mockReturnValueOnce(cleanups[2])
  const bridge: NativeConversationBridge = { mount }
  NativeConversationSlot({ bridge, sessionId: '', target: 'messages' })
  expect(state.effect?.()).toBeUndefined()
  expect(mount).not.toHaveBeenCalled()
  NativeConversationSlot({ bridge, sessionId: 'first', target: 'messages' })
  const messagesCleanup = state.effect?.()
  NativeConversationSlot({ bridge, sessionId: 'first', target: 'composer' })
  const composerCleanup = state.effect?.()
  expect(mount.mock.calls.map(call => call.slice(1))).toEqual([['first', 'messages'], ['first', 'composer']])
  messagesCleanup?.(); composerCleanup?.()
  NativeConversationSlot({ bridge, sessionId: 'second', target: 'composer' })
  const replacementCleanup = state.effect?.()
  expect(mount).toHaveBeenLastCalledWith(state.node, 'second', 'composer')
  replacementCleanup?.()
  expect(cleanups.every(cleanup => cleanup.mock.calls.length === 1)).toBe(true)
})
