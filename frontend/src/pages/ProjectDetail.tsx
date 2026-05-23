import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputAdornment,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
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
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'
import HistoryToggleOffIcon from '@mui/icons-material/HistoryToggleOff'
import { api, ApiError } from '../api'
import type { Project, Item, Note, Comment, ItemStatus, Priority, ProjectStatus, DispatchAgentInfo } from '../types'
import { useDraftState } from '../hooks/useDraftState'
import { PRIORITY_BORDER } from '../priorityColors'
import { useEvents } from '../contexts/EventStreamContext'
import { useQuickCapture } from '../contexts/QuickCaptureContext'
import KanbanBoard from '../components/KanbanBoard'
import NoteEditor from '../components/NoteEditor'
import ItemDetailDrawer from '../components/ItemDetailDrawer'
import ShareTab from '../components/ShareTab'
import MarkdownContent from '../components/MarkdownContent'
import ProjectEditDialog from '../components/ProjectEditDialog'
import RolloutBanner from '../components/RolloutBanner'
import ActivityDrawer, { type Scope } from '../components/ActivityDrawer'

// Local extension of Item for optimistic UI — never exported or added to types.ts
type DisplayItem = Item & { _optimistic?: true }

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

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [project, setProject] = useState<Project | null>(null)
  const [items, setItems] = useState<DisplayItem[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [comments, setComments] = useState<Comment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState(() => {
    // Support ?tab=share deep link
    const params = new URLSearchParams(window.location.search)
    return params.get('tab') === 'share' ? 4 : 0
  })

  // Activity drawer state
  const [activityDrawerOpen, setActivityDrawerOpen] = useState(false)
  const [activeRolloutId, setActiveRolloutId] = useState<string | null>(null)
  const [activityDrawerScope, setActivityDrawerScope] = useState<Scope>('project')

  // Copy project ID
  const [copied, setCopied] = useState(false)
  const handleCopy = useCallback(() => {
    if (!project) return
    void navigator.clipboard.writeText(project.id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [project])

  // Open activity drawer with rollout tab selected.
  // The existing drawer-open pattern is implemented by the header IconButton
  // which calls setActivityDrawerOpen(true) directly. This callback both opens
  // the drawer and sets the active tab to 'rollout' when the CTA is clicked.
  const handleOpenActivityDrawer = useCallback(() => {
    setActivityDrawerOpen(true)
    setActivityDrawerScope('rollout')
  }, [])

  // Project comment input
  const [newComment, setNewComment] = useState('')
  const [savingComment, setSavingComment] = useState(false)

  // Item comments (loaded when editing)
  const [itemComments, setItemComments] = useState<Comment[]>([])
  const [newItemComment, setNewItemComment] = useState('')
  const [savingItemComment, setSavingItemComment] = useState(false)

  // Project edit dialog
  const [editDialogOpen, setEditDialogOpen] = useState(false)

  // Item dialog
  const [itemDialogOpen, setItemDialogOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<Item | null>(null)

  // Draft state for the NEW ITEM path — persisted to localStorage so an
  // accidental dismiss (backdrop / Escape) never loses what the user typed.
  // Cleared explicitly on successful create or deliberate Cancel click.
  interface ItemDraft {
    title: string
    description: string
    status: ItemStatus
    priority: Priority
    dueDate: string
  }
  const ITEM_DRAFT_INITIAL: ItemDraft = {
    title: '',
    description: '',
    status: 'new',
    priority: 'normal',
    dueDate: '',
  }
  const [itemDraft, setItemDraft, clearItemDraft] = useDraftState<ItemDraft>(
    projectId
      ? `agent-gtd:draft:project-new-item:${projectId}`
      : 'agent-gtd:draft:project-new-item:_',
    ITEM_DRAFT_INITIAL,
  )

  // Edit-path form state — plain useState, not persisted (server is source of truth).
  const [editFormData, setEditFormData] = useState<ItemDraft>(ITEM_DRAFT_INITIAL)

  // Unified read-only form values — callers use these regardless of create/edit mode.
  const itemTitle = editingItem ? editFormData.title : itemDraft.title
  const itemDescription = editingItem ? editFormData.description : itemDraft.description
  const itemStatus = editingItem ? editFormData.status : itemDraft.status
  const itemPriority = editingItem ? editFormData.priority : itemDraft.priority
  const itemDueDate = editingItem ? editFormData.dueDate : itemDraft.dueDate

  // Unified setters — route writes to the appropriate backing state.
  const setItemTitle = (v: string) => {
    if (editingItem) setEditFormData((s) => ({ ...s, title: v }))
    else setItemDraft((s) => ({ ...s, title: v }))
  }
  const setItemDescription = (v: string) => {
    if (editingItem) setEditFormData((s) => ({ ...s, description: v }))
    else setItemDraft((s) => ({ ...s, description: v }))
  }
  const setItemStatus = (v: ItemStatus) => {
    if (editingItem) setEditFormData((s) => ({ ...s, status: v }))
    else setItemDraft((s) => ({ ...s, status: v }))
  }
  const setItemPriority = (v: Priority) => {
    if (editingItem) setEditFormData((s) => ({ ...s, priority: v }))
    else setItemDraft((s) => ({ ...s, priority: v }))
  }
  const setItemDueDate = (v: string) => {
    if (editingItem) setEditFormData((s) => ({ ...s, dueDate: v }))
    else setItemDraft((s) => ({ ...s, dueDate: v }))
  }

  const [itemProjectId, setItemProjectId] = useState<string>('')
  const [savingItem, setSavingItem] = useState(false)

  // Active projects for project selector
  const [allProjects, setAllProjects] = useState<Project[]>([])

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
  const [selectedLabels, setSelectedLabels] = useState<string[]>([])
  const [labelFilterMode, setLabelFilterMode] = useState<'and' | 'or'>('or')

  // Delete confirmation
  const [deleteItemTarget, setDeleteItemTarget] = useState<Item | null>(null)
  const [deleteNoteTarget, setDeleteNoteTarget] = useState<Note | null>(null)
  const [deletingItem, setDeletingItem] = useState(false)
  const [deletingNote, setDeletingNote] = useState(false)

  // Wave banner / dispatch guard state (AC-19, AC-20)
  const [hasActiveWave, setHasActiveWave] = useState(false)

  // Dispatch tab state
  const [dispatchGlobalSettings, setDispatchGlobalSettings] = useState<{
    planAgentName: string
    buildAgentName: string
    defaultMaxTurns: number
    defaultTimeoutMinutes: number
  } | null>(null)
  const [dispatchCapabilities, setDispatchCapabilities] = useState<DispatchAgentInfo[] | null>(null)
  const [dispatchCapabilitiesError, setDispatchCapabilitiesError] = useState<'unavailable' | 'empty' | null>(null)
  const [localPlanDispatchAgent, setLocalPlanDispatchAgent] = useState<string | null>(null)
  const [localBuildDispatchAgent, setLocalBuildDispatchAgent] = useState<string | null>(null)
  const [localDispatchMaxTurnsStr, setLocalDispatchMaxTurnsStr] = useState<string>('')
  const [localDispatchTimeoutMinutesStr, setLocalDispatchTimeoutMinutesStr] = useState<string>('')
  const [savingDispatch, setSavingDispatch] = useState(false)
  const [dispatchSaved, setDispatchSaved] = useState(false)
  const [dispatchSaveError, setDispatchSaveError] = useState<string | null>(null)

  const { onEvent } = useEvents()
  const { setActiveProject, captureCount } = useQuickCapture()
  const loadDataRef = useRef<() => Promise<void>>(undefined)
  // Mirror of items state for use in SSE callbacks (avoids stale closure).
  const itemsRef = useRef<DisplayItem[]>([])

  const loadData = useCallback(async () => {
    if (!projectId) return
    try {
      const [proj, projItems, projNotes, projComments, activeProjects] = await Promise.all([
        api.projects.get(projectId),
        api.projects.items(projectId),
        api.projects.notes(projectId),
        api.projects.comments(projectId),
        api.projects.list({ status: 'active' }),
      ])
      setProject(proj)
      setItems(projItems)
      setNotes(projNotes)
      setComments(projComments)
      setAllProjects(activeProjects)
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
  itemsRef.current = items

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
      onEvent('item_created', (event) => {
        // Skip the refetch if the real item is already in local state
        // (optimistic swap already happened when the POST returned).
        if (itemsRef.current.some((i) => i.id === event.entityId)) return
        loadDataRef.current?.()
      }),
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
      onEvent('run_started', () => { loadDataRef.current?.() }),
      onEvent('run_completed', () => { loadDataRef.current?.() }),
      onEvent('run_failed', () => { loadDataRef.current?.() }),
    ]
    return () => { unsubs.forEach((u) => u()) }
  }, [onEvent])

  // Clear search and label filter when project changes
  useEffect(() => {
    setSearchQuery('')
    setSelectedLabels([])
    setLabelFilterMode('or')
  }, [projectId])

  // Load global dispatch settings once (for "inherit" defaults and effective values)
  useEffect(() => {
    api.settings.getDispatch()
      .then((res) => setDispatchGlobalSettings({
        planAgentName: res.planAgentName,
        buildAgentName: res.buildAgentName,
        defaultMaxTurns: res.defaultMaxTurns,
        defaultTimeoutMinutes: res.defaultTimeoutMinutes,
      }))
      .catch(() => { /* non-critical: dispatch tab will show no effective values */ })
  }, [])

  // Load dispatch agent capabilities once
  useEffect(() => {
    api.dispatch.capabilities()
      .then((caps) => {
        if (caps.agents.length === 0) {
          setDispatchCapabilitiesError('empty')
        } else {
          setDispatchCapabilities(caps.agents)
        }
      })
      .catch(() => {
        setDispatchCapabilitiesError('unavailable')
      })
  }, [])

  // Sync dispatch form local state when project loads or reloads
  useEffect(() => {
    if (project) {
      setLocalPlanDispatchAgent(project.planDispatchAgent ?? null)
      setLocalBuildDispatchAgent(project.buildDispatchAgent ?? null)
      setLocalDispatchMaxTurnsStr(project.dispatchMaxTurns?.toString() ?? '')
      setLocalDispatchTimeoutMinutesStr(project.dispatchTimeoutMinutes?.toString() ?? '')
    }
  }, [project])

  // Open item drawer when navigating here with ?item=<id> query param
  useEffect(() => {
    const itemId = searchParams.get('item')
    if (itemId && items.length > 0) {
      const item = items.find((i) => i.id === itemId)
      if (item) {
        setDrawerItem(item)
        searchParams.delete('item')
        setSearchParams(searchParams, { replace: true })
      }
    }
  }, [searchParams, items, setDrawerItem, setSearchParams])

  const handleViewChange = (_: unknown, newView: 'list' | 'board' | null) => {
    if (!newView) return
    setItemView(newView)
    localStorage.setItem(`gtd_view_${projectId}`, newView)
  }

  const openCreateItemWithStatus = (status: ItemStatus) => {
    setEditingItem(null)
    // Start fresh with the requested status (Kanban column "+" button).
    setItemDraft({ ...ITEM_DRAFT_INITIAL, status })
    setItemDialogOpen(true)
  }

  // --- Items ---
  const openCreateItem = () => {
    setEditingItem(null)
    // Don't reset itemDraft here — let it restore from localStorage so an
    // accidental previous dismiss doesn't lose what the user was typing.
    setItemDialogOpen(true)
  }

  const openEditItem = (item: Item) => {
    setEditingItem(item)
    setEditFormData({
      title: item.title,
      description: item.description,
      status: item.status,
      priority: item.priority,
      dueDate: item.dueDate ?? '',
    })
    setItemProjectId(item.projectId ?? projectId ?? '')
    setItemComments([])
    setNewItemComment('')
    setItemDialogOpen(true)
    api.items.comments(item.id).then(setItemComments).catch(() => {})
  }

  const handleSaveItem = async () => {
    if (!projectId || !itemTitle.trim()) return
    setSavingItem(true)

    if (editingItem) {
      // Edit path: synchronous UX — dialog stays open until save completes.
      try {
        await api.items.update(editingItem.id, {
          title: itemTitle,
          description: itemDescription,
          status: itemStatus,
          priority: itemPriority,
          dueDate: itemDueDate || null,
          projectId: itemProjectId || null,
        })
        setItemDialogOpen(false)
        await loadData()
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : 'Failed to save item')
      } finally {
        setSavingItem(false)
      }
      return
    }

    // Create path: optimistic UX — insert immediately, close dialog, then POST.
    const tempId = crypto.randomUUID()
    const now = new Date().toISOString()
    const optimisticItem: DisplayItem = {
      id: tempId,
      projectId,
      title: itemTitle,
      description: itemDescription,
      status: itemStatus,
      priority: itemPriority,
      dueDate: itemDueDate || null,
      completedAt: null,
      createdBy: 'human',
      assignedTo: '',
      waitingOn: '',
      sortOrder: 0,
      labels: [],
      blockers: [],
      lockedByRolloutId: null,
      buildEngine: null,
      acceptanceCriteria: [],
      filesToModify: [],
      scopeOut: [],
      version: 0,
      createdAt: now,
      updatedAt: now,
      _optimistic: true,
    }

    setItems((prev) => [optimisticItem, ...prev])
    setItemDialogOpen(false)
    setSavingItem(false)

    try {
      const realItem = await api.projects.createItem(projectId, {
        title: itemTitle,
        description: itemDescription,
        status: itemStatus,
        priority: itemPriority,
      })
      // Swap optimistic placeholder for the real item from the server.
      setItems((prev) => prev.map((i) => (i.id === tempId ? (realItem as DisplayItem) : i)))
      clearItemDraft()
    } catch (err) {
      // Roll back: remove the optimistic item and re-open the dialog for retry.
      setItems((prev) => prev.filter((i) => i.id !== tempId))
      setItemDialogOpen(true)
      setError(err instanceof ApiError ? err.detail : 'Failed to create item')
    }
  }

  const handleSaveAndPlan = async () => {
    if (!projectId || !itemTitle.trim() || !project?.gitOrigin) return
    setSavingItem(true)

    // Optimistic create — identical to the Create path in handleSaveItem
    const tempId = crypto.randomUUID()
    const now = new Date().toISOString()
    const optimisticItem: DisplayItem = {
      id: tempId,
      projectId,
      title: itemTitle,
      description: itemDescription,
      status: itemStatus,
      priority: itemPriority,
      dueDate: itemDueDate || null,
      completedAt: null,
      createdBy: 'human',
      assignedTo: '',
      waitingOn: '',
      sortOrder: 0,
      labels: [],
      blockers: [],
      lockedByRolloutId: null,
      buildEngine: null,
      acceptanceCriteria: [],
      filesToModify: [],
      scopeOut: [],
      version: 0,
      createdAt: now,
      updatedAt: now,
      _optimistic: true,
    }

    setItems((prev) => [optimisticItem, ...prev])
    setItemDialogOpen(false)
    setSavingItem(false)

    try {
      const realItem = await api.projects.createItem(projectId, {
        title: itemTitle,
        description: itemDescription,
        status: itemStatus,
        priority: itemPriority,
      })
      setItems((prev) => prev.map((i) => (i.id === tempId ? (realItem as DisplayItem) : i)))
      clearItemDraft()

      // Dispatch the saved item in plan mode
      try {
        await api.items.dispatch(realItem.id, { mode: 'plan' })
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : 'Dispatch failed')
      }
    } catch (err) {
      // Roll back optimistic item, re-open dialog for retry
      setItems((prev) => prev.filter((i) => i.id !== tempId))
      setItemDialogOpen(true)
      setError(err instanceof ApiError ? err.detail : 'Failed to create item')
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

  const allLabels = useMemo(() => {
    const labelSet = new Set<string>()
    for (const item of visibleItems) {
      for (const label of item.labels) {
        labelSet.add(label)
      }
    }
    return Array.from(labelSet).sort()
  }, [visibleItems])

  const filteredItems = useMemo(() => {
    let result = visibleItems
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (item) =>
          item.title.toLowerCase().includes(q) ||
          item.description.toLowerCase().includes(q),
      )
    }
    if (selectedLabels.length > 0) {
      result = result.filter((item) =>
        labelFilterMode === 'and'
          ? selectedLabels.every((label) => item.labels.includes(label))
          : selectedLabels.some((label) => item.labels.includes(label)),
      )
    }
    return result
  }, [visibleItems, searchQuery, selectedLabels, labelFilterMode])

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

  // --- Dispatch tab ---
  const handleSaveDispatch = async () => {
    if (!projectId) return

    let maxTurns: number | null = null
    if (localDispatchMaxTurnsStr !== '') {
      const val = parseInt(localDispatchMaxTurnsStr, 10)
      if (isNaN(val) || val < 10 || val > 500) {
        setDispatchSaveError('Max turns must be between 10 and 500')
        return
      }
      maxTurns = val
    }

    let timeoutMinutes: number | null = null
    if (localDispatchTimeoutMinutesStr !== '') {
      const val = parseInt(localDispatchTimeoutMinutesStr, 10)
      if (isNaN(val) || val < 5 || val > 480) {
        setDispatchSaveError('Dispatch timeout must be between 5 and 480 minutes')
        return
      }
      timeoutMinutes = val
    }

    setSavingDispatch(true)
    setDispatchSaveError(null)
    setDispatchSaved(false)
    try {
      const updated = await api.projects.update(projectId, {
        planDispatchAgent: localPlanDispatchAgent,
        buildDispatchAgent: localBuildDispatchAgent,
        dispatchMaxTurns: maxTurns,
        dispatchTimeoutMinutes: timeoutMinutes,
      })
      setProject(updated)
      setLocalPlanDispatchAgent(updated.planDispatchAgent ?? null)
      setLocalBuildDispatchAgent(updated.buildDispatchAgent ?? null)
      setLocalDispatchMaxTurnsStr(updated.dispatchMaxTurns?.toString() ?? '')
      setLocalDispatchTimeoutMinutesStr(updated.dispatchTimeoutMinutes?.toString() ?? '')
      setDispatchSaved(true)
      setTimeout(() => setDispatchSaved(false), 3000)
    } catch (err) {
      setDispatchSaveError(err instanceof ApiError ? err.detail : 'Failed to save dispatch settings')
    } finally {
      setSavingDispatch(false)
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
        <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>
          ({project.totalItems} items)
        </Typography>
        <Chip
          label={STATUS_LABELS[project.status]}
          color={STATUS_COLORS[project.status]}
          size="small"
        />
        {project.area && (
          <Chip label={project.area} size="small" variant="outlined" />
        )}
        <Button size="small" startIcon={<EditIcon />} onClick={() => setEditDialogOpen(true)}>
          Edit
        </Button>
        <Tooltip title="Activity">
          <IconButton
            size="small"
            onClick={() => setActivityDrawerOpen(true)}
            aria-label="Open activity drawer"
          >
            <HistoryToggleOffIcon />
          </IconButton>
        </Tooltip>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, ml: 5 }}>
        <Typography variant="caption" color="text.disabled" sx={{ mr: 0.5 }}>
          #{project.id.slice(0, 8)}
        </Typography>
        <Tooltip title={copied ? 'Copied!' : 'Copy project ID'} placement="right">
          <IconButton
            size="small"
            onClick={handleCopy}
            sx={{ p: 0.25, flexShrink: 0 }}
            aria-label="Copy project ID"
          >
            {copied ? (
              <CheckIcon sx={{ fontSize: 14, color: 'success.main' }} />
            ) : (
              <ContentCopyIcon sx={{ fontSize: 14 }} />
            )}
          </IconButton>
        </Tooltip>
        {project.description && (
          <Typography variant="body2" color="text.secondary" sx={{ ml: 0.5 }}>
            {project.description}
          </Typography>
        )}
      </Box>

      {/* Wave banner (AC-1 through AC-21) — above items list / Kanban view */}
      {projectId && (
        <RolloutBanner
          projectId={projectId}
          onActiveChange={setHasActiveWave}
          onRolloutIdChange={setActiveRolloutId}
          onOpenActivityDrawer={handleOpenActivityDrawer}
        />
      )}

      {/* Tabs */}
      <Tabs
          value={tab}
          onChange={(_, v: number) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
          sx={{ mb: 2 }}
        >
        <Tab label={`Items (${visibleItems.length})`} />
        <Tab label={`Notes (${notes.length})`} />
        <Tab label={`Comments (${comments.length})`} />
        <Tab label="Dispatch" />
        <Tab label="Share" />
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
            <>
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
              {allLabels.length > 0 && (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 1, alignItems: 'center' }}>
                  <ToggleButtonGroup
                    size="small"
                    value={labelFilterMode}
                    exclusive
                    onChange={(_: unknown, newMode: 'and' | 'or' | null) => {
                      if (!newMode) return
                      setLabelFilterMode(newMode)
                    }}
                  >
                    <ToggleButton value="or">OR</ToggleButton>
                    <ToggleButton value="and">AND</ToggleButton>
                  </ToggleButtonGroup>
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
            </>
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
                  : selectedLabels.length > 0 && !searchQuery.trim()
                    ? 'No items match the selected labels.'
                    : `No items match \u201c${searchQuery}\u201d`}
            </Typography>
          ) : (
            <List>
              {filteredItems.map((item) => (
                <ListItem
                  key={item.id}
                  onClick={() => { if (!item._optimistic) setDrawerItem(item) }}
                  secondaryAction={
                    item._optimistic ? null : (
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
                    )
                  }
                  sx={{
                    border: 1,
                    borderColor: 'divider',
                    borderLeft: `3px solid ${PRIORITY_BORDER[item.priority]}`,
                    borderRadius: 1,
                    mb: 1,
                    cursor: item._optimistic ? 'default' : 'pointer',
                    opacity: item._optimistic ? 0.6 : 1,
                    '&:hover': { bgcolor: item._optimistic ? undefined : 'action.hover' },
                  }}
                >
                  <ListItemText
                    primary={
                      <Box>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, overflow: 'hidden' }}>
                          <Typography
                            variant="body1"
                            sx={{
                              textDecoration: item.status === 'done' ? 'line-through' : 'none',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              minWidth: 0,
                              flex: 1,
                              fontStyle: item._optimistic ? 'italic' : undefined,
                            }}
                          >
                            {item.title}
                          </Typography>
                          {item._optimistic && (
                            <CircularProgress size={12} sx={{ flexShrink: 0 }} />
                          )}
                          {!item._optimistic && ((project.memberCount ?? 0) > 0 || project.isOwner === false) && item.createdBy && item.createdBy !== 'human' && (
                            <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>
                              by {item.createdBy}
                            </Typography>
                          )}
                        </Box>
                        <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
                          <Chip
                            label={ITEM_STATUS_LABELS[item.status]}
                            size="small"
                            variant="outlined"
                          />
                          {item.dueDate && (
                            <Chip
                              label={item.dueDate}
                              size="small"
                              variant="outlined"
                            />
                          )}
                        </Box>
                        {item.labels.length > 0 && (
                          <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
                            {item.labels.map((label) => (
                              <Chip
                                key={label}
                                label={label}
                                size="small"
                                color={selectedLabels.includes(label) ? 'primary' : 'default'}
                                variant={selectedLabels.includes(label) ? 'filled' : 'outlined'}
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
                          </Box>
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
                    primary={<MarkdownContent>{comment.contentMarkdown}</MarkdownContent>}
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

      {/* Share Tab */}
      {tab === 4 && (
        <ShareTab
          projectId={project.id}
          isOwner={project.isOwner !== false}
          ownerEmail={project.ownerEmail}
        />
      )}

      {/* Dispatch Tab */}
      {tab === 3 && (
        <Box sx={{ maxWidth: 560 }}>
          {project.isOwner === false ? (
            <Alert severity="info">
              Dispatch settings are managed by the project owner.
            </Alert>
          ) : (
          <>
          {/* AC-19: guard when wave is active */}
          {hasActiveWave && (
            <Alert severity="info" sx={{ mb: 2 }}>
              Dispatch settings cannot be changed while an autonomous wave is active.
            </Alert>
          )}
          <Card sx={{ border: 1, borderColor: 'divider' }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 600 }}>
                Dispatch Overrides
              </Typography>
              <Divider sx={{ my: 1 }} />

              {/* Plan Agent field */}
              {(() => {
                const capabilityNames = dispatchCapabilities?.map((a) => a.name) ?? []
                const capabilitiesHelperText = dispatchCapabilitiesError === 'unavailable'
                  ? 'Dispatch service unavailable'
                  : dispatchCapabilitiesError === 'empty'
                    ? 'No agents advertised'
                    : null

                const renderDispatchOption = (
                  props: React.HTMLAttributes<HTMLLIElement> & { key?: React.Key },
                  option: string | null,
                  globalLabel: string,
                ) => {
                  const { key, ...rest } = props
                  const agentInfo = option ? dispatchCapabilities?.find((a) => a.name === option) : null
                  return (
                    <li key={key} {...rest}>
                      <Box>
                        <Typography variant="body2">
                          {option === null ? globalLabel : option}
                        </Typography>
                        {agentInfo?.description && (
                          <Typography variant="caption" color="text.secondary">
                            {agentInfo.description}
                          </Typography>
                        )}
                      </Box>
                    </li>
                  )
                }

                const globalPlanLabel = dispatchGlobalSettings?.planAgentName
                  ? `Inherit from global (${dispatchGlobalSettings.planAgentName})`
                  : 'Inherit from global (none)'
                const globalBuildLabel = dispatchGlobalSettings?.buildAgentName
                  ? `Inherit from global (${dispatchGlobalSettings.buildAgentName})`
                  : 'Inherit from global (none)'

                const planOptions: (string | null)[] = [null, ...capabilityNames]
                const buildOptions: (string | null)[] = [null, ...capabilityNames]

                return (
                  <>
                    <Box sx={{ mt: 2 }}>
                      <Autocomplete<string | null>
                        options={planOptions}
                        value={localPlanDispatchAgent}
                        onChange={(_, val) => setLocalPlanDispatchAgent(val)}
                        disabled={dispatchCapabilitiesError !== null || hasActiveWave}
                        getOptionLabel={(option) => option === null ? globalPlanLabel : option}
                        isOptionEqualToValue={(option, value) => option === value}
                        renderOption={(props, option) =>
                          renderDispatchOption(
                            props as React.HTMLAttributes<HTMLLIElement> & { key?: React.Key },
                            option,
                            globalPlanLabel,
                          )
                        }
                        renderInput={(params) => (
                          <TextField
                            {...params}
                            label="Plan Agent"
                            size="small"
                            helperText={capabilitiesHelperText ?? undefined}
                          />
                        )}
                      />
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                        Effective:{' '}
                        <strong>
                          {(project.planDispatchAgent ?? dispatchGlobalSettings?.planAgentName) || '(none)'}
                        </strong>
                      </Typography>
                    </Box>
                    <Box sx={{ mt: 2 }}>
                      <Autocomplete<string | null>
                        options={buildOptions}
                        value={localBuildDispatchAgent}
                        onChange={(_, val) => setLocalBuildDispatchAgent(val)}
                        disabled={dispatchCapabilitiesError !== null || hasActiveWave}
                        getOptionLabel={(option) => option === null ? globalBuildLabel : option}
                        isOptionEqualToValue={(option, value) => option === value}
                        renderOption={(props, option) =>
                          renderDispatchOption(
                            props as React.HTMLAttributes<HTMLLIElement> & { key?: React.Key },
                            option,
                            globalBuildLabel,
                          )
                        }
                        renderInput={(params) => (
                          <TextField
                            {...params}
                            label="Build Agent"
                            size="small"
                            helperText={capabilitiesHelperText ?? undefined}
                          />
                        )}
                      />
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                        Effective:{' '}
                        <strong>
                          {(project.buildDispatchAgent ?? dispatchGlobalSettings?.buildAgentName) || '(none)'}
                        </strong>
                      </Typography>
                    </Box>
                  </>
                )
              })()}

              {/* Max turns field */}
              <Box sx={{ mt: 2 }}>
                <TextField
                  label="Max Turns"
                  type="number"
                  size="small"
                  fullWidth
                  value={localDispatchMaxTurnsStr}
                  onChange={(e) => setLocalDispatchMaxTurnsStr(e.target.value)}
                  disabled={hasActiveWave}
                  placeholder={
                    dispatchGlobalSettings
                      ? `Inherit from global (${dispatchGlobalSettings.defaultMaxTurns})`
                      : 'Inherit from global'
                  }
                  slotProps={{
                    htmlInput: { min: 10, max: 500 },
                    inputLabel: { shrink: localDispatchMaxTurnsStr !== '' || undefined },
                  }}
                  helperText="Leave blank to inherit the global default. Valid range: 10–500."
                />
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                  Effective:{' '}
                  <strong>
                    {project.dispatchMaxTurns ?? dispatchGlobalSettings?.defaultMaxTurns ?? '(unset)'}
                  </strong>
                </Typography>
              </Box>

              {/* Dispatch timeout field */}
              <Box sx={{ mt: 2 }}>
                <TextField
                  label="Dispatch timeout (min)"
                  type="number"
                  size="small"
                  fullWidth
                  value={localDispatchTimeoutMinutesStr}
                  onChange={(e) => setLocalDispatchTimeoutMinutesStr(e.target.value)}
                  disabled={hasActiveWave}
                  placeholder={
                    dispatchGlobalSettings
                      ? `Inherit from global (${dispatchGlobalSettings.defaultTimeoutMinutes})`
                      : 'Inherit from global'
                  }
                  slotProps={{
                    htmlInput: { min: 5, max: 480 },
                    inputLabel: { shrink: localDispatchTimeoutMinutesStr !== '' || undefined },
                  }}
                  helperText="Leave blank to inherit the global default. Valid range: 5–480 minutes."
                />
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                  Effective:{' '}
                  <strong>
                    {project.dispatchTimeoutMinutes ?? dispatchGlobalSettings?.defaultTimeoutMinutes ?? '(unset)'}
                  </strong>
                </Typography>
              </Box>

              {/* Helper text */}
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                Overrides apply when dispatching tasks from this project. Leave a field blank to use the global default.
              </Typography>

              {/* Save controls */}
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mt: 2 }}>
                <Button
                  variant="contained"
                  size="small"
                  onClick={handleSaveDispatch}
                  disabled={savingDispatch || hasActiveWave}
                >
                  {savingDispatch ? <CircularProgress size={18} /> : 'Save'}
                </Button>
                {dispatchSaved && (
                  <Typography variant="body2" color="success.main">
                    Saved
                  </Typography>
                )}
              </Box>
              {dispatchSaveError && (
                <Alert severity="error" sx={{ mt: 1 }} onClose={() => setDispatchSaveError(null)}>
                  {dispatchSaveError}
                </Alert>
              )}
            </CardContent>
          </Card>
          </>
          )}
        </Box>
      )}

      {/* Edit Project Dialog */}
      <ProjectEditDialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        editing={project}
        onSaved={(updated) => { setProject(updated) }}
      />

      {/* Item Dialog */}
      <Dialog
        open={itemDialogOpen}
        onClose={() => setItemDialogOpen(false)}
        fullWidth
        maxWidth="sm"
        onKeyDown={(e) => {
          if (e.key !== 'Enter') return
          const modifier = e.metaKey || e.ctrlKey
          // Cmd/Ctrl+Shift+Enter → Save and Plan (new-item mode only, requires git origin)
          if (e.shiftKey && modifier) {
            e.preventDefault()
            if (!editingItem && itemTitle.trim() && !savingItem && project?.gitOrigin) {
              void handleSaveAndPlan()
            }
            return
          }
          // Enter (modifier or non-textarea) → Save / Create — existing behaviour
          if (!e.shiftKey && (modifier || !(e.target instanceof HTMLTextAreaElement))) {
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
              <MenuItem value="new">New</MenuItem>
              <MenuItem value="ready">Ready</MenuItem>
              <MenuItem value="active">In Progress</MenuItem>
              <MenuItem value="review">Review</MenuItem>
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
            <FormControl fullWidth margin="normal" size="small">
              <InputLabel>Project</InputLabel>
              <Select
                value={itemProjectId}
                onChange={(e) => setItemProjectId(e.target.value)}
                label="Project"
              >
                <MenuItem value="">
                  <em>None (Inbox)</em>
                </MenuItem>
                {allProjects.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
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
                        primary={<MarkdownContent>{c.contentMarkdown}</MarkdownContent>}
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
        <DialogActions sx={{ justifyContent: 'space-between' }}>
          {/* Left slot: Save and Plan (new item mode only) */}
          {!editingItem ? (
            <Tooltip title={!project?.gitOrigin ? 'No dispatch origin configured for this project' : ''}>
              <span>
                <Button
                  onClick={handleSaveAndPlan}
                  disabled={savingItem || !itemTitle.trim() || !project?.gitOrigin}
                >
                  Save and Plan
                </Button>
              </span>
            </Tooltip>
          ) : (
            <Box />
          )}
          {/* Right slot: Cancel + Save/Create */}
          <Box>
            <Button onClick={() => {
              clearItemDraft()
              setItemDialogOpen(false)
            }}>Cancel</Button>
            <Button
              variant="contained"
              onClick={handleSaveItem}
              disabled={savingItem || !itemTitle.trim()}
            >
              {savingItem ? <CircularProgress size={20} /> : editingItem ? 'Save' : 'Create'}
            </Button>
          </Box>
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
          setItems((prev) => prev.map((i) => (i.id === updated.id ? (updated as DisplayItem) : i)))
        }}
        projectName={project.name}
        projectGitOrigin={project.gitOrigin}
        projectIsOwner={project.isOwner !== false}
        showAttribution={(project.memberCount ?? 0) > 0 || project.isOwner === false}
      />

      {/* Activity Drawer */}
      <ActivityDrawer
        open={activityDrawerOpen}
        onClose={() => setActivityDrawerOpen(false)}
        projectId={project.id}
        activeRolloutId={activeRolloutId}
        scope={activityDrawerScope}
        onScopeChange={setActivityDrawerScope}
      />
    </Box>
  )
}
