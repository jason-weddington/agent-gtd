/**
 * RolloutBanner — persistent banner above the project board when a rollout is active.
 *
 * Owns rollout state fetch and SSE subscription. Renders RolloutEventFeed and
 * RolloutHaltCard as children when appropriate.
 *
 * AC-1 through AC-18.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Alert,
  Box,
  Tab,
  Tabs,
} from '@mui/material'
import { api, ApiError } from '../api'
import type { Rollout, RolloutEvent, RolloutStatus } from '../types'
import { useEvents } from '../contexts/EventStreamContext'
import type { ServerEvent } from '../hooks/useEventStream'
import RolloutEventFeed from './RolloutEventFeed'
import RolloutActivityTab from './RolloutActivityTab'
import RolloutHaltCard from './RolloutHaltCard'
import RolloutStrip from './RolloutStrip'

// ---------------------------------------------------------------------------
// Exported pure helpers (tested in RolloutBanner.test.tsx)
// ---------------------------------------------------------------------------

/**
 * Return the MUI colour palette key for a given rollout status (AC-4).
 */
export function getStatusColor(
  status: RolloutStatus,
): 'default' | 'info' | 'warning' | 'error' | 'success' {
  switch (status) {
    case 'pending':
    case 'planning':
      return 'default'
    case 'running':
      return 'info'
    case 'halted':
      return 'warning'
    case 'failed':
      return 'error'
    case 'completed':
      return 'success'
    default:
      return 'default'
  }
}

/**
 * Return the banner title text for a given rollout status (AC-3).
 */
export function getTitleText(status: RolloutStatus): string {
  switch (status) {
    case 'pending':
    case 'planning':
    case 'running':
      return 'Autonomous Dispatch Management in Progress'
    case 'halted':
      return 'Wave Halted — Review Needed'
    case 'failed':
      return 'Wave Failed'
    case 'completed':
      return 'Wave Completed'
    default:
      return 'Wave'
  }
}

/**
 * Return a 0–1 progress fraction for the rollout (AC-5).
 */
export function getProgressFraction(doneCount: number, totalCount: number): number {
  if (totalCount <= 0) return 0
  return Math.min(1, doneCount / totalCount)
}

/**
 * Return true if the incoming SSE wave_event should be prepended to the
 * events feed for the current rollout.
 *
 * Guards against cross-rollout contamination: when a new rollout starts, SSE
 * fires for the new rollout_id before loadRollout() has updated state.  Only
 * events whose rollout_id matches the currently active rollout are shown (AC-2).
 */
export function shouldPrepondRolloutEvent(
  eventRolloutId: string,
  currentRolloutId: string | null | undefined,
): boolean {
  return Boolean(currentRolloutId) && eventRolloutId === currentRolloutId
}

/**
 * Return true if the manager state is stale (updatedAt is more than
 * thresholdMs milliseconds ago, or null).
 *
 * Used to render the state line in a muted colour with a ⚠ stale suffix.
 */
export function isStateStale(
  updatedAt: string | null,
  thresholdMs: number = 5 * 60 * 1000,
): boolean {
  if (updatedAt === null) return true
  return Date.now() - new Date(updatedAt).getTime() > thresholdMs
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface RolloutBannerProps {
  projectId: string
  /** Callback fired whenever the rollout active status changes, so the parent can
   *  disable Dispatch tab controls (AC-19, AC-20). */
  onActiveChange?: (hasActiveWave: boolean) => void
}

/** Statuses that block Dispatch tab editing. */
const BLOCKING_STATUSES: ReadonlySet<RolloutStatus> = new Set([
  'pending',
  'planning',
  'running',
  'halted',
])

/** Show the strip for these statuses (AC-1, AC-2). */
const STRIP_STATUSES: ReadonlySet<RolloutStatus> = new Set([
  'pending',
  'planning',
  'running',
  'halted',
  'failed',
])

export default function RolloutBanner({ projectId, onActiveChange }: RolloutBannerProps) {
  const [rollout, setRollout] = useState<Rollout | null>(null)
  const [events, setEvents] = useState<RolloutEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)
  const [bannerError, setBannerError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState(0)
  /** Whether the Events/Activity section is visible (AC-13: default collapsed). */
  const [showDetails, setShowDetails] = useState(false)
  // Incremented on each SSE event for the current rollout; passed to
  // RolloutActivityTab so it re-fetches without needing its own SSE sub (AC-4).
  const [activityRefreshKey, setActivityRefreshKey] = useState(0)

  const { onEvent } = useEvents()
  const rolloutRef = useRef<Rollout | null>(null)
  rolloutRef.current = rollout

  // ---------------------------------------------------------------------------
  // Load active rollout for this project
  // ---------------------------------------------------------------------------

  const loadRollout = useCallback(async () => {
    try {
      const w = await api.rollouts.getActiveForProject(projectId)
      setRollout(w)
      setBannerError(null)
      return w
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // No active rollout — clear banner
        setRollout(null)
        return null
      }
      setBannerError(err instanceof ApiError ? err.detail : 'Failed to load rollout status')
      return null
    }
  }, [projectId])

  // ---------------------------------------------------------------------------
  // Load historical events (AC-10)
  // ---------------------------------------------------------------------------

  const loadEvents = useCallback(async (rolloutId: string) => {
    setEventsLoading(true)
    try {
      const res = await api.rollouts.events(rolloutId, 50)
      setEvents(res.events)
    } catch {
      setEvents([])
    } finally {
      setEventsLoading(false)
    }
  }, [])

  // ---------------------------------------------------------------------------
  // Initial load — fetch the active rollout (events are handled by the
  // rollout-id effect below, not here, to avoid double-fetching on id change).
  // ---------------------------------------------------------------------------

  useEffect(() => {
    loadRollout().catch(() => {/* handled in loadRollout */})
  }, [loadRollout])

  // ---------------------------------------------------------------------------
  // Reload events whenever the active rollout changes (AC-3).
  // Clears stale events from the previous rollout and fetches the new ones.
  // ---------------------------------------------------------------------------

  const currentRolloutId = rollout?.id ?? null
  useEffect(() => {
    setEvents([])
    if (!currentRolloutId) return
    loadEvents(currentRolloutId).catch(() => {/* non-critical */})
  }, [currentRolloutId, loadEvents])

  // ---------------------------------------------------------------------------
  // Notify parent of active status changes (AC-19, AC-20)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const isActive = rollout !== null && BLOCKING_STATUSES.has(rollout.status)
    onActiveChange?.(isActive)
  }, [rollout, onActiveChange])

  // ---------------------------------------------------------------------------
  // SSE subscription (AC-2, AC-11)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const unsub = onEvent('wave_event', (sseEvent: ServerEvent) => {
      // Only react to events for this project
      if (sseEvent.projectId !== projectId) return

      // AC-11: prepend the full wave_event object to the feed
      const rawPayload = sseEvent.payload as Record<string, unknown>
      const waveEventData: RolloutEvent = {
        id: String(rawPayload.id ?? ''),
        rolloutId: String(rawPayload.rollout_id ?? ''),
        seq: Number(rawPayload.seq ?? 0),
        ts: String(rawPayload.ts ?? ''),
        kind: String(rawPayload.kind ?? ''),
        actor: (rawPayload.actor as RolloutEvent['actor']) ?? 'manager',
        decisionRule: String(rawPayload.decision_rule ?? ''),
        payload: (rawPayload.payload as Record<string, unknown>) ?? {},
      }

      // AC-2: only prepend events that belong to the currently active rollout.
      // Events for a different rollout_id (e.g. a newly started rollout whose
      // ID hasn't landed in state yet) must not pollute the current feed.
      if (shouldPrepondRolloutEvent(waveEventData.rolloutId, rolloutRef.current?.id)) {
        setEvents((prev) => [waveEventData, ...prev])
        // Signal RolloutActivityTab to re-fetch (AC-4)
        setActivityRefreshKey((k) => k + 1)
      }

      // Always re-fetch rollout state so banner + progress update, and so
      // cross-rollout transitions (new rollout started) are picked up.
      loadRollout().catch(() => {/* handled */})
    })
    return unsub
  }, [onEvent, projectId, loadRollout])

  // ---------------------------------------------------------------------------
  // Halt card helpers
  // ---------------------------------------------------------------------------

  const latestHaltEvent =
    events.find((e) => e.kind === 'wave_halted') ?? null

  const handleResume = useCallback(() => {
    loadRollout().catch(() => {/* handled */})
  }, [loadRollout])

  const handleSkip = useCallback(() => {
    loadRollout().catch(() => {/* handled */})
  }, [loadRollout])

  const handleAbort = useCallback(() => {
    loadRollout().catch(() => {/* handled */})
  }, [loadRollout])

  const handleHalt = useCallback(() => {
    loadRollout().catch(() => {/* handled */})
  }, [loadRollout])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (bannerError) {
    return (
      <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setBannerError(null)}>
        {bannerError}
      </Alert>
    )
  }

  if (!rollout || !STRIP_STATUSES.has(rollout.status)) {
    return null
  }

  return (
    <Box sx={{ mb: 2 }}>
      {/* Compact 2-row strip (AC-1, AC-4 through AC-14) */}
      <RolloutStrip
        rollout={rollout}
        onHalt={handleHalt}
        onToggleDetails={() => setShowDetails((v) => !v)}
        showDetails={showDetails}
      />

      {/* Details section — collapsed by default (AC-13) */}
      {showDetails && (
        <>
          {/* Halt card (shown when halted) */}
          {rollout.status === 'halted' && (
            <RolloutHaltCard
              waveRun={rollout}
              latestHaltEvent={latestHaltEvent}
              onResume={handleResume}
              onSkip={handleSkip}
              onAbort={handleAbort}
            />
          )}

          {/* Events / Activity tabs */}
          <Box sx={{ borderBottom: 1, borderColor: 'divider', mt: 1 }}>
            <Tabs
              value={activeTab}
              onChange={(_e, v: number) => setActiveTab(v)}
              textColor="inherit"
              indicatorColor="primary"
              sx={{ minHeight: 32 }}
            >
              <Tab label="Events" sx={{ minHeight: 32, py: 0.5, fontSize: '0.75rem' }} />
              <Tab label="Activity" sx={{ minHeight: 32, py: 0.5, fontSize: '0.75rem' }} />
            </Tabs>
          </Box>

          {/* Events tab */}
          {activeTab === 0 && (
            <RolloutEventFeed events={events} loading={eventsLoading} projectId={projectId} />
          )}

          {/* Activity tab */}
          {activeTab === 1 && (
            <RolloutActivityTab rolloutId={rollout.id} refreshKey={activityRefreshKey} />
          )}
        </>
      )}
    </Box>
  )
}
