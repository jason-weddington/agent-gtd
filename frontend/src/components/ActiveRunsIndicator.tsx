import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Badge,
  Box,
  Chip,
  IconButton,
  LinearProgress,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
} from '@mui/material'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import { api } from '../api'
import { useEvents } from '../contexts/EventStreamContext'
import { useItemDrawer } from '../contexts/ItemDrawerContext'
import type { Run, Item, Project, Rollout } from '../types'

const POLL_INTERVAL_MS = 15000

function getRunTitle(run: Run, item: Item | undefined, rollout: Rollout | undefined): string {
  if (run.mode === 'manage') {
    if (rollout?.managerCurrentStep) return rollout.managerCurrentStep
    const shortId = run.rolloutId?.slice(0, 8) ?? '?'
    return `Rollout manager (${shortId})`
  }
  return item?.title ?? run.featureBranch
}

function formatElapsed(startedAt: string | null, now: number): string {
  if (!startedAt) return '–'
  const elapsedSec = Math.floor(
    (now - new Date(startedAt).getTime()) / 1000,
  )
  if (elapsedSec < 60) return `${elapsedSec}s`
  if (elapsedSec < 3600) return `${Math.floor(elapsedSec / 60)}m`
  return `${Math.floor(elapsedSec / 3600)}h ${Math.floor((elapsedSec % 3600) / 60)}m`
}

/**
 * Header indicator that shows how many agent runs are currently active or queued.
 * Clicking the icon opens a menu listing each run with its item title,
 * project name, and elapsed time. Each entry opens the item in the side drawer.
 *
 * Running runs are shown with a pulsing robot icon; queued (pending) runs are
 * shown with an hourglass and a "Queued" chip explaining the concurrency cap.
 *
 * Polls api.runs.list({ status: 'pending,running' }) every 15 seconds and reacts
 * to SSE run_started / run_completed / run_failed events in real time.
 */
export default function ActiveRunsIndicator() {
  const [runs, setRuns] = useState<Run[]>([])
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [now, setNow] = useState(() => Date.now())
  const [itemMap, setItemMap] = useState<Record<string, Item>>({})
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({})
  const [rolloutMap, setRolloutMap] = useState<Record<string, Rollout>>({})
  // Refs track which IDs we've already fetched so enrichment calls are idempotent
  const fetchedItemIds = useRef<Set<string>>(new Set())
  const fetchedProjectIds = useRef<Set<string>>(new Set())
  const fetchedRolloutIds = useRef<Set<string>>(new Set())
  const { onEvent } = useEvents()
  const { openItemDrawer } = useItemDrawer()

  // Using void .then() (not async/await) so the eslint react-hooks/set-state-in-effect
  // rule doesn't consider this a direct setState call chain from within the effect.
  const loadRuns = useCallback(() => {
    void api.runs
      .list({ status: 'pending,running', scope: 'accessible_projects' })
      .then((activeRuns) => {
        setRuns(activeRuns)

        // Lazily enrich each run with item title and project name.
        // Fire-and-forget; refs prevent duplicate requests across polls.
        for (const run of activeRuns) {
          if (run.itemId && !fetchedItemIds.current.has(run.itemId)) {
            fetchedItemIds.current.add(run.itemId)
            void api.items
              .get(run.itemId)
              .then((item) =>
                setItemMap((prev) => ({ ...prev, [run.itemId!]: item })),
              )
          }
          if (!fetchedProjectIds.current.has(run.projectId)) {
            fetchedProjectIds.current.add(run.projectId)
            void api.projects
              .get(run.projectId)
              .then((project) =>
                setProjectMap((prev) => ({
                  ...prev,
                  [run.projectId]: project,
                })),
              )
          }
          if (run.mode === 'manage' && run.rolloutId && !fetchedRolloutIds.current.has(run.rolloutId)) {
            fetchedRolloutIds.current.add(run.rolloutId)
            void api.rollouts
              .get(run.rolloutId)
              .then((rollout) =>
                setRolloutMap((prev) => ({ ...prev, [run.rolloutId!]: rollout })),
              )
          }
        }
      })
  }, [])

  // Initial load on mount
  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  // Periodic poll every 15 seconds
  useEffect(() => {
    const interval = setInterval(loadRuns, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [loadRuns])

  // Tick every second so elapsed times update in real time
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(interval)
  }, [])

  // React to SSE events so the count updates in real time
  useEffect(() => {
    const unsubs = [
      onEvent('run_started', () => loadRuns()),
      onEvent('run_completed', () => loadRuns()),
      onEvent('run_failed', () => loadRuns()),
    ]
    return () => unsubs.forEach((u) => u())
  }, [onEvent, loadRuns])

  const runningRuns = runs.filter((r) => r.status !== 'pending')
  const pendingRuns = runs.filter((r) => r.status === 'pending')
  const runningCount = runningRuns.length
  const pendingCount = pendingRuns.length
  const totalCount = runningCount + pendingCount

  function buildTooltip(): string {
    if (totalCount === 0) return 'No active runs'
    const parts: string[] = []
    if (runningCount > 0)
      parts.push(`${runningCount} running`)
    if (pendingCount > 0)
      parts.push(`${pendingCount} queued`)
    return parts.join(', ')
  }

  return (
    <>
      <Tooltip title={buildTooltip()}>
        <IconButton
          color="inherit"
          onClick={(e) => setAnchorEl(e.currentTarget)}
          aria-label="Active agent runs"
        >
          <Badge badgeContent={totalCount} color="primary" invisible={totalCount === 0}>
            <SmartToyOutlinedIcon
              sx={runningCount > 0 ? {
                animation: 'pulse-green 2s ease-in-out infinite',
                '@keyframes pulse-green': {
                  '0%, 100%': { color: 'inherit' },
                  '50%': { color: 'success.main' },
                },
              } : undefined}
            />
          </Badge>
        </IconButton>
      </Tooltip>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => setAnchorEl(null)}
        transformOrigin={{ horizontal: 'right', vertical: 'top' }}
        anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
        slotProps={{
          paper: {
            sx: { mt: 1, minWidth: 300, maxWidth: 420 },
          },
        }}
      >
        {runningCount > 0 && (
          <LinearProgress color="success" sx={{ height: 2 }} />
        )}
        {totalCount === 0 ? (
          <MenuItem disabled>
            <Typography variant="body2" color="text.secondary">
              No active runs
            </Typography>
          </MenuItem>
        ) : (() => {
          // Build display groups: each manage run followed by its children,
          // then standalone (non-rollout) runs at the end.
          const manageRuns = runs.filter((r) => r.mode === 'manage')
          const standaloneRuns = runs.filter((r) => r.mode !== 'manage' && !r.rolloutId)
          const childRunsByRollout: Record<string, Run[]> = {}
          for (const run of runs) {
            if (run.mode !== 'manage' && run.rolloutId) {
              childRunsByRollout[run.rolloutId] ??= []
              childRunsByRollout[run.rolloutId].push(run)
            }
          }
          const displayGroups: Array<{ run: Run; isChild: boolean }> = []
          for (const mgr of manageRuns) {
            displayGroups.push({ run: mgr, isChild: false })
            for (const child of (mgr.rolloutId ? (childRunsByRollout[mgr.rolloutId] ?? []) : [])) {
              displayGroups.push({ run: child, isChild: true })
            }
          }
          for (const run of standaloneRuns) {
            displayGroups.push({ run, isChild: false })
          }

          return displayGroups.map(({ run, isChild }) => {
            const item = run.itemId ? itemMap[run.itemId] : undefined
            const project = projectMap[run.projectId]
            const rollout = run.rolloutId ? rolloutMap[run.rolloutId] : undefined
            const isQueued = run.status === 'pending'
            return (
              <MenuItem
                key={run.id}
                onClick={() => {
                  if (!item) return  // item not yet loaded — graceful no-op
                  setAnchorEl(null)
                  openItemDrawer(item, project)
                }}
              >
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 1,
                    py: 0.5,
                    width: '100%',
                    overflow: 'hidden',
                    ...(isChild ? { pl: 2 } : {}),
                  }}
                >
                  <Tooltip
                    title={
                      isQueued
                        ? 'Queued — waiting for a free slot (capped at 6 concurrent runs)'
                        : 'Running'
                    }
                    placement="left"
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', mt: 0.25 }}>
                      {isQueued ? (
                        <HourglassEmptyIcon
                          fontSize="small"
                          sx={{ color: 'text.disabled', fontSize: 16 }}
                        />
                      ) : (
                        <SmartToyOutlinedIcon
                          fontSize="small"
                          sx={{
                            fontSize: 16,
                            animation: 'pulse-green-row 2s ease-in-out infinite',
                            '@keyframes pulse-green-row': {
                              '0%, 100%': { color: 'text.secondary' },
                              '50%': { color: 'success.main' },
                            },
                          }}
                        />
                      )}
                    </Box>
                  </Tooltip>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                      <Chip
                        label={run.mode === 'manage' ? 'Manage' : run.mode === 'plan' ? 'Plan' : 'Build'}
                        size="small"
                        variant="outlined"
                        color={run.mode === 'manage' ? 'warning' : 'default'}
                        sx={{ flexShrink: 0 }}
                      />
                      <Typography variant="body2" fontWeight={500} noWrap sx={{ flex: 1 }}>
                        {getRunTitle(run, item, rollout)}
                      </Typography>
                      {isQueued && (
                        <Chip
                          label="Queued"
                          size="small"
                          sx={{
                            height: 18,
                            fontSize: '0.65rem',
                            bgcolor: 'action.selected',
                            flexShrink: 0,
                          }}
                        />
                      )}
                      {/* TODO(AC4): show engine chip per run once RunResponse includes an `engine` field.
                          As of 2026-05-16 the backend RunResponse model (models.py RunResponse) does not
                          expose the engine used for a run. When that field is added, update the Run
                          interface in types.ts and render a chip here using the same ENGINE_LABEL
                          mapping as KanbanCard.tsx / GtdItemList.tsx. */}
                    </Box>
                    <Typography variant="caption" color="text.secondary" noWrap>
                      {project?.name ?? run.projectId}
                      {!isQueued && ` · ${formatElapsed(run.startedAt, now)}`}
                    </Typography>
                  </Box>
                </Box>
              </MenuItem>
            )
          })
        })()}
      </Menu>
    </>
  )
}
