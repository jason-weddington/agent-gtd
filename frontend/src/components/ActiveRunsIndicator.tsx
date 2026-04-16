import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Badge,
  Box,
  IconButton,
  LinearProgress,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
} from '@mui/material'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useEvents } from '../contexts/EventStreamContext'
import type { Run, Item, Project } from '../types'

const POLL_INTERVAL_MS = 15000

function formatElapsed(startedAt: string | null): string {
  if (!startedAt) return '–'
  const elapsedSec = Math.floor(
    (Date.now() - new Date(startedAt).getTime()) / 1000,
  )
  if (elapsedSec < 60) return `${elapsedSec}s`
  if (elapsedSec < 3600) return `${Math.floor(elapsedSec / 60)}m`
  return `${Math.floor(elapsedSec / 3600)}h ${Math.floor((elapsedSec % 3600) / 60)}m`
}

/**
 * Header indicator that shows how many agent runs are currently active.
 * Clicking the icon opens a menu listing each active run with its item title,
 * project name, and elapsed time. Each entry navigates to the project page.
 *
 * Polls api.runs.list({ status: 'running' }) every 15 seconds and reacts
 * to SSE run_started / run_completed / run_failed events in real time.
 */
export default function ActiveRunsIndicator() {
  const [runs, setRuns] = useState<Run[]>([])
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [itemMap, setItemMap] = useState<Record<string, Item>>({})
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({})
  // Refs track which IDs we've already fetched so enrichment calls are idempotent
  const fetchedItemIds = useRef<Set<string>>(new Set())
  const fetchedProjectIds = useRef<Set<string>>(new Set())
  const { onEvent } = useEvents()
  const navigate = useNavigate()

  // Using void .then() (not async/await) so the eslint react-hooks/set-state-in-effect
  // rule doesn't consider this a direct setState call chain from within the effect.
  const loadRuns = useCallback(() => {
    void api.runs
      .list({ status: 'running' })
      .then((activeRuns) => {
        setRuns(activeRuns)

        // Lazily enrich each run with item title and project name.
        // Fire-and-forget; refs prevent duplicate requests across polls.
        for (const run of activeRuns) {
          if (!fetchedItemIds.current.has(run.itemId)) {
            fetchedItemIds.current.add(run.itemId)
            void api.items
              .get(run.itemId)
              .then((item) =>
                setItemMap((prev) => ({ ...prev, [run.itemId]: item })),
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

  // React to SSE events so the count updates in real time
  useEffect(() => {
    const unsubs = [
      onEvent('run_started', () => loadRuns()),
      onEvent('run_completed', () => loadRuns()),
      onEvent('run_failed', () => loadRuns()),
    ]
    return () => unsubs.forEach((u) => u())
  }, [onEvent, loadRuns])

  const count = runs.length

  return (
    <>
      <Tooltip
        title={
          count > 0
            ? `${count} active agent run${count !== 1 ? 's' : ''}`
            : 'No active runs'
        }
      >
        <IconButton
          color="inherit"
          onClick={(e) => setAnchorEl(e.currentTarget)}
          aria-label="Active agent runs"
        >
          <Badge badgeContent={count} color="primary" invisible={count === 0}>
            <SmartToyOutlinedIcon
              sx={count > 0 ? {
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
        {count > 0 && (
          <LinearProgress color="success" sx={{ height: 2 }} />
        )}
        {runs.length === 0 ? (
          <MenuItem disabled>
            <Typography variant="body2" color="text.secondary">
              No active runs
            </Typography>
          </MenuItem>
        ) : (
          runs.map((run) => {
            const item = itemMap[run.itemId]
            const project = projectMap[run.projectId]
            return (
              <MenuItem
                key={run.id}
                onClick={() => {
                  setAnchorEl(null)
                  navigate(`/projects/${run.projectId}?item=${run.itemId}`)
                }}
              >
                <Box
                  sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 0.25,
                    py: 0.5,
                    overflow: 'hidden',
                  }}
                >
                  <Typography variant="body2" fontWeight={500} noWrap>
                    {item?.title ?? run.featureBranch}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" noWrap>
                    {project?.name ?? run.projectId} ·{' '}
                    {formatElapsed(run.startedAt)}
                  </Typography>
                </Box>
              </MenuItem>
            )
          })
        )}
      </Menu>
    </>
  )
}
