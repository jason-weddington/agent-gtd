import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
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
  InputAdornment,
  Tooltip,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import DoneIcon from '@mui/icons-material/Done'
import DeleteIcon from '@mui/icons-material/Delete'
import SearchIcon from '@mui/icons-material/Search'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'
import { api, ApiError } from '../api'
import type { Item, Project, ItemStatus, Priority } from '../types'
import { useEvents } from '../contexts/EventStreamContext'
import ItemDetailDrawer from './ItemDetailDrawer'

const ITEM_STATUS_LABELS: Record<ItemStatus, string> = {
  inbox: 'Inbox',
  new: 'New',
  ready: 'Ready',
  next_action: 'To Do',
  waiting_for: 'Waiting',
  someday_maybe: 'Someday',
  active: 'In Progress',
  review: 'Review',
  done: 'Done',
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
  const [search, setSearch] = useState('')

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

  // Detail drawer
  const [drawerItem, setDrawerItem] = useState<Item | null>(null)

  // Copy ID feedback
  const [copiedId, setCopiedId] = useState<string | null>(null)

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

  const filteredItems = useMemo(() => {
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q) ||
        (item.projectId && projectMap[item.projectId]?.name.toLowerCase().includes(q)),
    )
  }, [items, search, projectMap])

  const handleCopyId = (id: string) => {
    void navigator.clipboard.writeText(id)
    setCopiedId(id)
    setTimeout(() => setCopiedId((prev) => (prev === id ? null : prev)), 2000)
  }

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
        <>
          <TextField
            size="small"
            placeholder={`Search ${title.toLowerCase()}…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            sx={{ mb: 2, maxWidth: 400 }}
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" color="action" />
                  </InputAdornment>
                ),
              },
            }}
          />

          {filteredItems.length === 0 ? (
            <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
              No items match &ldquo;{search}&rdquo;
            </Typography>
          ) : (
        <List>
          {filteredItems.map((item) => (
            <ListItem
              key={item.id}
              onClick={() => setDrawerItem(item)}
              secondaryAction={
                <Box>
                  <IconButton size="small" onClick={(e) => { e.stopPropagation(); openEdit(item) }} title="Edit">
                    <EditIcon fontSize="small" />
                  </IconButton>
                  <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleDone(item) }} title="Done">
                    <DoneIcon fontSize="small" />
                  </IconButton>
                  <IconButton
                    size="small"
                    onClick={(e) => { e.stopPropagation(); setDeleteTarget(item) }}
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
                cursor: 'pointer',
                '&:hover': { bgcolor: 'action.hover' },
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
                  <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Typography component="span" variant="caption" color="text.disabled">
                      #{item.id.slice(0, 8)}
                    </Typography>
                    <Tooltip title={copiedId === item.id ? 'Copied!' : 'Copy ID'} placement="right">
                      <IconButton
                        size="small"
                        onClick={(e) => { e.stopPropagation(); handleCopyId(item.id) }}
                        sx={{ p: 0.25 }}
                        aria-label="Copy item ID"
                      >
                        {copiedId === item.id ? (
                          <CheckIcon sx={{ fontSize: 12, color: 'success.main' }} />
                        ) : (
                          <ContentCopyIcon sx={{ fontSize: 12 }} />
                        )}
                      </IconButton>
                    </Tooltip>
                    {showWaitingOn && item.waitingOn && (
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        Waiting on: {item.waitingOn}
                      </Typography>
                    )}
                  </Box>
                }
                secondaryTypographyProps={{ component: 'div' }}
              />
            </ListItem>
          ))}
        </List>
          )}
        </>
      )}

      {/* Edit Dialog */}
      <Dialog
        open={Boolean(editTarget)}
        onClose={() => setEditTarget(null)}
        fullWidth
        maxWidth="sm"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && ((e.metaKey || e.ctrlKey) || !(e.target instanceof HTMLTextAreaElement))) {
            e.preventDefault()
            if (editTitle.trim() && !saving) handleSave()
          }
        }}
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <span>Edit Item</span>
            {editTarget && (
              <>
                <Typography component="span" variant="caption" color="text.disabled">
                  #{editTarget.id.slice(0, 8)}
                </Typography>
                <Tooltip title={copiedId === editTarget.id ? 'Copied!' : 'Copy ID'} placement="right">
                  <IconButton
                    size="small"
                    onClick={() => handleCopyId(editTarget.id)}
                    sx={{ p: 0.25 }}
                    aria-label="Copy item ID"
                  >
                    {copiedId === editTarget.id ? (
                      <CheckIcon sx={{ fontSize: 14, color: 'success.main' }} />
                    ) : (
                      <ContentCopyIcon sx={{ fontSize: 14 }} />
                    )}
                  </IconButton>
                </Tooltip>
              </>
            )}
          </Box>
        </DialogTitle>
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

      {/* Item Detail Drawer */}
      <ItemDetailDrawer
        item={drawerItem}
        onClose={() => setDrawerItem(null)}
        onEdit={(item) => { setDrawerItem(null); openEdit(item) }}
        onItemUpdated={(updated) => {
          setDrawerItem(updated)
          setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        }}
        projectName={drawerItem?.projectId ? projectMap[drawerItem.projectId]?.name : undefined}
        projectGitOrigin={drawerItem?.projectId ? projectMap[drawerItem.projectId]?.gitOrigin : undefined}
      />
    </Box>
  )
}
