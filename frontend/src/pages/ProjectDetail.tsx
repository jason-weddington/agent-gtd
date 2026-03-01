import { useState, useEffect, useCallback } from 'react'
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
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { api, ApiError } from '../api'
import type { Project, Item, Note, ItemStatus, Priority, ProjectStatus } from '../types'

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

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const [project, setProject] = useState<Project | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState(0)

  // Project edit dialog
  const [editProjectOpen, setEditProjectOpen] = useState(false)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editStatus, setEditStatus] = useState<ProjectStatus>('active')
  const [editArea, setEditArea] = useState('')
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

  // Delete confirmation
  const [deleteItemTarget, setDeleteItemTarget] = useState<Item | null>(null)
  const [deleteNoteTarget, setDeleteNoteTarget] = useState<Note | null>(null)
  const [deletingItem, setDeletingItem] = useState(false)
  const [deletingNote, setDeletingNote] = useState(false)

  const loadData = useCallback(async () => {
    if (!projectId) return
    try {
      const [proj, projItems, projNotes] = await Promise.all([
        api.projects.get(projectId),
        api.projects.items(projectId),
        api.projects.notes(projectId),
      ])
      setProject(proj)
      setItems(projItems)
      setNotes(projNotes)
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

  useEffect(() => {
    loadData()
  }, [loadData])

  // --- Project edit ---
  const openEditProject = () => {
    if (!project) return
    setEditName(project.name)
    setEditDescription(project.description)
    setEditStatus(project.status)
    setEditArea(project.area)
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
    setItemStatus('active')
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
    setItemDialogOpen(true)
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
        <Tab label={`Items (${items.length})`} />
        <Tab label={`Notes (${notes.length})`} />
      </Tabs>

      {/* Items Tab */}
      {tab === 0 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={openCreateItem}
            >
              Add Item
            </Button>
          </Box>
          {items.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              No items in this project yet.
            </Typography>
          ) : (
            <List>
              {items.map((item) => (
                <ListItem
                  key={item.id}
                  secondaryAction={
                    <Box>
                      <IconButton size="small" onClick={() => openEditItem(item)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => setDeleteItemTarget(item)}
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
                        <Typography
                          variant="body1"
                          sx={{
                            textDecoration: item.status === 'done' ? 'line-through' : 'none',
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

      {/* Edit Project Dialog */}
      <Dialog
        open={editProjectOpen}
        onClose={() => setEditProjectOpen(false)}
        fullWidth
        maxWidth="sm"
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
              <MenuItem value="inbox">Inbox</MenuItem>
              <MenuItem value="next_action">Next Action</MenuItem>
              <MenuItem value="waiting_for">Waiting For</MenuItem>
              <MenuItem value="scheduled">Scheduled</MenuItem>
              <MenuItem value="someday_maybe">Someday/Maybe</MenuItem>
              <MenuItem value="active">Active</MenuItem>
              <MenuItem value="done">Done</MenuItem>
              <MenuItem value="cancelled">Cancelled</MenuItem>
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
        maxWidth="sm"
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
          <TextField
            fullWidth
            label="Content"
            value={noteContent}
            onChange={(e) => setNoteContent(e.target.value)}
            margin="normal"
            multiline
            rows={8}
            size="small"
          />
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
    </Box>
  )
}
