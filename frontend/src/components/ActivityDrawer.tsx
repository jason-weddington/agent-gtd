/**
 * ActivityDrawer — right-side collapsible drawer for unified activity feed.
 *
 * Shows rollout events/activity (when a rollout is active) and/or project run history.
 * Scope is selectable via a ToggleButtonGroup. Does not push page content.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Chip,
  CircularProgress,
  Drawer,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { api } from '../api'
import type { Run, RunStatus, RolloutEvent } from '../types'
import RolloutEventFeed from './RolloutEventFeed'
import RolloutActivityTab from './RolloutActivityTab'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ActivityDrawerProps {
  open: boolean
  onClose: () => void
  projectId: string
  activeRolloutId: string | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Scope = 'rollout' | 'project' | 'all'

const RUN_STATUS_COLORS: Record<
  RunStatus,
  'default' | 'info' | 'primary' | 'success' | 'error' | 'warning'
> = {
  pending: 'default',
  cloning: 'info',
  running: 'primary',
  success: 'success',
  failed: 'error',
  timeout: 'warning',
  cancelled: 'default',
}

function formatDuration(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt) return '—'
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now()
  const seconds = Math.floor((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

// ---------------------------------------------------------------------------
// Inner: Rollout event section (fetches + renders RolloutEventFeed)
// ---------------------------------------------------------------------------

function RolloutEventSection({ rolloutId }: { rolloutId: string }) {
  const [events, setEvents] = useState<RolloutEvent[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.rollouts.events(rolloutId, 100)
      setEvents(res.events)
    } catch {
      setEvents([])
    } finally {
      setLoading(false)
    }
  }, [rolloutId])

  useEffect(() => {
    void load()
  }, [load])

  return <RolloutEventFeed events={events} loading={loading} />
}

// ---------------------------------------------------------------------------
// Inner: Runs table (fetches + renders run history)
// ---------------------------------------------------------------------------

interface RunsTableProps {
  projectId?: string
  all?: boolean
}

function RunsTable({ projectId, all }: RunsTableProps) {
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)

  const loadRuns = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.runs.list(all ? {} : { projectId })
      setRuns(data)
    } catch {
      setRuns([])
    } finally {
      setLoading(false)
    }
  }, [projectId, all])

  useEffect(() => {
    void loadRuns()
  }, [loadRuns])

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
        <CircularProgress size={24} />
      </Box>
    )
  }

  if (runs.length === 0) {
    return (
      <Box sx={{ py: 4, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No agent runs yet.
        </Typography>
      </Box>
    )
  }

  return (
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Item</TableCell>
            <TableCell>Status</TableCell>
            <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>Branch</TableCell>
            <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>Started</TableCell>
            <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>Finished</TableCell>
            <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>Duration</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {runs.map((run) => {
            const itemLabel = run.itemId
              ? `Item ${run.itemId.slice(0, 8)}`
              : 'Manage run'
            const isFailed = run.status === 'failed' || run.status === 'timeout'
            return (
              <TableRow
                key={run.id}
                sx={{
                  bgcolor: isFailed
                    ? (theme) =>
                        theme.palette.mode === 'dark'
                          ? 'rgba(211,47,47,0.15)'
                          : 'rgba(211,47,47,0.07)'
                    : undefined,
                }}
              >
                <TableCell>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Chip
                      label={run.mode === 'plan' ? 'Plan' : 'Build'}
                      size="small"
                      variant="outlined"
                    />
                    <Typography variant="body2">{itemLabel}</Typography>
                  </Box>
                  {run.errorMsg && (
                    <Tooltip title={run.errorMsg} placement="bottom-start">
                      <Typography
                        variant="caption"
                        color="error"
                        sx={{
                          display: 'block',
                          maxWidth: 260,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {run.errorMsg}
                      </Typography>
                    </Tooltip>
                  )}
                </TableCell>
                <TableCell>
                  <Chip
                    label={run.status}
                    size="small"
                    color={RUN_STATUS_COLORS[run.status]}
                  />
                </TableCell>
                <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>
                  <Typography
                    variant="caption"
                    sx={{ fontFamily: 'monospace', fontSize: '0.72rem' }}
                  >
                    {run.featureBranch || '—'}
                  </Typography>
                </TableCell>
                <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>
                  <Typography variant="caption">
                    {run.startedAt
                      ? new Date(run.startedAt).toLocaleString()
                      : '—'}
                  </Typography>
                </TableCell>
                <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>
                  <Typography variant="caption">
                    {run.finishedAt
                      ? new Date(run.finishedAt).toLocaleString()
                      : '—'}
                  </Typography>
                </TableCell>
                <TableCell sx={{ display: { xs: 'none', md: 'table-cell' } }}>
                  <Typography variant="caption">
                    {formatDuration(run.startedAt, run.finishedAt)}
                  </Typography>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ActivityDrawer({
  open,
  onClose,
  projectId,
  activeRolloutId,
}: ActivityDrawerProps) {
  const [scope, setScope] = useState<Scope>(activeRolloutId ? 'rollout' : 'project')
  // Derived: if activeRolloutId goes away, fall back from 'rollout' to 'project'
  const effectiveScope: Scope = scope === 'rollout' && !activeRolloutId ? 'project' : scope

  const handleScopeChange = (_: React.SyntheticEvent, value: Scope | null) => {
    if (value) setScope(value)
  }

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      sx={{
        '& .MuiDrawer-paper': {
          width: { xs: '100vw', md: 500 },
          boxSizing: 'border-box',
        },
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Header */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            p: 2,
            borderBottom: 1,
            borderColor: 'divider',
            flexShrink: 0,
          }}
        >
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Activity
          </Typography>
          <IconButton onClick={onClose} aria-label="Close activity drawer" size="small">
            <CloseIcon />
          </IconButton>
        </Box>

        {/* Scope filter */}
        <Box sx={{ px: 2, py: 1, flexShrink: 0 }}>
          <ToggleButtonGroup
            value={effectiveScope}
            exclusive
            onChange={handleScopeChange}
            size="small"
          >
            {activeRolloutId && (
              <ToggleButton value="rollout">This rollout</ToggleButton>
            )}
            <ToggleButton value="project">This project</ToggleButton>
            <ToggleButton value="all">All</ToggleButton>
          </ToggleButtonGroup>
        </Box>

        {/* Content */}
        <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
          {effectiveScope === 'rollout' && activeRolloutId && (
            <>
              <RolloutEventSection rolloutId={activeRolloutId} />
              <Box sx={{ mt: 2 }}>
                <RolloutActivityTab rolloutId={activeRolloutId} />
              </Box>
            </>
          )}
          {effectiveScope === 'project' && (
            <RunsTable projectId={projectId} />
          )}
          {effectiveScope === 'all' && (
            <RunsTable all />
          )}
        </Box>
      </Box>
    </Drawer>
  )
}
