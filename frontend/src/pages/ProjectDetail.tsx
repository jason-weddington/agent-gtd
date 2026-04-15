import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Box,
  Typography,
  Button,
  Chip,
  Tabs,
  Tab,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  CircularProgress,
  Alert,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  ToggleButtonGroup,
  ToggleButton,
  FormControlLabel,
  Checkbox,
  Divider,
  InputAdornment,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import DoneIcon from '@mui/icons-material/Done'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ViewListIcon from '@mui/icons-material/ViewList'
import ViewKanbanIcon from '@mui/icons-material/ViewKanban'
import SearchIcon from '@mui/icons-material/Search'
import ClearIcon from '@mui/icons-material/Clear'
import { api, ApiError } from '../api'
import type { Project, Item, Note, Comment, ItemStatus, Priority, ProjectStatus } from '../types'
import { useEvents } from '../contexts/EventStreamContext'
import { useQuickCapture } from '../contexts/QuickCaptureContext'
import KanbanBoard from '../components/KanbanBoard'
import NoteEditor from '../components/NoteEditor'
import ItemDetailDrawer from '../components/ItemDetailDrawer'

const STATUS_COLORS: Record<ProjectStatus, 'success' | 'default' | 'warning' | 'error'> = {
  active: 'success',
  completed: 'default',
  on_hold: 'warning',
  cancelled: 'error',
}

const STATUS_LABELS: Record<ProjectStatus, string> = {
  active: 'Active',
  completed: 'Completed',
  on_hold: 'On Hold',
  cancelled: 'Cancelled',
}

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

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const [project, setProject] = useState<Project | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [comments, setComments] = useState<Comment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState(0)

  // Project comment input
  const [newComment, setNewComment] = useState('')
  const [savingComment, setSavingComment] = useState(false)

  // Item comments (loaded when editing)
  const [itemComments, setItemComments] = useState<Comment[]>([])
  const [newItemComment, setNewItemComment] = useState('')
  const [savingItemComment, setSavingItemComment] = useState(false)

  // Project edit dialog
  const [editProjectOpen, setEditProjectOpen] = useState(false)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editStatus, setEditStatus] = useState<ProjectStatus>('active')
  const [editArea, setEditArea] = useState('')
  const [editGitOrigin, setEditGitOrigin] = useState('')
  const [editKbProjectRef, setEditKbProjectRef] = useState('')
  const [savingProject, setSavingProject] = useState(false)

  // Item dialog
  const [itemDialogOpen, setItemDialogOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<Item | null>(null)
  const [itemTitle, setItemTitle] = useState('')
  const [itemDescription, setItemDescription] = useState('')
  const [itemStatus, setItemStatus] = useState<ItemStatus>('active')
  const [itemPriority, setItemPriority] = useState<Priority>('normal')
  const [itemDueDate, setItemDueDate] = useState('')
  const [savingItem, setSavingItem] = useState(false)

  // Note dialog
  const [noteDialogOpen, setNoteDialogOpen] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [noteTitle, setNoteTitle] = useState('')
  const [noteContent, setNoteContent] = useState('')
  const [savingNote, setSavingNote] = useState(false)

  // Detail drawer
  const [drawerItem, setDrawerItem] = useState<Item | null>(null)

  // View toggle (list vs board)
  const [itemView, setItemView] = useState<'list' | 'board'>(() => {
    return (localStorage.getItem(`gtd_view_${projectId}`) as 'list' | 'board') || 'list'
  })

  // Show completed items toggle
  const [showCompleted, setShowCompleted] = useState(false)

  // Search / filter
  const [searchQuery, setSearchQuery] = useState('')

  // Delete confirmation
  const [deleteItemTarget, setDeleteItemTarget] = useState<Item | null>(null)
  const [deleteNoteTarget, setDeleteNoteTarget] = useState<Note | null>(null)
  const [deletingItem, setDeletingItem] = useState(false)
  const [deletingNote, setDeletingNote] = useState(false)

  const { onEvent } = useEvents()
  const { setActiveProject, captureCount } = useQuickCapture()
  const loadDataRef = useRef<() => Promise<void>>(undefined)

  const loadData = useCallback(async () => {
    if (!projectId) return
    try {
      const [proj, projItems, projNotes, projComments] = await Promise.all([
        api.projects.get(projectId),
        api.projects.items(projectId),
        api.projects.notes(projectId),
        api.projects.comments(projectId),
      ])
      setProject(proj)
      setItems(projItems)
      setNotes(projNotes)
      setComments(projComments)
      setError(null)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        navigate('/projects')
        return
      }
      setError(err instanceof ApiError ? err.detail : 'Failed to load project')
    } finally {
      setLoading(false)
    }
  }, [projectId, navigate])

  loadDataRef.current = loadData

  useEffect(() => {
    loadData()
  }, [loadData])

  // Refresh when items are captured via QuickCapture
  useEffect(() => {
    if (captureCount > 0) loadData()
  }, [captureCount]) // eslint-disable-line react-hooks/exhaustive-deps

  // Set active project for QuickCapture context
  useEffect(() => {
    if (project) {
      setActiveProject({ id: project.id, name: project.name })
    }
    return () => setActiveProject(null)
  }, [project, setActiveProject])

  // Re-fetch when relevant entities change via SSE
  useEffect(() => {
    const unsubs = [
      onEvent('item_created', () => { loadDataRef.current?.() }),
      onEvent('item_updated', () => { loadDataRef.current?.() }),
      onEvent('item_deleted', () => { loadDataRef.current?.() }),
      onEvent('note_created', () => { loadDataRef.current?.() }),
      onEvent('note_updated', () => { loadDataRef.current?.() }),
      onEvent('note_deleted', () => { loadDataRef.current?.() }),
      onEvent('project_updated', () => { loadDataRef.current?.() }),
      onEvent('project_deleted', () => { loadDataRef.current?.() }),
      onEvent('comment_created', () => { loadDataRef.current?.() }),
      onEvent('comment_updated', () => { loadDataRef.current?.() }),
      onEvent('comment_deleted', () => { loadDataRef.current?.() }),
    ]
    return () => { unsubs.forEach((u) => u()) }
  }, [onEvent])

  // Clear search when project changes
  useEffect(() => {
    setSearchQuery('')
  }, [projectId])

  const handleViewChange = (_: unknown, newView: 'list' | 'board' | null) => {
    if (!newView) return
    setItemView(newView)
    localStorage.setItem(`gtd_view_${projectId}`, newView)
  }

  const openCreateItemWithStatus = (status: ItemStatus) => {
    setEditingItem(null)
    setItemTitle('')
    setItemDescription('')
    setItemStatus(status)
    setItemPriority('normal')
    setItemDueDate('')
    setItemDialogOpen(true)
  }

  // --- Project edit ---
  const openEditProject = () => {
    if (!project) return
    setEditName(project.name)
    setEditDescription(project.description)
    setEditStatus(project.status)
    setEditArea(project.area)
    setEditGitOrigin(project.gitOrigin || '')
    setEditKbProjectRef(project.kbProjectRef || '')
    setEditProjectOpen(true)
  }

  const handleSaveProject = async () => {
    if (!projectId || !editName.trim()) return
    setSavingProject(true)
    try {
      await api.projects.update(projectId, {
        name: editName,
        description: editDescription,
        status: editStatus,
        area: editArea,
        gitOrigin: editGitOrigin,
        kbProjectRef: editKbProjectRef,
      })
      setEditProjectOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to update project')
    } finally {
      setSavingProject(false)
    }
  }

  // --- Items ---
  const openCreateItem = () => {
    setEditingItem(null)
    setItemTitle('')
    setItemDescription('')
    setItemStatus('next_action')
    setItemPriority('normal')
    setItemDueDate('')
    setItemDialogOpen(true)
  }

  const openEditItem = (item: Item) => {
    setEditingItem(item)
    setItemTitle(item.title)
    setItemDescription(item.description)
    setItemStatus(item.status)
    setItemPriority(item.priority)
    setItemDueDate(item.dueDate ?? '')
    setItemComments([])
    setNewItemComment('')
    setItemDialogOpen(true)
    api.items.comments(item.id).then(setItemComments).catch(() => {})
  }

  const handleSaveItem = async () => {
    if (!projectId || !itemTitle.trim()) return
    setSavingItem(true)
    try {
      if (editingItem) {
        await api.items.update(editingItem.id, {
          title: itemTitle,
          description: itemDescription,
          status: itemStatus,
          priority: itemPriority,
          dueDate: itemDueDate || null,
        })
      } else {
        await api.projects.createItem(projectId, {
          title: itemTitle,
          description: itemDescription,
          status: itemStatus,
          priority: itemPriority,
        })
      }
      setItemDialogOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to save item')
    } finally {
      setSavingItem(false)
    }
  }

  const handleDeleteItem = async () => {
    if (!deleteItemTarget) return
    setDeletingItem(true)
    try {
      await api.items.delete(deleteItemTarget.id)
      setDeleteItemTarget(null)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to delete item')
    } finally {
      setDeletingItem(false)
    }
  }

  const handleCompleteItem = async (item: Item) => {
    try {
      await api.items.update(item.id, { status: 'done' })
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to mark done')
    }
  }

  const visibleItems = showCompleted ? items : items.filter((i) => i.status !== 'done')

  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return visibleItems
    const q = searchQuery.toLowerCase()
    return visibleItems.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q),
    )
  }, [visibleItems, searchQuery])

  // --- Notes ---
  const openCreateNote = () => {
    setEditingNote(null)
    setNoteTitle('')
    setNoteContent('')
    setNoteDialogOpen(true)
  }

  const openEditNote = (note: Note) => {
    setEditingNote(note)
    setNoteTitle(note.title)
    setNoteContent(note.contentMarkdown)
    setNoteDialogOpen(true)
  }

  const handleSaveNote = async () => {
    if (!projectId) return
    setSavingNote(true)
    try {
      if (editingNote) {
        await api.notes.update(editingNote.id, {
          title: noteTitle,
          contentMarkdown: noteContent,
        })
      } else {
        await api.projects.createNote(projectId, {
          title: noteTitle,
          contentMarkdown: noteContent,
        })
      }
      setNoteDialogOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to save note')
    } finally {
      setSavingNote(false)
    }
  }

  const handleDeleteNote = async () => {
    if (!deleteNoteTarget) return
    setDeletingNote(true)
    try {
      await api.notes.delete(deleteNoteTarget.id)
      setDeleteNoteTarget(null)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to delete note')
    } finally {
      setDeletingNote(false)
    }
  }

  // --- Project comments ---
  const handleAddComment = async () => {
    if (!projectId || !newComment.trim()) return
    setSavingComment(true)
    try {
      await api.projects.createComment(projectId, { contentMarkdown: newComment })
      setNewComment('')
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to add comment')
    } finally {
      setSavingComment(false)
    }
  }

  const handleDeleteComment = async (commentId: string) => {
    try {
      await api.comments.delete(commentId)
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to delete comment')
    }
  }

  // --- Item comments ---
  const handleAddItemComment = async () => {
    if (!editingItem || !newItemComment.trim()) return
    setSavingItemComment(true)
    try {
      const created = await api.items.createComment(editingItem.id, { contentMarkdown: newItemComment })
      setItemComments((prev) => [...prev, created])
      setNewItemComment('')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to add comment')
    } finally {
      setSavingItemComment(false)
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (!project) return null

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <IconButton onClick={() => navigate('/projects')} size="small">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" sx={{ flex: 1 }}>
          {project.name}
        </Typography>
        <Chip
          label={STATUS_LABELS[project.status]}
          color={STATUS_COLORS[project.status]}
          size="small"
        />
        {project.area && (
          <Chip label={project.area} size="small" variant="outlined" />
        )}
        <Button size="small" startIcon={<EditIcon />} onClick={openEditProject}>
          Edit
        </Button>
      </Box>
      {project.description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2, ml: 5 }}>
          {project.description}
        </Typography>
      )}

      {/* Tabs */}
      <Tabs value={tab} onChange={(_, v: number) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label={`Items (${visibleItems.length})`} />
        <Tab label={`Notes (${notes.length})`} />
        <Tab label={`Comments (${comments.length})`} />
      </Tabs>

      {/* Items Tab */}
      {tab === 0 && (
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            {itemView === 'list' && (
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={showCompleted}
                    onChange={(e) => setShowCompleted(e.target.checked)}
                  />
                }
                label={<Typography variant="body2">Show completed</Typography>}
                sx={{ mr: 'auto' }}
              />
            )}
            {itemView !== 'list' && <Box sx={{ flex: 1 }} />}
            <ToggleButtonGroup
              size="small"
              value={itemView}
              exclusive
              onChange={handleViewChange}
            >
              <ToggleButton value="list">
                <ViewListIcon fontSize="small" />
              </ToggleButton>
              <ToggleButton value="board">
                <ViewKanbanIcon fontSize="small" />
              </ToggleButton>
            </ToggleButtonGroup>
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={openCreateItem}
            >
              Add Item
            </Button>
          </Box>

          {itemView === 'list' && (
            <TextField
              size="small"
              placeholder="Search items…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              sx={{ mb: 1, maxWidth: 400 }}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" color="action" />
                    </InputAdornment>
                  ),
                  endAdornment: searchQuery ? (
                    <InputAdornment position="end">
                      <IconButton
                        size="small"
                        onClick={() => setSearchQuery('')}
                        edge="end"
                        aria-label="Clear search"
                      >
                        <ClearIcon fontSize="small" />
                      </IconButton>
                    </InputAdornment>
                  ) : null,
                },
              }}
            />
          )}

          {itemView === 'board' ? (
            <KanbanBoard
              items={items}
              onRefresh={loadData}
              onEditItem={setDrawerItem}
              onDeleteItem={setDeleteItemTarget}
              onAddItem={openCreateItemWithStatus}
            />
          ) : filteredItems.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              {items.length === 0
                ? 'No items in this project yet.'
                : visibleItems.length === 0
                  ? 'All items are completed.'
                  : `No items match "${searchQuery}"`}
            </Typography>
          ) : (
            <List>
              {filteredItems.map((item) => (
                <ListItem
                  key={item.id}
                  onClick={() => setDrawerItem(item)}
                  secondaryAction={
                    <Box>
                      <IconButton size="small" onClick={(e) => { e.stopPropagation(); openEditItem(item) }}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      {item.status !== 'done' && (
                        <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleCompleteItem(item) }} title="Done">
                          <DoneIcon fontSize="small" />
                        </IconButton>
                      )}
                      <IconButton
                        size="small"
                        onClick={(e) => { e.stopPropagation(); setDeleteItemTarget(item) }}
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
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, overflow: 'hidden' }}>
                        <Typography
                          variant="body1"
                          sx={{
                            textDecoration: item.status === 'done' ? 'line-through' : 'none',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            minWidth: 0,
                          }}
                        >
                          {item.title}
                        </Typography>
                        <Chip
                          label={ITEM_STATUS_LABELS[item.status]}
                          size="small"
                          variant="outlined"
                        />
                        <Chip
                          label={item.priority}
                          size="small"
                          color={PRIORITY_COLORS[item.priority]}
                        />
                        {item.dueDate && (
                          <Chip
                            label={item.dueDate}
                            size="small"
                            variant="outlined"
                          />
                        )}
                      </Box>
                    }
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      )}

      {/* Notes Tab */}
      {tab === 1 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={openCreateNote}
            >
              Add Note
            </Button>
          </Box>
          {notes.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              No notes in this project yet.
            </Typography>
          ) : (
            <List>
              {notes.map((note) => (
                <ListItem
                  key={note.id}
                  secondaryAction={
                    <Box>
                      <IconButton size="small" onClick={() => openEditNote(note)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => setDeleteNoteTarget(note)}
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
                    primary={note.title || 'Untitled'}
                    secondary={
                      note.contentMarkdown
                        ? note.contentMarkdown.slice(0, 100) +
                          (note.contentMarkdown.length > 100 ? '...' : '')
                        : 'No content'
                    }
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      )}

      {/* Comments Tab */}
      {tab === 2 && (
        <Box>
          {comments.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              No comments on this project yet.
            </Typography>
          ) : (
            <List>
              {comments.map((comment) => (
                <ListItem
                  key={comment.id}
                  secondaryAction={
                    <IconButton
                      size="small"
                      onClick={() => handleDeleteComment(comment.id)}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  }
                  sx={{
                    border: 1,
                    borderColor: 'divider',
                    borderRadius: 1,
                    mb: 1,
                  }}
                >
                  <ListItemText
                    primary={comment.contentMarkdown}
                    secondary={
                      <Box component="span" sx={{ display: 'flex', gap: 1, mt: 0.5, alignItems: 'center' }}>
                        <Chip label={comment.createdBy} size="small" variant="outlined" />
                        <Typography variant="caption" color="text.secondary">
                          {new Date(comment.createdAt).toLocaleString()}
                        </Typography>
                      </Box>
                    }
                  />
                </ListItem>
              ))}
            </List>
          )}
          <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
            <TextField
              fullWidth
              size="small"
              placeholder="Add a comment..."
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  if (newComment.trim() && !savingComment) handleAddComment()
                }
              }}
              multiline
              maxRows={4}
            />
            <IconButton
              color="primary"
              onClick={handleAddComment}
              disabled={savingComment || !newComment.trim()}
            >
              {savingComment ? <CircularProgress size={20} /> : <SendIcon />}
            </IconButton>
          </Box>
        </Box>
      )}

      {/* Edit Project Dialog */}
      <Dialog
        open={editProjectOpen}
        onClose={() => setEditProjectOpen(false)}
        fullWidth
        maxWidth="sm"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && ((e.metaKey || e.ctrlKey) || !(e.target instanceof HTMLTextAreaElement))) {
            e.preventDefault()
            if (editName.trim() && !savingProject) handleSaveProject()
          }
        }}
      >
        <DialogTitle>Edit Project</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Name"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
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
              onChange={(e) => setEditStatus(e.target.value as ProjectStatus)}
              label="Status"
            >
              <MenuItem value="active">Active</MenuItem>
              <MenuItem value="completed">Completed</MenuItem>
              <MenuItem value="on_hold">On Hold</MenuItem>
              <MenuItem value="cancelled">Cancelled</MenuItem>
            </Select>
          </FormControl>
          <TextField
            fullWidth
            label="Area"
            value={editArea}
            onChange={(e) => setEditArea(e.target.value)}
            margin="normal"
            size="small"
          />
          <TextField
            fullWidth
            label="Git Origin"
            value={editGitOrigin}
            onChange={(e) => setEditGitOrigin(e.target.value)}
            margin="normal"
            size="small"
            placeholder="e.g. git@github.com:org/repo.git"
            helperText="Repository URL for agent dispatch"
          />
          <TextField
            fullWidth
            label="KB Project Ref"
            value={editKbProjectRef}
            onChange={(e) => setEditKbProjectRef(e.target.value)}
            margin="normal"
            size="small"
            placeholder="e.g. my-project"
            helperText="Personal KB project reference for agent context"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditProjectOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSaveProject}
            disabled={savingProject || !editName.trim()}
          >
            {savingProject ? <CircularProgress size={20} /> : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Item Dialog */}
      <Dialog
        open={itemDialogOpen}
        onClose={() => setItemDialogOpen(false)}
        fullWidth
        maxWidth="sm"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && ((e.metaKey || e.ctrlKey) || !(e.target instanceof HTMLTextAreaElement))) {
            e.preventDefault()
            if (itemTitle.trim() && !savingItem) handleSaveItem()
          }
        }}
      >
        <DialogTitle>{editingItem ? 'Edit Item' : 'New Item'}</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Title"
            value={itemTitle}
            onChange={(e) => setItemTitle(e.target.value)}
            margin="normal"
            autoFocus
            size="small"
            required
          />
          <TextField
            fullWidth
            label="Description"
            value={itemDescription}
            onChange={(e) => setItemDescription(e.target.value)}
            margin="normal"
            multiline
            rows={3}
            size="small"
          />
          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Status</InputLabel>
            <Select
              value={itemStatus}
              onChange={(e) => setItemStatus(e.target.value as ItemStatus)}
              label="Status"
            >
              <MenuItem value="next_action">To Do</MenuItem>
              <MenuItem value="active">In Progress</MenuItem>
              <MenuItem value="waiting_for">Waiting</MenuItem>
              <MenuItem value="someday_maybe">Someday</MenuItem>
              <MenuItem value="done">Done</MenuItem>
            </Select>
          </FormControl>
          <FormControl fullWidth margin="normal" size="small">
            <InputLabel>Priority</InputLabel>
            <Select
              value={itemPriority}
              onChange={(e) => setItemPriority(e.target.value as Priority)}
              label="Priority"
            >
              <MenuItem value="low">Low</MenuItem>
              <MenuItem value="normal">Normal</MenuItem>
              <MenuItem value="high">High</MenuItem>
              <MenuItem value="urgent">Urgent</MenuItem>
            </Select>
          </FormControl>
          <TextField
            fullWidth
            label="Due Date"
            value={itemDueDate}
            onChange={(e) => setItemDueDate(e.target.value)}
            margin="normal"
            size="small"
            type="date"
            slotProps={{ inputLabel: { shrink: true } }}
          />
          {editingItem && (
            <>
              <Divider sx={{ my: 2 }} />
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Comments ({itemComments.length})
              </Typography>
              {itemComments.length > 0 && (
                <List dense sx={{ mb: 1 }}>
                  {itemComments.map((c) => (
                    <ListItem key={c.id} sx={{ px: 0 }}>
                      <ListItemText
                        primary={c.contentMarkdown}
                        secondary={
                          <Box component="span" sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                            <Chip label={c.createdBy} size="small" variant="outlined" />
                            <Typography variant="caption" color="text.secondary">
                              {new Date(c.createdAt).toLocaleString()}
                            </Typography>
                          </Box>
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              )}
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField
                  fullWidth
                  size="small"
                  placeholder="Add a comment..."
                  value={newItemComment}
                  onChange={(e) => setNewItemComment(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      if (newItemComment.trim() && !savingItemComment) handleAddItemComment()
                    }
                  }}
                />
                <IconButton
                  color="primary"
                  onClick={handleAddItemComment}
                  disabled={savingItemComment || !newItemComment.trim()}
                  size="small"
                >
                  {savingItemComment ? <CircularProgress size={16} /> : <SendIcon fontSize="small" />}
                </IconButton>
              </Box>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setItemDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSaveItem}
            disabled={savingItem || !itemTitle.trim()}
          >
            {savingItem ? <CircularProgress size={20} /> : editingItem ? 'Save' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Note Dialog */}
      <Dialog
        open={noteDialogOpen}
        onClose={() => setNoteDialogOpen(false)}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>{editingNote ? 'Edit Note' : 'New Note'}</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Title"
            value={noteTitle}
            onChange={(e) => setNoteTitle(e.target.value)}
            margin="normal"
            autoFocus
            size="small"
          />
          <NoteEditor content={noteContent} onChange={setNoteContent} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNoteDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSaveNote}
            disabled={savingNote}
          >
            {savingNote ? <CircularProgress size={20} /> : editingNote ? 'Save' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Item Confirmation */}
      <Dialog
        open={Boolean(deleteItemTarget)}
        onClose={() => setDeleteItemTarget(null)}
      >
        <DialogTitle>Delete Item</DialogTitle>
        <DialogContent>
          <Typography>
            Delete &ldquo;{deleteItemTarget?.title}&rdquo;?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteItemTarget(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDeleteItem}
            disabled={deletingItem}
          >
            {deletingItem ? <CircularProgress size={20} /> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Note Confirmation */}
      <Dialog
        open={Boolean(deleteNoteTarget)}
        onClose={() => setDeleteNoteTarget(null)}
      >
        <DialogTitle>Delete Note</DialogTitle>
        <DialogContent>
          <Typography>
            Delete &ldquo;{deleteNoteTarget?.title || 'Untitled'}&rdquo;?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteNoteTarget(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDeleteNote}
            disabled={deletingNote}
          >
            {deletingNote ? <CircularProgress size={20} /> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Item Detail Drawer */}
      <ItemDetailDrawer
        item={drawerItem}
        onClose={() => setDrawerItem(null)}
        onEdit={(item) => { setDrawerItem(null); openEditItem(item) }}
        onItemUpdated={(updated) => {
          setDrawerItem(updated)
          setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        }}
        projectName={project.name}
        projectGitOrigin={project.gitOrigin}
      />
    </Box>
  )
}
