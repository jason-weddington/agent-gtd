import { useState, useEffect, useCallback } from 'react'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { api, ApiError } from '../api'
import type { FailedRun, StaleRun } from '../types'

function statusChip(status: string) {
  const colors: Record<string, 'error' | 'warning' | 'success' | 'default'> = {
    failed: 'error',
    timeout: 'warning',
    success: 'success',
  }
  return (
    <Chip
      label={status}
      size="small"
      color={colors[status] ?? 'default'}
      variant="outlined"
    />
  )
}

function formatTs(ts: string | null): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

interface FailedRunsTableProps {
  runs: FailedRun[]
}

function FailedRunsTable({ runs }: FailedRunsTableProps) {
  if (runs.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
        No failed runs. 🎉
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
            <TableCell>Project</TableCell>
            <TableCell>Mode</TableCell>
            <TableCell>Error</TableCell>
            <TableCell>Finished</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id} hover>
              <TableCell>{statusChip(run.status)}</TableCell>
              <TableCell>
                <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                  {run.itemTitle ?? <em style={{ opacity: 0.5 }}>manage-mode</em>}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {run.id.slice(0, 8)}
                </Typography>
              </TableCell>
              <TableCell>
                <Typography variant="body2">{run.projectName}</Typography>
              </TableCell>
              <TableCell>
                <Chip label={run.mode} size="small" variant="outlined" />
              </TableCell>
              <TableCell>
                <Typography
                  variant="body2"
                  noWrap
                  sx={{ maxWidth: 300, fontFamily: 'monospace', fontSize: '0.75rem' }}
                  title={run.errorMsg}
                >
                  {run.errorMsg || <em style={{ opacity: 0.5 }}>—</em>}
                </Typography>
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

interface StaleRunsTableProps {
  runs: StaleRun[]
}

function StaleRunsTable({ runs }: StaleRunsTableProps) {
  if (runs.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
        No stale runs.
      </Typography>
    )
  }
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Item</TableCell>
            <TableCell>Item Status</TableCell>
            <TableCell>Project</TableCell>
            <TableCell>Branch</TableCell>
            <TableCell>Finished</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id} hover>
              <TableCell>
                <Typography variant="body2" noWrap sx={{ maxWidth: 220 }}>
                  {run.itemTitle ?? '—'}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {run.id.slice(0, 8)}
                </Typography>
              </TableCell>
              <TableCell>
                <Chip label={run.itemStatus} size="small" color="warning" variant="outlined" />
              </TableCell>
              <TableCell>
                <Typography variant="body2">{run.projectName}</Typography>
              </TableCell>
              <TableCell>
                <Typography
                  variant="body2"
                  noWrap
                  sx={{ maxWidth: 240, fontFamily: 'monospace', fontSize: '0.75rem' }}
                  title={run.featureBranch}
                >
                  {run.featureBranch}
                </Typography>
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

export default function Runs() {
  const [failedRuns, setFailedRuns] = useState<FailedRun[]>([])
  const [staleRuns, setStaleRuns] = useState<StaleRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [failed, stale] = await Promise.all([
        api.runs.failures(),
        api.runs.stale(),
      ])
      setFailedRuns(failed)
      setStaleRuns(stale)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Failed to load runs')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <Box sx={{ p: 3, maxWidth: 1200 }}>
      <Typography variant="h5" gutterBottom>
        Runs
      </Typography>

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {!loading && !error && (
        <>
          {/* Failed Runs */}
          <Box sx={{ mb: 4 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <ErrorOutlineIcon color="error" fontSize="small" />
              <Typography variant="h6">
                Failed Runs
              </Typography>
              {failedRuns.length > 0 && (
                <Chip label={failedRuns.length} size="small" color="error" />
              )}
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Runs that ended in <code>failed</code> or <code>timeout</code> status across your
              accessible projects.
            </Typography>
            <FailedRunsTable runs={failedRuns} />
          </Box>

          {/* Stale — Completed but Not Advanced */}
          <Box sx={{ mb: 4 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <WarningAmberIcon color="warning" fontSize="small" />
              <Typography variant="h6">
                Stale — Completed but Not Advanced
              </Typography>
              {staleRuns.length > 0 && (
                <Chip label={staleRuns.length} size="small" color="warning" />
              )}
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Build runs that succeeded in the last 72 hours but whose item was not moved to{' '}
              <code>review</code> — the agent may have skipped the status-flip step.
            </Typography>
            <StaleRunsTable runs={staleRuns} />
          </Box>
        </>
      )}
    </Box>
  )
}
