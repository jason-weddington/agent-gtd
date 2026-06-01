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
import type { ActivityEvent, Item, Run, RunStatus } from '../types'
import RolloutEventFeed from './RolloutEventFeed'
import RolloutActivityTab from './RolloutActivityTab'
import ItemDetailDrawer from './ItemDetailDrawer'

// ---------------------------------------------------------------------------
// Type exports
// ---------------------------------------------------------------------------

export type Scope = 'rollout' | 'project' | 'all'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ActivityDrawerProps {
  open: boolean
  onClose: () => void
  projectId: string
  activeRolloutId: string | null
  scope: Scope
  onScopeChange: (scope: Scope) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [drawerItem, setDrawerItem] = useState<Item | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.rollouts.activity(rolloutId, 100)
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

  const handleItemClick = useCallback(async (itemId: string) => {
    try {
      const item = await api.items.get(itemId)
      setDrawerItem(item)
    } catch {
      // ignore — item may have been deleted or user lacks access
    }
  }, [])

  return (
    <>
      <RolloutEventFeed
        events={events}
        loading={loading}
        onItemClick={(id) => { void handleItemClick(id) }}
      />
      <ItemDetailDrawer
        item={drawerItem}
        onClose={() => setDrawerItem(null)}
        onEdit={() => {}}
      />
    </>
  )
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
  scope,
  onScopeChange,
}: ActivityDrawerProps) {
  // Derived: if activeRolloutId goes away, fall back from 'rollout' to 'project'
  const effectiveScope: Scope = scope === 'rollout' && !activeRolloutId ? 'project' : scope

  const handleScopeChange = (_: React.SyntheticEvent, value: Scope | null) => {
    if (value) onScopeChange(value)
  }

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      // Regression guard (GTD 36c1b775): this is a `temporary` Drawer (no
      // `variant` → MUI default), whose Modal otherwise locks body scroll
      // (`overflow:hidden` + `padding-right`) on open. The `top:'64px'` offset
      // below is scoped to the paper only, so the modal/backdrop span the whole
      // viewport. `disableScrollLock` keeps the drawer from mutating
      // `document.body`, so no scroll-lock residue can outlive the drawer and
      // leave the Sidebar nav unclickable after close.
      disableScrollLock
      sx={{
        '& .MuiDrawer-paper': {
          width: { xs: '100vw', sm: 792 },
          boxSizing: 'border-box',
          top: '64px',
          height: 'calc(100% - 64px)',
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
