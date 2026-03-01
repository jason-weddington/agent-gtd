import { useEffect, useRef, useCallback } from 'react'

export interface ServerEvent {
  eventType: string
  entityType: string
  entityId: string
  projectId: string | null
  payload: Record<string, unknown>
  createdAt: string
}

type EventHandler = (event: ServerEvent) => void

/**
 * Opens an EventSource to /api/events and dispatches parsed events
 * to the provided handler. Tracks lastEventId for replay on reconnect.
 */
export function useEventStream(
  token: string | null,
  onEvent: EventHandler,
) {
  const lastEventIdRef = useRef<string | null>(null)
  const onEventRef = useRef(onEvent)

  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams()
    if (token) params.set('token', token)
    if (lastEventIdRef.current) params.set('since', lastEventIdRef.current)
    return `/api/events?${params.toString()}`
  }, [token])

  useEffect(() => {
    if (!token) return

    const url = buildUrl()
    const es = new EventSource(url)

    const handleMessage = (e: MessageEvent) => {
      if (e.lastEventId) {
        lastEventIdRef.current = e.lastEventId
      }
      try {
        const data = JSON.parse(e.data) as ServerEvent
        onEventRef.current(data)
      } catch {
        // Ignore malformed events
      }
    }

    // Listen for all named event types
    const eventTypes = [
      'item_created', 'item_updated', 'item_deleted',
      'project_created', 'project_updated', 'project_deleted',
      'note_created', 'note_updated', 'note_deleted',
    ]
    for (const type of eventTypes) {
      es.addEventListener(type, handleMessage)
    }

    return () => {
      es.close()
    }
  }, [token, buildUrl])
}
