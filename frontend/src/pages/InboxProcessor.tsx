import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Box,
  Typography,
  TextField,
  Button,
  LinearProgress,
  CircularProgress,
  Alert,
  Paper,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import { api, ApiError } from '../api'
import type { Item, Project } from '../types'
import ProcessorActions from '../components/ProcessorActions'
import type { ProcessorResult } from '../components/ProcessorActions'

export default function InboxProcessor() {
  const navigate = useNavigate()
  const location = useLocation()
  const returnTo = (location.state as { returnTo?: string } | null)?.returnTo ?? '/'
  const [items, setItems] = useState<Item[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [editedTitle, setEditedTitle] = useState('')
  const [totalCount, setTotalCount] = useState(0)

  const loadData = useCallback(async () => {
    try {
      const [inboxItems, activeProjects] = await Promise.all([
        api.items.inbox(),
        api.projects.list({ status: 'active' }),
      ])
      setItems(inboxItems)
      setProjects(activeProjects)
      setTotalCount((prev) => (prev === 0 ? inboxItems.length : prev))
      if (inboxItems.length > 0 && currentIndex === 0) {
        setEditedTitle(inboxItems[0].title)
      }
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load inbox')
    } finally {
      setLoading(false)
    }
  }, [currentIndex])

  useEffect(() => {
    loadData()
  }, [loadData])

  const currentItem: Item | undefined = items[currentIndex]
  const processedCount = totalCount - items.length + currentIndex

  const advanceToNext = useCallback(() => {
    const nextIndex = currentIndex + 1
    if (nextIndex < items.length) {
      setCurrentIndex(nextIndex)
      setEditedTitle(items[nextIndex].title)
    } else {
      // All done — set index past end to show completion screen
      setCurrentIndex(items.length)
    }
  }, [currentIndex, items])

  const handleConfirm = async (result: ProcessorResult) => {
    if (!currentItem) return
    setSubmitting(true)
    try {
      const titleChanged = editedTitle.trim() !== currentItem.title
      const titleUpdate = titleChanged ? { title: editedTitle.trim() } : {}

      switch (result.outcome) {
        case 'next_action': {
          await api.items.update(currentItem.id, {
            status: 'next_action',
            priority: result.priority,
            ...(result.projectId ? { projectId: result.projectId } : {}),
            ...titleUpdate,
          })
          break
        }
        case 'waiting_for': {
          await api.items.update(currentItem.id, {
            status: 'waiting_for',
            priority: result.priority,
            waitingOn: result.waitingOn ?? '',
            ...(result.projectId ? { projectId: result.projectId } : {}),
            ...titleUpdate,
          })
          break
        }
        case 'scheduled': {
          await api.items.update(currentItem.id, {
            status: 'scheduled',
            priority: result.priority,
            dueDate: result.dueDate ?? null,
            ...(result.projectId ? { projectId: result.projectId } : {}),
            ...titleUpdate,
          })
          break
        }
        case 'someday_maybe': {
          await api.items.update(currentItem.id, {
            status: 'someday_maybe',
            ...(result.projectId ? { projectId: result.projectId } : {}),
            ...titleUpdate,
          })
          break
        }
        case 'project': {
          const newProject = await api.projects.create({
            name: result.newProjectName ?? currentItem.title,
          })
          // Refresh projects list for subsequent items
          setProjects((prev) => [...prev, newProject])
          if (result.keepAsAction) {
            await api.items.update(currentItem.id, {
              status: 'next_action',
              projectId: newProject.id,
              ...titleUpdate,
            })
          } else {
            await api.items.delete(currentItem.id)
          }
          break
        }
        case 'done': {
          await api.items.update(currentItem.id, { status: 'done', ...titleUpdate })
          break
        }
        case 'trash': {
          await api.items.delete(currentItem.id)
          break
        }
      }

      advanceToNext()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to process item')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  // Empty inbox — nothing to process
  if (totalCount === 0) {
    return (
      <Box sx={{ textAlign: 'center', py: 8 }}>
        <Typography variant="h6" color="text.secondary" gutterBottom>
          Inbox is empty
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Nothing to process. Capture some items first.
        </Typography>
        <Button variant="outlined" startIcon={<ArrowBackIcon />} onClick={() => navigate(returnTo)}>
          Back
        </Button>
      </Box>
    )
  }

  // All items processed
  if (!currentItem) {
    return (
      <Box sx={{ textAlign: 'center', py: 8 }}>
        <CheckCircleOutlineIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
        <Typography variant="h5" gutterBottom>
          All done!
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
          You processed {totalCount} item{totalCount !== 1 ? 's' : ''}.
        </Typography>
        <Button variant="contained" startIcon={<ArrowBackIcon />} onClick={() => navigate(returnTo)}>
          Back
        </Button>
      </Box>
    )
  }

  const progress = totalCount > 0 ? (processedCount / totalCount) * 100 : 0

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Button size="small" startIcon={<ArrowBackIcon />} onClick={() => navigate(returnTo)}>
          Back
        </Button>
        <Typography variant="body2" color="text.secondary">
          {processedCount + 1} of {totalCount}
        </Typography>
      </Box>

      {/* Progress bar */}
      <LinearProgress
        variant="determinate"
        value={progress}
        sx={{ mb: 3, borderRadius: 1, height: 6 }}
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Split panel */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
          gap: 3,
        }}
      >
        {/* Left: Item card */}
        <Paper variant="outlined" sx={{ p: 3 }}>
          <TextField
            fullWidth
            value={editedTitle}
            onChange={(e) => setEditedTitle(e.target.value)}
            variant="standard"
            slotProps={{
              input: {
                sx: { fontSize: '1.25rem', fontWeight: 500 },
              },
            }}
            sx={{ mb: 2 }}
          />
          {currentItem.description && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2, whiteSpace: 'pre-wrap' }}>
              {currentItem.description}
            </Typography>
          )}
          <Typography variant="caption" color="text.disabled">
            Captured: {new Date(currentItem.createdAt).toLocaleDateString(undefined, {
              year: 'numeric',
              month: 'short',
              day: 'numeric',
            })}
          </Typography>
        </Paper>

        {/* Right: Actions */}
        <Paper variant="outlined" sx={{ p: 3 }}>
          <ProcessorActions
            key={currentItem.id}
            itemTitle={editedTitle}
            projects={projects}
            onConfirm={handleConfirm}
            submitting={submitting}
          />
        </Paper>
      </Box>
    </Box>
  )
}
