/**
 * WaveActivityTab — unified per-wave activity timeline.
 *
 * Calls GET /api/wave-runs/{id}/activity on mount and renders a vertical list
 * of enriched events with role-coloured actor pills, one-line descriptions,
 * and expandable raw-payload rows.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Button,
  Chip,
  Collapse,
  CircularProgress,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'
import { api } from '../api'
import type { ActivityEvent } from '../types'

// ---------------------------------------------------------------------------
// Actor pill colour helper
// ---------------------------------------------------------------------------

type PillColor = 'primary' | 'secondary' | 'warning' | 'success' | 'default'

function actorColor(actor: string): PillColor {
  if (actor === 'manager' || actor.startsWith('claude-manage-')) return 'primary'
  if (actor === 'child-agent' || actor.startsWith('claude-build-')) return 'secondary'
  if (actor === 'reaper' || actor.startsWith('system-')) return 'warning'
  if (actor === 'human') return 'success'
  return 'default'
}

// ---------------------------------------------------------------------------
// Event description mapping
// ---------------------------------------------------------------------------

function describeEvent(event: ActivityEvent): string {
  const { eventType, payload, itemTitle, itemId } = event
  const label = itemTitle ?? itemId ?? ''
  switch (eventType) {
    case 'wave_planned':
      return `Wave planned: ${String(payload.item_count ?? '')} items, model ${String(payload.planner_model ?? '')}`
    case 'wave_started':
      return 'Wave started (manage agent dispatched)'
    case 'item_dispatched':
      return `Dispatched: ${label}`
    case 'item_outcome': {
      const outcome = String(payload.outcome ?? '')
      return `${label}: ${outcome}`
    }
    case 'wave_halted':
      return `Wave halted: ${String(payload.reason ?? '')}`
    case 'wave_cancelled':
      return 'Wave cancelled'
    case 'wave_resumed': {
      const newlyReady = Array.isArray(payload.newly_ready) ? payload.newly_ready : []
      return `Wave resumed (${newlyReady.length} items re-readied)`
    }
    case 'wave_replanned': {
      const oldV = payload.old_version
      const newV = payload.new_version
      return `Replanned: v${String(oldV ?? '')} → v${String(newV ?? '')}`
    }
    case 'wave_crashed':
      return 'Wave crashed (reaped)'
    case 'comment_posted':
      return `Comment posted (${String(payload.comment_type ?? '')})`
    default:
      return eventType
  }
}

// ---------------------------------------------------------------------------
// Timestamp formatter (local HH:MM:SS)
// ---------------------------------------------------------------------------

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return ts
  }
}

// ---------------------------------------------------------------------------
// Single event row
// ---------------------------------------------------------------------------

interface EventRowProps {
  event: ActivityEvent
}

function EventRow({ event }: EventRowProps) {
  const [expanded, setExpanded] = useState(false)
  const color = actorColor(event.actor)
  const description = describeEvent(event)

  return (
    <ListItem
      disablePadding
      onClick={() => setExpanded((v) => !v)}
      sx={{ cursor: 'pointer', flexDirection: 'column', alignItems: 'flex-start', py: 0.5 }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
        <Typography
          variant="caption"
          fontFamily="monospace"
          sx={{ color: 'text.secondary', minWidth: 70, flexShrink: 0 }}
        >
          {formatTimestamp(event.ts)}
        </Typography>
        <Chip
          label={event.actor}
          size="small"
          color={color === 'default' ? undefined : color}
          sx={{ fontSize: '0.65rem', height: 20, flexShrink: 0 }}
        />
        <ListItemText
          primary={description}
          primaryTypographyProps={{ variant: 'caption' }}
          sx={{ m: 0 }}
        />
      </Box>
      <Collapse in={expanded} sx={{ width: '100%', pl: 1 }}>
        <Box
          component="pre"
          sx={{
            mt: 0.5,
            p: 1,
            bgcolor: 'action.hover',
            borderRadius: 1,
            fontSize: '0.7rem',
            overflow: 'auto',
            maxHeight: 200,
          }}
        >
          {JSON.stringify(event.payload, null, 2)}
        </Box>
      </Collapse>
    </ListItem>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface WaveActivityTabProps {
  waveRunId: string
}

export default function WaveActivityTab({ waveRunId }: WaveActivityTabProps) {
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadActivity = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.waves.activity(waveRunId, 200)
      setEvents(res.events)
      setHasMore(res.hasMore)
    } catch {
      setError('Failed to load activity')
      setEvents([])
    } finally {
      setLoading(false)
    }
  }, [waveRunId])

  useEffect(() => {
    loadActivity().catch(() => {/* handled */})
  }, [loadActivity])

  const loadMore = useCallback(async () => {
    if (events.length === 0) return
    const minSeq = events[events.length - 1].seq
    setLoadingMore(true)
    try {
      const res = await api.waves.activity(waveRunId, 200, minSeq)
      setEvents((prev) => [...prev, ...res.events])
      setHasMore(res.hasMore)
    } catch {
      // Non-critical — user can retry
    } finally {
      setLoadingMore(false)
    }
  }, [waveRunId, events])

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
        <CircularProgress size={24} />
      </Box>
    )
  }

  if (error) {
    return (
      <Typography variant="body2" color="error" sx={{ py: 2 }}>
        {error}
      </Typography>
    )
  }

  if (events.length === 0) {
    return (
      <Box sx={{ py: 2, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No activity recorded for this wave
        </Typography>
      </Box>
    )
  }

  return (
    <Box>
      <List dense disablePadding>
        {events.map((event) => (
          <EventRow key={event.id} event={event} />
        ))}
      </List>
      {hasMore && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 1 }}>
          <Button
            size="small"
            variant="outlined"
            onClick={() => loadMore().catch(() => {/* handled */})}
            disabled={loadingMore}
          >
            {loadingMore ? 'Loading…' : 'Load more'}
          </Button>
        </Box>
      )}
    </Box>
  )
}
