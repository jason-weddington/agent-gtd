import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import { api, ApiError } from '../api'
import type { FailedRun, Rollout, RolloutEvent, RolloutFailureFeed } from '../types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

function statusChip(status: string) {
  const colors: Record<string, 'error' | 'warning' | 'success' | 'info' | 'default'> = {
    failed: 'error',
    timeout: 'warning',
    success: 'success',
    running: 'info',
    pending: 'default',
    halted: 'warning',
    completed: 'success',
    cancelled: 'default',
  }
  return <Chip label={status} size="small" color={colors[status] ?? 'default'} variant="outlined" />
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface WaveHaltsTableProps {
  halts: RolloutEvent[]
}

function WaveHaltsTable({ halts }: WaveHaltsTableProps) {
  if (halts.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
        No wave halts recorded.
      </Typography>
    )
  }
  return (
    <TableContainer component={Paper} variant="outlined" sx={{ mb: 3 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Seq</TableCell>
            <TableCell>Timestamp</TableCell>
            <TableCell>Reason</TableCell>
            <TableCell>Offending Item</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {halts.map((event) => {
            const payload = (event.payload ?? {}) as Record<string, unknown>
            return (
              <TableRow key={event.id} hover>
                <TableCell>{event.seq}</TableCell>
                <TableCell>
                  <Typography variant="body2" noWrap>
                    {formatTs(event.ts)}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography
                    variant="body2"
                    sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}
                  >
                    {String(payload.reason ?? '—')}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                    {payload.item_id ? String(payload.item_id).slice(0, 8) : '—'}
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

interface FailedRunsTableProps {
  runs: FailedRun[]
}

function FailedRunsTable({ runs }: FailedRunsTableProps) {
  if (runs.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
        No failed or timed-out runs for this rollout.
      </Typography>
    )
  }
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Status</TableCell>
            <TableCell>Item</TableCell>
            <TableCell>Error</TableCell>
            <TableCell>Finished</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id} hover>
              <TableCell>{statusChip(run.status)}</TableCell>
              <TableCell>
                <Typography variant="body2" noWrap sx={{ maxWidth: 220 }}>
                  {run.itemTitle ?? <em style={{ opacity: 0.5 }}>—</em>}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {run.id.slice(0, 8)}
                </Typography>
              </TableCell>
              <TableCell>
                <Tooltip title={run.errorMsg} placement="top">
                  <Typography
                    variant="body2"
                    noWrap
                    sx={{ maxWidth: 280, fontFamily: 'monospace', fontSize: '0.75rem', cursor: 'help' }}
                  >
                    {run.errorMsg || '—'}
                  </Typography>
                </Tooltip>
              </TableCell>
              <TableCell>
                <Typography variant="body2" noWrap>
                  {formatTs(run.finishedAt)}
                </Typography>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

interface FailuresTabProps {
  rolloutId: string
}

function FailuresTab({ rolloutId }: FailuresTabProps) {
  const [feed, setFeed] = useState<RolloutFailureFeed | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await api.rollouts.failures(rolloutId)
      setFeed(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Failed to load failure feed')
      }
    } finally {
      setLoading(false)
    }
  }, [rolloutId])

  useEffect(() => {
    load()
  }, [load])

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={28} />
      </Box>
    )
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        {error}
      </Alert>
    )
  }

  const totalIssues = (feed?.waveHalts.length ?? 0) + (feed?.failedRuns.length ?? 0)

  return (
    <Box sx={{ pt: 2 }}>
      {totalIssues === 0 && (
        <Alert severity="success">No failures recorded for this rollout.</Alert>
      )}

      {(feed?.waveHalts.length ?? 0) > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 600 }}>
            Wave Halts
          </Typography>
          <WaveHaltsTable halts={feed?.waveHalts ?? []} />
        </Box>
      )}

      {(feed?.failedRuns.length ?? 0) > 0 && (
        <Box>
          <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 600 }}>
            Failed Runs
          </Typography>
          <FailedRunsTable runs={feed?.failedRuns ?? []} />
        </Box>
      )}

      {totalIssues === 0 && (feed?.waveHalts.length ?? 0) === 0 && (
        <Box>
          <WaveHaltsTable halts={[]} />
          <FailedRunsTable runs={[]} />
        </Box>
      )}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function RolloutDetail() {
  const { rolloutId } = useParams<{ rolloutId: string }>()
  const navigate = useNavigate()

  const [rollout, setRollout] = useState<Rollout | null>(null)
  const [loadingRollout, setLoadingRollout] = useState(true)
  const [rolloutError, setRolloutError] = useState<string | null>(null)
  const [tab, setTab] = useState<'failures'>('failures')

  const loadRollout = useCallback(async () => {
    if (!rolloutId) return
    try {
      const data = await api.rollouts.get(rolloutId)
      setRollout(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setRolloutError(err.detail)
      } else {
        setRolloutError('Failed to load rollout')
      }
    } finally {
      setLoadingRollout(false)
    }
  }, [rolloutId])

  useEffect(() => {
    loadRollout()
  }, [loadRollout])

  if (!rolloutId) {
    return <Alert severity="error">Missing rollout ID</Alert>
  }

  return (
    <Box sx={{ p: 3, maxWidth: 1200 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <IconButton onClick={() => navigate(-1)} size="small">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5">Rollout</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
          {rolloutId.slice(0, 8)}…
        </Typography>
        {rollout && statusChip(rollout.status)}
      </Box>

      {loadingRollout && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {rolloutError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {rolloutError}
        </Alert>
      )}

      {rollout && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Progress: {rollout.doneCount} / {rollout.totalCount} items done
            {rollout.haltReason && (
              <> &nbsp;·&nbsp; Halt reason: <code>{rollout.haltReason}</code></>
            )}
          </Typography>
        </Box>
      )}

      {/* Tabs */}
      <Tabs value={tab} onChange={(_e, v: 'failures') => setTab(v)} sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tab
          value="failures"
          label={
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <ErrorOutlineIcon fontSize="small" />
              Failures
            </Box>
          }
        />
      </Tabs>

      {tab === 'failures' && <FailuresTab rolloutId={rolloutId} />}
    </Box>
  )
}
