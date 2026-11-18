import { useLayoutEffect, useRef } from 'react'

/** The host owns the native renderer and returns a synchronous cleanup for each slot. */
export interface NativeConversationBridge {
  mount(container: HTMLElement, sessionId: string, target: 'messages' | 'composer'): () => void
}

export function NativeConversationSlot({ bridge, sessionId, target }: { bridge: NativeConversationBridge; sessionId: string; target: 'messages' | 'composer' }) {
  const container = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!sessionId || !container.current) return
    return bridge.mount(container.current, sessionId, target)
  }, [bridge, sessionId, target])
  return <div ref={container} className={`native-conversation native-conversation-${target}`} data-native-conversation={target}/>
}
