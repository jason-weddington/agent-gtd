import { createContext, useContext, useRef, useCallback, useMemo, type ReactNode } from 'react'
import { useAuth } from './AuthContext'
import { useEventStream, type ServerEvent } from '../hooks/useEventStream'

type EventCallback = (event: ServerEvent) => void

interface EventStreamContextValue {
  /** Subscribe to a specific event type. Returns an unsubscribe function. */
  onEvent: (eventType: string, callback: EventCallback) => () => void
}

const EventStreamContext = createContext<EventStreamContextValue | undefined>(undefined)

export function EventStreamProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const listenersRef = useRef<Map<string, Set<EventCallback>>>(new Map())

  const handleEvent = useCallback((event: ServerEvent) => {
    const callbacks = listenersRef.current.get(event.eventType)
    if (callbacks) {
      for (const cb of callbacks) {
        cb(event)
      }
    }
  }, [])

  const token = isAuthenticated ? localStorage.getItem('agent_gtd-token') : null
  useEventStream(token, handleEvent)

  const onEvent = useCallback((eventType: string, callback: EventCallback) => {
    if (!listenersRef.current.has(eventType)) {
      listenersRef.current.set(eventType, new Set())
    }
    listenersRef.current.get(eventType)!.add(callback)
    return () => {
      const set = listenersRef.current.get(eventType)
      if (set) {
        set.delete(callback)
        if (set.size === 0) {
          listenersRef.current.delete(eventType)
        }
      }
    }
  }, [])

  const value = useMemo(() => ({ onEvent }), [onEvent])

  return (
    <EventStreamContext.Provider value={value}>
      {children}
    </EventStreamContext.Provider>
  )
}

export function useEvents() {
  const ctx = useContext(EventStreamContext)
  if (!ctx) throw new Error('useEvents must be used within EventStreamProvider')
  return ctx
}
