import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box,
  Typography,
  TextField,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  CircularProgress,
  Alert,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'
import DoneIcon from '@mui/icons-material/Done'
import DeleteIcon from '@mui/icons-material/Delete'
import DriveFileMoveIcon from '@mui/icons-material/DriveFileMove'
import { api, ApiError } from '../api'
import type { Item, Project, ItemStatus, Priority } from '../types'
import { useEvents } from '../contexts/EventStreamContext'

export default function Inbox() {
  const navigate = useNavigate()
  const [items, setItems] = useState<Item[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [captureText, setCaptureText] = useState('')
  const [capturing, setCapturing] = useState(false)

  // Triage dialog
  const [triageTarget, setTriageTarget] = useState<Item | null>(null)
  const [triageProjectId, setTriageProjectId] = useState<string>('')
  const [triageStatus, setTriageStatus] = useState<ItemStatus>('next_action')
  const [triagePriority, setTriagePriority] = useState<Priority>('normal')
  const [triaging, setTriaging] = useState(false)

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<Item | null>(null)
  const [deleting, setDeleting] = useState(false)

  const { onEvent } = useEvents()
  const loadDataRef = useRef<() => Promise<void>>(undefined)

  const loadData = useCallback(async () => {
    try {
      const [inboxItems, activeProjects] = await Promise.all([
        api.items.inbox(),
        api.projects.list({ status: 'active' }),
      ])
      setItems(inboxItems)
      setProjects(activeProjects)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load inbox')
    } finally {
      setLoading(false)
    }
  }, [])

  loadDataRef.current = loadData

  useEffect(() => {
    loadData()
  }, [loadData])

  // Re-fetch when items change via SSE
  useEffect(() => {
    const unsubs = [
      onEvent('item_created', () => { loadDataRef.current?.() }),
      onEvent('item_updated', () => { loadDataRef.current?.() }),
      onEvent('item_deleted', () => { loadDataRef.current?.() }),
    ]
    return () => { unsubs.forEach((u) => u()) }
  }, [onEvent])

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

  const handleDone = async (item: Item) => {
    try {
      await api.items.update(item.id, { status: 'done' })
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to mark done')
    }
  }

  const openTriage = (item: Item) => {
    setTriageTarget(item)
    setTriageProjectId(item.projectId ?? '')
    setTriageStatus('next_action')
    setTriagePriority(item.priority)
  }

  const handleTriage = async () => {
    if (!triageTarget) return
    setTriaging(true)
    try {
      const update: Record<string, unknown> = {
        status: triageStatus,
        priority: triagePriority,
      }
      if (triageProjectId) {
        update.projectId = triageProjectId
      }
      await api.items.update(triageTarget.id, update)
      setTriageTarget(null)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to triage item')
    } finally {
      setTriaging(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.items.delete(deleteTarget.id)
      setDeleteTarget(null)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to delete item')
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5">Inbox</Typography>
        {items.length > 0 && (
          <Button
            variant="outlined"
            size="small"
            onClick={() => navigate('/inbox/process')}
          >
            Process Inbox
          </Button>
        )}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Quick capture */}
      <TextField
        fullWidth
        placeholder="Capture a new item..."
        value={captureText}
        onChange={(e) => setCaptureText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleCapture()
        }}
        disabled={capturing}
        size="small"
        sx={{ mb: 3 }}
        slotProps={{
          input: {
            endAdornment: capturing ? <CircularProgress size={20} /> : null,
          },
        }}
      />

      {items.length === 0 ? (
        <Box sx={{ textAlign: 'center', py: 6 }}>
          <Typography variant="h6" color="text.secondary" gutterBottom>
            Inbox is empty
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Capture items above or they'll appear here when added.
          </Typography>
        </Box>
      ) : (
        <List>
          {items.map((item) => (
            <ListItem
              key={item.id}
              secondaryAction={
                <Box>
                  <IconButton size="small" onClick={() => openTriage(item)} title="Triage">
                    <DriveFileMoveIcon fontSize="small" />
                  </IconButton>
                  <IconButton size="small" onClick={() => handleDone(item)} title="Done">
                    <DoneIcon fontSize="small" />
                  </IconButton>
                  <IconButton
                    size="small"
                    onClick={() => setDeleteTarget(item)}
                    title="Delete"
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Box>
              }
              sx={{
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                mb: 1,
              }}
            >
              <ListItemText primary={item.title} />
            </ListItem>
          ))}
        </List>
      )}

      {/* Triage Dialog */}
      <Dialog
        open={Boolean(triageTarget)}
        onClose={() => setTriageTarget(null)}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>Triage: {triageTarget?.title}</DialogTitle>
        <DialogContent>
          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Project</InputLabel>
            <Select
              value={triageProjectId}
              onChange={(e) => setTriageProjectId(e.target.value)}
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

          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Status</InputLabel>
            <Select
              value={triageStatus}
              onChange={(e) => setTriageStatus(e.target.value as ItemStatus)}
              label="Status"
            >
              <MenuItem value="next_action">Next Action</MenuItem>
              <MenuItem value="waiting_for">Waiting For</MenuItem>
              <MenuItem value="scheduled">Scheduled</MenuItem>
              <MenuItem value="someday_maybe">Someday/Maybe</MenuItem>
              <MenuItem value="active">Active</MenuItem>
            </Select>
          </FormControl>

          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Priority</InputLabel>
            <Select
              value={triagePriority}
              onChange={(e) => setTriagePriority(e.target.value as Priority)}
              label="Priority"
            >
              <MenuItem value="low">Low</MenuItem>
              <MenuItem value="normal">Normal</MenuItem>
              <MenuItem value="high">High</MenuItem>
              <MenuItem value="urgent">Urgent</MenuItem>
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTriageTarget(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleTriage} disabled={triaging}>
            {triaging ? <CircularProgress size={20} /> : 'Triage'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation */}
      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete Item</DialogTitle>
        <DialogContent>
          <Typography>
            Delete &ldquo;{deleteTarget?.title}&rdquo;?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting ? <CircularProgress size={20} /> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Inbox count chip */}
      {items.length > 0 && (
        <Box sx={{ mt: 2, display: 'flex', justifyContent: 'center' }}>
          <Chip
            label={`${items.length} item${items.length !== 1 ? 's' : ''} in inbox`}
            size="small"
            variant="outlined"
          />
        </Box>
      )}
    </Box>
  )
}
