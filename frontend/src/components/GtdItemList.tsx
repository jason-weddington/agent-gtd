import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box,
  Typography,
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
  TextField,
  CircularProgress,
  Alert,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import DoneIcon from '@mui/icons-material/Done'
import DeleteIcon from '@mui/icons-material/Delete'
import { api, ApiError } from '../api'
import type { Item, Project, ItemStatus, Priority } from '../types'
import { useEvents } from '../contexts/EventStreamContext'

const ITEM_STATUS_LABELS: Record<ItemStatus, string> = {
  inbox: 'Inbox',
  next_action: 'Next Action',
  waiting_for: 'Waiting For',
  scheduled: 'Scheduled',
  someday_maybe: 'Someday',
  active: 'Active',
  done: 'Done',
  cancelled: 'Cancelled',
}

const PRIORITY_COLORS: Record<Priority, 'default' | 'info' | 'warning' | 'error'> = {
  low: 'default',
  normal: 'info',
  high: 'warning',
  urgent: 'error',
}

interface GtdItemListProps {
  title: string
  statusFilter: ItemStatus
  emptyTitle: string
  emptyDescription: string
  showWaitingOn?: boolean
}

export default function GtdItemList({
  title,
  statusFilter,
  emptyTitle,
  emptyDescription,
  showWaitingOn,
}: GtdItemListProps) {
  const [items, setItems] = useState<Item[]>([])
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Edit dialog
  const [editTarget, setEditTarget] = useState<Item | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editStatus, setEditStatus] = useState<ItemStatus>('next_action')
  const [editPriority, setEditPriority] = useState<Priority>('normal')
  const [editProjectId, setEditProjectId] = useState<string>('')
  const [saving, setSaving] = useState(false)

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<Item | null>(null)
  const [deleting, setDeleting] = useState(false)

  const { onEvent } = useEvents()
  const loadDataRef = useRef<() => Promise<void>>(undefined)

  const loadData = useCallback(async () => {
    try {
      const [filteredItems, projects] = await Promise.all([
        api.items.list({ status: statusFilter }),
        api.projects.list({ status: 'active' }),
      ])
      setItems(filteredItems)
      const map: Record<string, Project> = {}
      for (const p of projects) {
        map[p.id] = p
      }
      setProjectMap(map)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load items')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

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

  const openEdit = (item: Item) => {
    setEditTarget(item)
    setEditTitle(item.title)
    setEditDescription(item.description)
    setEditStatus(item.status)
    setEditPriority(item.priority)
    setEditProjectId(item.projectId ?? '')
  }

  const handleSave = async () => {
    if (!editTarget || !editTitle.trim()) return
    setSaving(true)
    try {
      await api.items.update(editTarget.id, {
        title: editTitle,
        description: editDescription,
        status: editStatus,
        priority: editPriority,
        projectId: editProjectId || null,
      })
      setEditTarget(null)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to update item')
    } finally {
      setSaving(false)
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

  const projects = Object.values(projectMap)

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 3 }}>
        {title}
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {items.length === 0 ? (
        <Box sx={{ textAlign: 'center', py: 6 }}>
          <Typography variant="h6" color="text.secondary" gutterBottom>
            {emptyTitle}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {emptyDescription}
          </Typography>
        </Box>
      ) : (
        <List>
          {items.map((item) => (
            <ListItem
              key={item.id}
              secondaryAction={
                <Box>
                  <IconButton size="small" onClick={() => openEdit(item)} title="Edit">
                    <EditIcon fontSize="small" />
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
              <ListItemText
                primary={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="body1">{item.title}</Typography>
                    {item.projectId && projectMap[item.projectId] && (
                      <Chip
                        label={projectMap[item.projectId].name}
                        size="small"
                        variant="outlined"
                      />
                    )}
                    <Chip
                      label={item.priority}
                      size="small"
                      color={PRIORITY_COLORS[item.priority]}
                    />
                    {item.dueDate && (
                      <Chip label={item.dueDate} size="small" variant="outlined" />
                    )}
                  </Box>
                }
                secondary={
                  showWaitingOn && item.waitingOn
                    ? `Waiting on: ${item.waitingOn}`
                    : undefined
                }
              />
            </ListItem>
          ))}
        </List>
      )}

      {/* Edit Dialog */}
      <Dialog
        open={Boolean(editTarget)}
        onClose={() => setEditTarget(null)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Edit Item</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Title"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            margin="normal"
            autoFocus
            size="small"
            required
          />
          <TextField
            fullWidth
            label="Description"
            value={editDescription}
            onChange={(e) => setEditDescription(e.target.value)}
            margin="normal"
            multiline
            rows={3}
            size="small"
          />
          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Status</InputLabel>
            <Select
              value={editStatus}
              onChange={(e) => setEditStatus(e.target.value as ItemStatus)}
              label="Status"
            >
              {Object.entries(ITEM_STATUS_LABELS).map(([value, label]) => (
                <MenuItem key={value} value={value}>
                  {label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Priority</InputLabel>
            <Select
              value={editPriority}
              onChange={(e) => setEditPriority(e.target.value as Priority)}
              label="Priority"
            >
              <MenuItem value="low">Low</MenuItem>
              <MenuItem value="normal">Normal</MenuItem>
              <MenuItem value="high">High</MenuItem>
              <MenuItem value="urgent">Urgent</MenuItem>
            </Select>
          </FormControl>
          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Project</InputLabel>
            <Select
              value={editProjectId}
              onChange={(e) => setEditProjectId(e.target.value)}
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
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={saving || !editTitle.trim()}
          >
            {saving ? <CircularProgress size={20} /> : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation */}
      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} fullWidth maxWidth="xs">
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

      {/* Item count */}
      {items.length > 0 && (
        <Box sx={{ mt: 2, display: 'flex', justifyContent: 'center' }}>
          <Chip
            label={`${items.length} item${items.length !== 1 ? 's' : ''}`}
            size="small"
            variant="outlined"
          />
        </Box>
      )}
    </Box>
  )
}
