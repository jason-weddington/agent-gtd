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
import LockIcon from '@mui/icons-material/Lock'
import { api, ApiError } from '../api'
import type { Item, Project, ItemStatus, Priority, BlockerSummary } from '../types'
import { PRIORITY_BORDER } from '../priorityColors'
import { ENGINE_LABELS } from '../engineLabels'
import { hasUnresolvedBlockers } from '../utils'
import { useEvents } from '../contexts/EventStreamContext'
import ItemDetailDrawer from './ItemDetailDrawer'
import { BlockerPicker } from './BlockerPicker'

const ITEM_STATUS_LABELS: Partial<Record<ItemStatus, string>> = {
  inbox: 'Inbox',
  new: 'New',
  ready: 'Ready',
  active: 'In Progress',
  review: 'Review',
  waiting_for: 'Waiting',
  someday_maybe: 'Someday',
  done: 'Done',
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
  const [selectedLabels, setSelectedLabels] = useState<string[]>([])

  // Edit dialog
  const [editTarget, setEditTarget] = useState<Item | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editStatus, setEditStatus] = useState<ItemStatus>('next_action')
  const [editPriority, setEditPriority] = useState<Priority>('normal')
  const [editProjectId, setEditProjectId] = useState<string>('')
  const [editBlockers, setEditBlockers] = useState<BlockerSummary[]>([])
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

  const allLabels = useMemo(() => {
    const labelSet = new Set<string>()
    for (const item of items) {
      for (const label of item.labels) {
        labelSet.add(label)
      }
    }
    return Array.from(labelSet).sort()
  }, [items])

  const filteredItems = useMemo(() => {
    let result = items
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(
        (item) =>
          item.title.toLowerCase().includes(q) ||
          item.description.toLowerCase().includes(q) ||
          (item.projectId && projectMap[item.projectId]?.name.toLowerCase().includes(q)),
      )
    }
    if (selectedLabels.length > 0) {
      result = result.filter((item) =>
        selectedLabels.some((label) => item.labels.includes(label)),
      )
    }
    return result
  }, [items, search, projectMap, selectedLabels])

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
    setEditBlockers(item.blockers ?? [])
    if (item.blockers === undefined) {
      void api.items.blockers.list(item.id).then(setEditBlockers).catch(() => {})
    }
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
            sx={{ mb: 1, maxWidth: 400 }}
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

          {allLabels.length > 0 && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 2, alignItems: 'center' }}>
              {allLabels.map((label) => (
                <Chip
                  key={label}
                  label={label}
                  size="small"
                  onClick={() =>
                    setSelectedLabels((prev) =>
                      prev.includes(label)
                        ? prev.filter((l) => l !== label)
                        : [...prev, label],
                    )
                  }
                  color={selectedLabels.includes(label) ? 'primary' : 'default'}
                  variant={selectedLabels.includes(label) ? 'filled' : 'outlined'}
                />
              ))}
              {selectedLabels.length > 0 && (
                <Chip
                  label="Clear filter"
                  size="small"
                  variant="outlined"
                  onDelete={() => setSelectedLabels([])}
                  onClick={() => setSelectedLabels([])}
                />
              )}
            </Box>
          )}

          {filteredItems.length === 0 ? (
            <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
              {selectedLabels.length > 0
                ? 'No items match the selected labels.'
                : `No items match \u201c${search}\u201d`}
            </Typography>
          ) : (
        <List>
          {filteredItems.map((item) => (
            <ListItem
              key={item.id}
              onClick={() => setDrawerItem(item)}
              sx={{
                border: 1,
                borderColor: 'divider',
                borderLeft: `3px solid ${PRIORITY_BORDER[item.priority]}`,
                borderRadius: 1,
                mb: 1,
                cursor: 'pointer',
                pr: { xs: '112px', sm: '104px' },
                '&:hover': { bgcolor: 'action.hover' },
              }}
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
            >
              <ListItemText
                primary={
                  <Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, overflow: 'hidden' }}>
                      <Tooltip title={item.title}>
                        <Typography
                          variant="body1"
                          sx={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            minWidth: 0,
                          }}
                        >
                          {item.title}
                        </Typography>
                      </Tooltip>
                      {item.projectId &&
                        ((projectMap[item.projectId]?.memberCount ?? 0) > 0 ||
                          projectMap[item.projectId]?.isOwner === false) &&
                        item.createdBy &&
                        item.createdBy !== 'human' && (
                          <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>
                            by {item.createdBy}
                          </Typography>
                        )}
                      {hasUnresolvedBlockers(item.blockers) && (
                        <Tooltip
                          title={`Blocked by ${(item.blockers ?? []).filter((b) => b.status !== 'done').length} other item(s)`}
                        >
                          <LockIcon sx={{ fontSize: 14, color: 'warning.main', flexShrink: 0 }} />
                        </Tooltip>
                      )}
                      {item.projectId && projectMap[item.projectId] && (
                        <Chip
                          label={projectMap[item.projectId].name}
                          size="small"
                          variant="outlined"
                        />
                      )}
                      {item.dueDate && (
                        <Chip label={item.dueDate} size="small" variant="outlined" />
                      )}
                      {item.buildEngine && (
                        <Chip
                          label={ENGINE_LABELS[item.buildEngine]?.label ?? item.buildEngine}
                          size="small"
                          color={ENGINE_LABELS[item.buildEngine]?.color ?? 'default'}
                          sx={{ height: 20, fontSize: '0.7rem' }}
                        />
                      )}
                    </Box>
                    {item.labels.length > 0 && (
                      <Box sx={{ display: 'flex', gap: 0.5, mt: 0.25, flexWrap: 'wrap' }}>
                        {item.labels.slice(0, 4).map((label) => (
                          <Chip
                            key={label}
                            label={label}
                            size="small"
                            color={selectedLabels.includes(label) ? 'primary' : 'default'}
                            variant={selectedLabels.includes(label) ? 'filled' : 'outlined'}
                            sx={{ height: 20, fontSize: '0.7rem' }}
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedLabels((prev) =>
                                prev.includes(label)
                                  ? prev.filter((l) => l !== label)
                                  : [...prev, label],
                              )
                            }}
                          />
                        ))}
                        {item.labels.length > 4 && (
                          <Chip
                            label={`+${item.labels.length - 4} more`}
                            size="small"
                            variant="outlined"
                            sx={{ height: 20, fontSize: '0.7rem' }}
                          />
                        )}
                      </Box>
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
              {Object.entries(ITEM_STATUS_LABELS)
                .filter(([value]) => value !== 'inbox')
                .map(([value, label]) => (
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
          <Box sx={{ mt: 1, mb: 0.5 }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              Blocked by
            </Typography>
            {editTarget && (
              <BlockerPicker
                itemId={editTarget.id}
                blockers={editBlockers}
                onChange={setEditBlockers}
                disabled={saving}
              />
            )}
          </Box>
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
        projectIsOwner={
          drawerItem?.projectId
            ? projectMap[drawerItem.projectId]?.isOwner !== false
            : true
        }
        showAttribution={
          drawerItem?.projectId
            ? ((projectMap[drawerItem.projectId]?.memberCount ?? 0) > 0 ||
               projectMap[drawerItem.projectId]?.isOwner === false)
            : false
        }
      />
    </Box>
  )
}
