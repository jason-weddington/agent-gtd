import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Typography,
  Paper,
  Checkbox,
  FormControlLabel,
  Chip,
  Button,
  TextField,
  CircularProgress,
  Alert,
  Divider,
  IconButton,
  LinearProgress,
} from '@mui/material'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import { api, ApiError } from '../api'
import type { Item, Project } from '../types'
import { useEvents } from '../contexts/EventStreamContext'
import ProjectReviewCard from '../components/ProjectReviewCard'

export default function WeeklyReview() {
  const navigate = useNavigate()

  // Data
  const [inboxCount, setInboxCount] = useState(0)
  const [nextActionCount, setNextActionCount] = useState(0)
  const [waitingForCount, setWaitingForCount] = useState(0)
  const [somedayCount, setSomedayCount] = useState(0)
  const [projects, setProjects] = useState<Project[]>([])
  const [projectItems, setProjectItems] = useState<Record<string, Item[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Review progress
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  // Quick capture
  const [captureText, setCaptureText] = useState('')
  const [capturing, setCapturing] = useState(false)

  // Finish state
  const [finished, setFinished] = useState(false)

  const { onEvent } = useEvents()
  const loadDataRef = useRef<() => Promise<void>>(undefined)

  const loadData = useCallback(async () => {
    try {
      const [inboxItems, nextActions, waitingFor, someday, activeProjects] = await Promise.all([
        api.items.inbox(),
        api.items.list({ status: 'next_action' }),
        api.items.list({ status: 'waiting_for' }),
        api.items.list({ status: 'someday_maybe' }),
        api.projects.list({ status: 'active' }),
      ])
      setInboxCount(inboxItems.length)
      setNextActionCount(nextActions.length)
      setWaitingForCount(waitingFor.length)
      setSomedayCount(someday.length)
      setProjects(activeProjects)

      const entries = await Promise.all(
        activeProjects.map(async (p) => [p.id, await api.projects.items(p.id)] as const),
      )
      setProjectItems(Object.fromEntries(entries))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load review data')
    } finally {
      setLoading(false)
    }
  }, [])

  loadDataRef.current = loadData

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    const unsubs = [
      onEvent('item_created', () => { loadDataRef.current?.() }),
      onEvent('item_updated', () => { loadDataRef.current?.() }),
      onEvent('item_deleted', () => { loadDataRef.current?.() }),
      onEvent('project_updated', () => { loadDataRef.current?.() }),
    ]
    return () => { unsubs.forEach((u) => u()) }
  }, [onEvent])

  const toggle = (key: string) => {
    setChecked((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const handleCapture = async () => {
    const title = captureText.trim()
    if (!title) return
    setCapturing(true)
    try {
      await api.items.capture(title)
      setCaptureText('')
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to capture item')
    } finally {
      setCapturing(false)
    }
  }

  // Progress calculation
  const totalSteps = 3 + projects.length + 1 + 1 // 3 lists + N projects + inbox + brainstorm
  const checkedCount = Object.values(checked).filter(Boolean).length
  const progress = totalSteps > 0 ? (checkedCount / totalSteps) * 100 : 0

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (finished) {
    return (
      <Box sx={{ textAlign: 'center', py: 8 }}>
        <CheckCircleOutlineIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
        <Typography variant="h5" gutterBottom>
          Review complete
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
          {nextActionCount} next action{nextActionCount !== 1 ? 's' : ''},{' '}
          {waitingForCount} waiting-for item{waitingForCount !== 1 ? 's' : ''}{' '}
          across {projects.length} active project{projects.length !== 1 ? 's' : ''}.
        </Typography>
        <Button variant="contained" onClick={() => navigate('/')}>
          Back to Inbox
        </Button>
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Weekly Review
      </Typography>

      {/* Progress bar */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
        <LinearProgress
          variant="determinate"
          value={progress}
          sx={{ flex: 1, borderRadius: 1, height: 6 }}
        />
        <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
          {checkedCount} of {totalSteps} steps
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Section 1: Get Clear */}
      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Get Clear
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body1">Inbox</Typography>
            {inboxCount > 0 ? (
              <Chip label={`${inboxCount} item${inboxCount !== 1 ? 's' : ''}`} size="small" color="warning" />
            ) : (
              <Chip label="Clear" size="small" color="success" />
            )}
          </Box>
          <Button
            variant="outlined"
            size="small"
            disabled={inboxCount === 0}
            onClick={() => navigate('/inbox/process')}
          >
            Process Inbox
          </Button>
        </Box>
        <FormControlLabel
          control={<Checkbox checked={!!checked['inbox']} onChange={() => toggle('inbox')} size="small" />}
          label="Inbox processed"
        />
      </Paper>

      {/* Section 2: Get Current */}
      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Get Current
        </Typography>

        {/* List review rows */}
        {[
          { key: 'next-actions', label: 'Next Actions', count: nextActionCount, path: '/next-actions' },
          { key: 'waiting-for', label: 'Waiting For', count: waitingForCount, path: '/waiting-for' },
          { key: 'someday-maybe', label: 'Someday / Maybe', count: somedayCount, path: '/someday-maybe' },
        ].map((row) => (
          <Box
            key={row.key}
            sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={!!checked[row.key]}
                    onChange={() => toggle(row.key)}
                    size="small"
                  />
                }
                label={row.label}
              />
              <Chip label={row.count} size="small" variant="outlined" sx={{ ml: 1 }} />
            </Box>
            <IconButton size="small" onClick={() => navigate(row.path)} title={`Open ${row.label}`}>
              <OpenInNewIcon fontSize="small" />
            </IconButton>
          </Box>
        ))}

        <Divider sx={{ my: 2 }} />

        {/* Active Projects */}
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Active Projects
        </Typography>
        {projects.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No active projects.
          </Typography>
        ) : (
          projects.map((project) => (
            <ProjectReviewCard
              key={project.id}
              project={project}
              items={projectItems[project.id] ?? []}
              reviewed={!!checked[`project-${project.id}`]}
              onToggleReviewed={() => toggle(`project-${project.id}`)}
            />
          ))
        )}
      </Paper>

      {/* Section 3: Get Creative */}
      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Get Creative
        </Typography>
        <TextField
          fullWidth
          placeholder="Capture a new idea..."
          value={captureText}
          onChange={(e) => setCaptureText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleCapture()
          }}
          disabled={capturing}
          size="small"
          sx={{ mb: 2 }}
          slotProps={{
            input: {
              endAdornment: capturing ? <CircularProgress size={20} /> : null,
            },
          }}
        />
        <FormControlLabel
          control={<Checkbox checked={!!checked['brainstorm']} onChange={() => toggle('brainstorm')} size="small" />}
          label="Brainstormed new ideas"
        />
      </Paper>

      {/* Finish */}
      <Box sx={{ display: 'flex', justifyContent: 'center' }}>
        <Button variant="contained" size="large" onClick={() => setFinished(true)}>
          Finish Review
        </Button>
      </Box>
    </Box>
  )
}
