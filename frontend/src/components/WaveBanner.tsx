/**
 * WaveBanner — persistent banner above the project board when a wave is active.
 *
 * Owns wave state fetch and SSE subscription. Renders WaveEventFeed and
 * WaveHaltCard as children when appropriate.
 *
 * AC-1 through AC-18.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Alert,
  Box,
  Chip,
  LinearProgress,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import { api, ApiError } from '../api'
import type { WaveEvent, WaveRun, WaveRunStatus } from '../types'
import { formatRelativeTime } from '../utils'
import { useEvents } from '../contexts/EventStreamContext'
import type { ServerEvent } from '../hooks/useEventStream'
import WaveEventFeed from './WaveEventFeed'
import WaveActivityTab from './WaveActivityTab'
import WaveHaltCard from './WaveHaltCard'

// ---------------------------------------------------------------------------
// Exported pure helpers (tested in WaveBanner.test.tsx)
// ---------------------------------------------------------------------------

/**
 * Return the MUI colour palette key for a given wave status (AC-4).
 */
export function getStatusColor(
  status: WaveRunStatus,
): 'default' | 'info' | 'warning' | 'error' | 'success' {
  switch (status) {
    case 'pending':
    case 'planning':
      return 'default'
    case 'running':
      return 'info'
    case 'halted':
      return 'warning'
    case 'crashed':
      return 'error'
    case 'completed':
      return 'success'
    default:
      return 'default'
  }
}

/**
 * Return the banner title text for a given wave status (AC-3).
 */
export function getTitleText(status: WaveRunStatus): string {
  switch (status) {
    case 'pending':
    case 'planning':
    case 'running':
      return 'Autonomous Dispatch Management in Progress'
    case 'halted':
      return 'Wave Halted — Review Needed'
    case 'crashed':
      return 'Wave Crashed'
    case 'completed':
      return 'Wave Completed'
    default:
      return 'Wave'
  }
}

/**
 * Return a 0–1 progress fraction for the wave (AC-5).
 */
export function getProgressFraction(doneCount: number, totalCount: number): number {
  if (totalCount <= 0) return 0
  return Math.min(1, doneCount / totalCount)
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
// MUI colour token helper
// ---------------------------------------------------------------------------

type MuiColor = 'default' | 'info' | 'warning' | 'error' | 'success'

function colorToSx(color: MuiColor): Record<string, unknown> {
  const map: Record<MuiColor, string> = {
    default: 'action.hover',
    info: 'info.main',
    warning: 'warning.main',
    error: 'error.main',
    success: 'success.main',
  }
  return { bgcolor: map[color], color: color === 'default' ? 'text.primary' : 'common.white' }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface WaveBannerProps {
  projectId: string
  /** Callback fired whenever the wave active status changes, so the parent can
   *  disable Dispatch tab controls (AC-19, AC-20). */
  onActiveChange?: (hasActiveWave: boolean) => void
}

/** Statuses that block Dispatch tab editing. */
const BLOCKING_STATUSES: ReadonlySet<WaveRunStatus> = new Set([
  'pending',
  'planning',
  'running',
  'halted',
])

/** Re-fetch on these status values (show banner). */
const VISIBLE_STATUSES: ReadonlySet<WaveRunStatus> = new Set([
  'pending',
  'planning',
  'running',
  'halted',
  'crashed',
  'completed',
])

export default function WaveBanner({ projectId, onActiveChange }: WaveBannerProps) {
  const [wave, setWave] = useState<WaveRun | null>(null)
  const [events, setEvents] = useState<WaveEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)
  const [bannerError, setBannerError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState(0)

  const { onEvent } = useEvents()
  const waveRef = useRef<WaveRun | null>(null)
  waveRef.current = wave

  // ---------------------------------------------------------------------------
  // Load active wave for this project
  // ---------------------------------------------------------------------------

  const loadWave = useCallback(async () => {
    try {
      const w = await api.waves.getActiveForProject(projectId)
      setWave(w)
      setBannerError(null)
      return w
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // No active wave — clear banner
        setWave(null)
        return null
      }
      setBannerError(err instanceof ApiError ? err.detail : 'Failed to load wave status')
      return null
    }
  }, [projectId])

  // ---------------------------------------------------------------------------
  // Load historical events (AC-10)
  // ---------------------------------------------------------------------------

  const loadEvents = useCallback(async (waveRunId: string) => {
    setEventsLoading(true)
    try {
      const res = await api.waves.events(waveRunId, 50)
      setEvents(res.events)
    } catch {
      setEvents([])
    } finally {
      setEventsLoading(false)
    }
  }, [])

  // ---------------------------------------------------------------------------
  // Initial load
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false
    loadWave().then((w) => {
      if (!cancelled && w) {
        loadEvents(w.id).catch(() => {/* non-critical */})
      }
    }).catch(() => {/* handled in loadWave */})
    return () => { cancelled = true }
  }, [loadWave, loadEvents])

  // ---------------------------------------------------------------------------
  // Notify parent of active status changes (AC-19, AC-20)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const isActive = wave !== null && BLOCKING_STATUSES.has(wave.status)
    onActiveChange?.(isActive)
  }, [wave, onActiveChange])

  // ---------------------------------------------------------------------------
  // SSE subscription (AC-2, AC-11)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const unsub = onEvent('wave_event', (sseEvent: ServerEvent) => {
      // Only react to events for this project
      if (sseEvent.projectId !== projectId) return

      // AC-11: prepend the full wave_event object to the feed
      const rawPayload = sseEvent.payload as Record<string, unknown>
      const waveEventData: WaveEvent = {
        id: String(rawPayload.id ?? ''),
        waveRunId: String(rawPayload.wave_run_id ?? ''),
        seq: Number(rawPayload.seq ?? 0),
        ts: String(rawPayload.ts ?? ''),
        kind: String(rawPayload.kind ?? ''),
        actor: (rawPayload.actor as WaveEvent['actor']) ?? 'manager',
        decisionRule: String(rawPayload.decision_rule ?? ''),
        payload: (rawPayload.payload as Record<string, unknown>) ?? {},
      }
      setEvents((prev) => [waveEventData, ...prev])

      // AC-2: re-fetch wave state so banner + progress update
      loadWave().catch(() => {/* handled */})
    })
    return unsub
  }, [onEvent, projectId, loadWave])

  // ---------------------------------------------------------------------------
  // Halt card helpers
  // ---------------------------------------------------------------------------

  const latestHaltEvent =
    events.find((e) => e.kind === 'wave_halted') ?? null

  const handleResume = useCallback(() => {
    loadWave().catch(() => {/* handled */})
  }, [loadWave])

  const handleSkip = useCallback(() => {
    loadWave().catch(() => {/* handled */})
  }, [loadWave])

  const handleAbort = useCallback(() => {
    loadWave().catch(() => {/* handled */})
  }, [loadWave])

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

  if (!wave || !VISIBLE_STATUSES.has(wave.status)) {
    return null
  }

  const statusColor = getStatusColor(wave.status)
  const titleText = getTitleText(wave.status)
  const showProgress = ['running', 'halted', 'completed'].includes(wave.status)
  const progressFraction = getProgressFraction(wave.doneCount, wave.totalCount)

  return (
    <Box sx={{ mb: 2 }}>
      {/* Banner (AC-1, AC-3, AC-4, AC-5) */}
      <Box
        sx={{
          ...colorToSx(statusColor),
          borderRadius: 1,
          p: 1.5,
          mb: 1,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: showProgress ? 1 : 0 }}>
          <Chip
            label={wave.status.toUpperCase()}
            size="small"
            color={statusColor === 'default' ? undefined : statusColor}
            sx={{ fontWeight: 700, fontSize: '0.65rem' }}
          />
          <Typography variant="subtitle2" sx={{ flex: 1, fontWeight: 600 }}>
            {titleText}
          </Typography>
          {showProgress && (
            <Typography variant="caption" sx={{ whiteSpace: 'nowrap' }}>
              {wave.doneCount} / {wave.totalCount} items done
            </Typography>
          )}
        </Box>
        {showProgress && (
          <LinearProgress
            variant="determinate"
            value={progressFraction * 100}
            color={statusColor === 'default' ? undefined : statusColor}
            sx={{ borderRadius: 1, height: 6 }}
          />
        )}
        {/* Manager state line (AC-8, AC-9) */}
        {wave.status === 'running' && wave.managerPhase !== null && (
          <Typography
            variant="caption"
            sx={{
              display: 'block',
              mt: 0.75,
              color: isStateStale(wave.managerStateUpdatedAt)
                ? 'text.disabled'
                : 'inherit',
              opacity: isStateStale(wave.managerStateUpdatedAt) ? 0.8 : 1,
            }}
          >
            {'Manager: '}
            {wave.managerPhase}
            {' · working on '}
            {wave.managerCurrentItemTitle ?? wave.managerCurrentItemId ?? '—'}
            {' · last updated '}
            {wave.managerStateUpdatedAt
              ? formatRelativeTime(wave.managerStateUpdatedAt)
              : '—'}
            {isStateStale(wave.managerStateUpdatedAt) ? ' ⚠ stale' : ''}
          </Typography>
        )}
      </Box>

      {/* Halt card (AC-12 through AC-18) */}
      {wave.status === 'halted' && (
        <WaveHaltCard
          waveRun={wave}
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

      {/* Events tab (AC-6 through AC-11) */}
      {activeTab === 0 && (
        <WaveEventFeed events={events} loading={eventsLoading} projectId={projectId} />
      )}

      {/* Activity tab */}
      {activeTab === 1 && wave && (
        <WaveActivityTab waveRunId={wave.id} />
      )}
    </Box>
  )
}
