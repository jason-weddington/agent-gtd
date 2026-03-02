import { useState, useEffect, useCallback } from 'react'
import {
  Dialog,
  TextField,
  Box,
  Collapse,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Slide,
  Snackbar,
  CircularProgress,
} from '@mui/material'
import type { TransitionProps } from '@mui/material/transitions'
import BoltIcon from '@mui/icons-material/Bolt'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import { forwardRef } from 'react'
import { api } from '../api'
import type { Project, ItemStatus, Priority } from '../types'

const SlideDown = forwardRef(function SlideDown(
  props: TransitionProps & { children: React.ReactElement },
  ref: React.Ref<unknown>,
) {
  return <Slide direction="down" ref={ref} {...props} />
})

interface QuickCaptureProps {
  open: boolean
  onClose: () => void
}

export default function QuickCapture({ open, onClose }: QuickCaptureProps) {
  const [title, setTitle] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [projectId, setProjectId] = useState('')
  const [status, setStatus] = useState<ItemStatus>('inbox')
  const [priority, setPriority] = useState<Priority>('normal')
  const [projects, setProjects] = useState<Project[]>([])
  const [saving, setSaving] = useState(false)
  const [justCaptured, setJustCaptured] = useState<string | null>(null)
  const [toast, setToast] = useState(false)

  // Load projects when expanded
  useEffect(() => {
    if (expanded && projects.length === 0) {
      api.projects.list({ status: 'active' }).then(setProjects).catch(() => {})
    }
  }, [expanded, projects.length])

  const reset = useCallback(() => {
    setTitle('')
    setExpanded(false)
    setProjectId('')
    setStatus('inbox')
    setPriority('normal')
    setJustCaptured(null)
  }, [])

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) reset()
  }, [open, reset])

  const handleSubmit = async () => {
    const trimmed = title.trim()
    if (!trimmed || saving) return
    setSaving(true)
    try {
      if (expanded && (projectId || status !== 'inbox' || priority !== 'normal')) {
        const data: Record<string, unknown> = { title: trimmed, status, priority }
        if (projectId) data.projectId = projectId
        await api.items.create(data as Parameters<typeof api.items.create>[0])
      } else {
        await api.items.capture(trimmed)
      }
      setJustCaptured(trimmed)
      setTitle('')
      setToast(true)
      // Auto-clear the "just captured" indicator
      setTimeout(() => setJustCaptured(null), 1500)
    } catch {
      // Keep dialog open on error so user doesn't lose input
    } finally {
      setSaving(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
    if (e.key === 'Tab' && !expanded && title.length > 0) {
      e.preventDefault()
      setExpanded(true)
    }
    if (e.key === 'Escape') {
      if (expanded) {
        setExpanded(false)
      } else {
        onClose()
      }
    }
  }

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        TransitionComponent={SlideDown}
        fullWidth
        maxWidth="sm"
        slotProps={{
          paper: {
            sx: {
              position: 'absolute',
              top: '10vh',
              m: 0,
              mx: 'auto',
              borderRadius: 2,
            },
          },
          backdrop: {
            sx: { backdropFilter: 'blur(4px)' },
          },
        }}
      >
        <Box sx={{ p: 2 }}>
          <TextField
            fullWidth
            autoFocus
            placeholder="Capture a thought..."
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={saving}
            variant="standard"
            slotProps={{
              input: {
                startAdornment: (
                  <BoltIcon sx={{ mr: 1, color: 'primary.main', fontSize: 20 }} />
                ),
                endAdornment: saving ? <CircularProgress size={18} /> : null,
                disableUnderline: true,
                sx: { fontSize: '1.1rem' },
              },
            }}
          />

          {justCaptured && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 1 }}>
              <CheckCircleOutlineIcon sx={{ fontSize: 16, color: 'success.main' }} />
              <Typography variant="body2" color="success.main">
                {justCaptured}
              </Typography>
            </Box>
          )}

          <Collapse in={expanded}>
            <Box sx={{ mt: 2, display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
              <FormControl size="small" sx={{ minWidth: 160, flex: 1 }}>
                <InputLabel>Project</InputLabel>
                <Select
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  label="Project"
                >
                  <MenuItem value="">
                    <em>None</em>
                  </MenuItem>
                  {projects.map((p) => (
                    <MenuItem key={p.id} value={p.id}>
                      {p.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>Priority</InputLabel>
                <Select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as Priority)}
                  label="Priority"
                >
                  <MenuItem value="low">Low</MenuItem>
                  <MenuItem value="normal">Normal</MenuItem>
                  <MenuItem value="high">High</MenuItem>
                  <MenuItem value="urgent">Urgent</MenuItem>
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>Status</InputLabel>
                <Select
                  value={status}
                  onChange={(e) => setStatus(e.target.value as ItemStatus)}
                  label="Status"
                >
                  <MenuItem value="inbox">Inbox</MenuItem>
                  <MenuItem value="next_action">Next Action</MenuItem>
                  <MenuItem value="waiting_for">Waiting For</MenuItem>
                  <MenuItem value="scheduled">Scheduled</MenuItem>
                  <MenuItem value="someday_maybe">Someday/Maybe</MenuItem>
                  <MenuItem value="active">Active</MenuItem>
                </Select>
              </FormControl>
            </Box>
          </Collapse>

          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ mt: 1.5, display: 'block' }}
          >
            {expanded ? 'Enter to save' : 'Tab for options'} &middot; Esc to close
          </Typography>
        </Box>
      </Dialog>

      <Snackbar
        open={toast}
        autoHideDuration={3000}
        onClose={() => setToast(false)}
        message="Captured to Inbox"
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      />
    </>
  )
}
