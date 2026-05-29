import { useState, useEffect, useRef, useCallback } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Drawer,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import CloseIcon from '@mui/icons-material/Close'
import SendIcon from '@mui/icons-material/Send'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'
import AttachFileIcon from '@mui/icons-material/AttachFile'
import DeleteIcon from '@mui/icons-material/Delete'
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile'
import { api, ApiError } from '../api'
import type { AttachmentResponse, DispatchHost, Item, Comment, MemberSummary, Project, Run, ItemStatus } from '../types'
import { BUILD_ENGINE_OPTIONS } from '../engineLabels'
import { isDispatchServiceConfigured, formatRelativeTime, formatFileSize } from '../utils'
import { useAuth } from '../contexts/AuthContext'
import { useEvents } from '../contexts/EventStreamContext'
import { BlockerPicker } from './BlockerPicker'
import MarkdownContent from './MarkdownContent'

const DRAWER_WIDTH = 792

const STATUS_LABELS: Partial<Record<ItemStatus, string>> = {
  inbox: 'Inbox',
  new: 'New',
  ready: 'Ready',
  active: 'In Progress',
  review: 'Review',
  waiting_for: 'Waiting',
  someday_maybe: 'Someday',
  done: 'Done',
}


function isAgentComment(c: Comment): boolean {
  const by = c.createdBy.toLowerCase()
  return by.includes('claude') || by.includes('dispatch') || by.includes('agent')
}

interface ItemDetailDrawerProps {
  item: Item | null
  onClose: () => void
  onEdit: (item: Item) => void
  onItemUpdated?: (item: Item) => void
  projectName?: string
  projectGitOrigin?: string
  /** Whether the current user owns the project. Defaults to true (solo context). */
  projectIsOwner?: boolean
  /** Whether to show item attribution (createdBy email). */
  showAttribution?: boolean
}

export default function ItemDetailDrawer({
  item,
  onClose,
  onEdit,
  onItemUpdated,
  projectName,
  projectGitOrigin,
  projectIsOwner = true,
  showAttribution = false,
}: ItemDetailDrawerProps) {
  const [comments, setComments] = useState<Comment[]>([])
  const [newComment, setNewComment] = useState('')
  const [saving, setSaving] = useState(false)
  const [loadingComments, setLoadingComments] = useState(false)
  const [activeRun, setActiveRun] = useState<Run | null>(null)
  const [dispatching, setDispatching] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [dispatchMode, setDispatchMode] = useState<'build' | 'plan'>('build')
  const [dispatchError, setDispatchError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [dispatchAnimating, setDispatchAnimating] = useState(false)
  const [dispatchConfigured, setDispatchConfigured] = useState<boolean | null>(null)
  const [defaultMaxTurns, setDefaultMaxTurns] = useState<number | undefined>(undefined)
  const [dispatchHosts, setDispatchHosts] = useState<DispatchHost[]>([])
  const [dispatchHostId, setDispatchHostId] = useState<string>('')

  // Local item state — stays in sync with prop, then updated optimistically on each inline save
  const [localItem, setLocalItem] = useState<Item | null>(null)

  // Inline edit state
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleValue, setTitleValue] = useState('')
  const [editingDescription, setEditingDescription] = useState(false)
  const [descriptionValue, setDescriptionValue] = useState('')
  const [savingField, setSavingField] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [dueDateValue, setDueDateValue] = useState('')
  const [addingLabel, setAddingLabel] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [allProjects, setAllProjects] = useState<Project[]>([])
  const [projectMembers, setProjectMembers] = useState<MemberSummary[]>([])
  const [blockerExpanded, setBlockerExpanded] = useState(false)
  const [metadataExpanded, setMetadataExpanded] = useState(false)
  const [attachmentsExpanded, setAttachmentsExpanded] = useState(false)
  const [acExpanded, setAcExpanded] = useState(false)
  const [filesToModifyExpanded, setFilesToModifyExpanded] = useState(false)
  const [loadingBlockers, setLoadingBlockers] = useState(false)

  // Attachment state
  const [attachments, setAttachments] = useState<AttachmentResponse[]>([])
  const [loadingAttachments, setLoadingAttachments] = useState(false)
  const [uploadingAttachment, setUploadingAttachment] = useState(false)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [previewAttachment, setPreviewAttachment] = useState<AttachmentResponse | null>(null)
  const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null)
  const [deleteAttachmentTarget, setDeleteAttachmentTarget] = useState<AttachmentResponse | null>(null)
  const [deletingAttachment, setDeletingAttachment] = useState(false)
  // attachmentId → blob URL for image thumbnails
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string>>({})

  const { user } = useAuth()
  const commentsEndRef = useRef<HTMLDivElement>(null)
  const itemIdRef = useRef<string | undefined>(undefined)
  // Tracks which attachment IDs have already had blob URL fetches initiated
  const fetchedThumbnailIdsRef = useRef<Set<string>>(new Set())
  // Always-current ref to thumbnailUrls for cleanup without stale closures
  const thumbnailUrlsRef = useRef<Record<string, string>>({})
  // Ref to the active preview blob URL for cleanup without stale closures
  const previewBlobUrlRef = useRef<string | null>(null)
  // Ref to the file input for resetting after upload
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { onEvent } = useEvents()

  // Sync localItem and reset inline edit state whenever the item prop changes.
  // When the same item is updated via an inline save, preserve any locally-loaded
  // blockers that the PATCH response does not include.
  useEffect(() => {
    setLocalItem((prev) => {
      if (!item) return null
      const isSameItem = item.id === prev?.id
      const blockers =
        item.blockers !== undefined
          ? item.blockers
          : isSameItem
            ? prev?.blockers
            : undefined
      return { ...item, blockers }
    })
    setEditingTitle(false)
    setEditingDescription(false)
    setTitleValue(item?.title ?? '')
    setDescriptionValue(item?.description ?? '')
    setDueDateValue(item?.dueDate ?? '')
    setFieldError(null)
    setAddingLabel(false)
    setNewLabel('')
    setMetadataExpanded(false)
    setAttachmentsExpanded(false)
    setAcExpanded(false)
    setFilesToModifyExpanded(false)
  }, [item])

  // Load active projects for the project dropdown — only when the drawer
  // actually has an item open. Mounting unconditionally above the router means
  // this fires on /login too, which 401s and triggers the global redirect.
  useEffect(() => {
    if (!item) return
    api.projects.list({ status: 'active' }).then(setAllProjects).catch(() => {})
  }, [item])

  // Load project members for the assignee dropdown — keyed on projectId so it
  // refreshes whenever the item is moved to a different project.
  useEffect(() => {
    const projectId = localItem?.projectId
    if (!projectId) {
      setProjectMembers([])
      return
    }
    api.projects.members.list(projectId).then(setProjectMembers).catch(() => {
      setProjectMembers([])
    })
  }, [localItem?.projectId])

  // Load dispatch config when the drawer has an item open. Same gating reason.
  useEffect(() => {
    if (!item) return
    api.settings.getDispatch().then((cfg) => {
      setDispatchConfigured(isDispatchServiceConfigured(cfg.serviceUrl, cfg.serviceApiKeyPreview))
      setDefaultMaxTurns(cfg.defaultMaxTurns)
    }).catch(() => {
      setDispatchConfigured(null)
    })
    api.dispatchHosts.list().then(setDispatchHosts).catch(() => {})
  }, [item])

  // Reset the dispatch-animation flag once the drawer has actually closed.
  // Keeping it true through the close keeps MUI's transitionDuration at 0 so
  // the default right-slide exit doesn't play after our CSS slide-up.
  useEffect(() => {
    if (!item && dispatchAnimating) {
      const t = setTimeout(() => setDispatchAnimating(false), 100)
      return () => clearTimeout(t)
    }
  }, [item, dispatchAnimating])

  // Load blockers and reset expanded state when switching to a different item.
  // Uses itemIdRef to distinguish a new-item open from an inline-save update
  // (both change the `item` reference, but only the former changes the ID).
  useEffect(() => {
    const isNewItem = item?.id !== itemIdRef.current
    itemIdRef.current = item?.id

    if (!isNewItem) return

    setBlockerExpanded(false)
    if (!item) return

    let cancelled = false
    setLoadingBlockers(true)
    void api.items.blockers.list(item.id)
      .then((bs) => {
        if (!cancelled) {
          setLocalItem((prev) => {
            if (!prev || prev.id !== item.id) return prev
            return { ...prev, blockers: bs }
          })
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingBlockers(false) })
    return () => { cancelled = true }
  }, [item])

  const loadComments = useCallback(async () => {
    if (!item) return
    setLoadingComments(true)
    try {
      const data = await api.items.comments(item.id)
      setComments(data)
    } catch {
      // silently fail
    } finally {
      setLoadingComments(false)
    }
  }, [item])

  const loadActiveRun = useCallback(async () => {
    if (!item) return
    try {
      const runs = await api.items.runs(item.id)
      const active = runs.find((r) =>
        ['pending', 'cloning', 'running'].includes(r.status),
      )
      setActiveRun(active ?? (runs.length > 0 ? runs[0] : null))
    } catch {
      // silently fail
    }
  }, [item])

  const loadAttachments = useCallback(async () => {
    if (!item) return
    setLoadingAttachments(true)
    try {
      const data = await api.attachments.list(item.id)
      setAttachments(data)
    } catch {
      // silently fail
    } finally {
      setLoadingAttachments(false)
    }
  }, [item])

  useEffect(() => {
    if (item) {
      loadComments()
      loadActiveRun()
      loadAttachments()
      setNewComment('')
      setDispatchError(null)
    } else {
      setComments([])
      setActiveRun(null)
      // Revoke all thumbnail blob URLs
      Object.values(thumbnailUrlsRef.current).forEach((u) => URL.revokeObjectURL(u))
      thumbnailUrlsRef.current = {}
      setThumbnailUrls({})
      setAttachments([])
      setAttachmentError(null)
      fetchedThumbnailIdsRef.current.clear()
      // Revoke active preview blob URL
      if (previewBlobUrlRef.current) {
        URL.revokeObjectURL(previewBlobUrlRef.current)
        previewBlobUrlRef.current = null
        setPreviewBlobUrl(null)
      }
      setPreviewAttachment(null)
    }
  }, [item, loadComments, loadActiveRun, loadAttachments])

  // Refresh on SSE events
  useEffect(() => {
    const unsubs = [
      onEvent('comment_created', () => loadComments()),
      onEvent('comment_updated', () => loadComments()),
      onEvent('comment_deleted', () => loadComments()),
      onEvent('run_started', () => loadActiveRun()),
      onEvent('run_completed', () => loadActiveRun()),
      onEvent('run_failed', () => loadActiveRun()),
    ]
    return () => unsubs.forEach((u) => u())
  }, [onEvent, loadComments, loadActiveRun])

  useEffect(() => {
    commentsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [comments.length])

  // Fetch thumbnail blob URLs for newly-loaded image attachments.
  // Uses fetchedThumbnailIdsRef to avoid double-fetching across re-renders.
  useEffect(() => {
    const imageAtts = attachments.filter((a) => a.mimeType.startsWith('image/'))
    const toFetch = imageAtts.filter((a) => !fetchedThumbnailIdsRef.current.has(a.id))
    if (toFetch.length === 0) return

    let cancelled = false
    const fetchAll = async () => {
      for (const att of toFetch) {
        if (cancelled) break
        fetchedThumbnailIdsRef.current.add(att.id)
        try {
          const url = await api.attachments.downloadBlobUrl(att.id)
          if (cancelled) {
            URL.revokeObjectURL(url)
            break
          }
          thumbnailUrlsRef.current = { ...thumbnailUrlsRef.current, [att.id]: url }
          setThumbnailUrls((prev) => ({ ...prev, [att.id]: url }))
        } catch {
          // thumbnail won't show; non-fatal
        }
      }
    }
    void fetchAll()
    return () => {
      cancelled = true
    }
  }, [attachments])

  // --- Inline save helper ---

  const saveField = useCallback(
    async (fieldKey: string, value: unknown) => {
      if (!localItem) return
      setSavingField(fieldKey)
      setFieldError(null)
      try {
        const updated = await api.items.update(localItem.id, {
          [fieldKey]: value,
          version: localItem.version,
        })
        setLocalItem(updated)
        onItemUpdated?.(updated)
      } catch (err) {
        if (err instanceof ApiError && err.blockers && err.blockers.length > 0) {
          const list = err.blockers.map((b) => `• ${b.title} (${b.status})`).join('\n')
          setFieldError(`${err.detail}\n\n${list}`)
        } else {
          setFieldError(
            err instanceof ApiError
              ? err.status === 409
                ? 'This item was updated elsewhere — refresh to see the latest version.'
                : err.detail
              : 'Failed to update',
          )
        }
      } finally {
        setSavingField(null)
      }
    },
    [localItem, onItemUpdated],
  )

  // --- Title handlers ---

  const handleTitleSave = useCallback(async () => {
    const trimmed = titleValue.trim()
    setEditingTitle(false)
    if (!trimmed || trimmed === localItem?.title) return
    await saveField('title', trimmed)
  }, [titleValue, localItem?.title, saveField])

  const handleTitleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        void handleTitleSave()
      }
      if (e.key === 'Escape') {
        setEditingTitle(false)
        setTitleValue(localItem?.title ?? '')
      }
    },
    [handleTitleSave, localItem?.title],
  )

  // --- Description handlers ---

  const handleDescriptionSave = useCallback(async () => {
    setEditingDescription(false)
    if (descriptionValue === (localItem?.description ?? '')) return
    await saveField('description', descriptionValue)
  }, [descriptionValue, localItem?.description, saveField])

  const handleDescriptionKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setEditingDescription(false)
        setDescriptionValue(localItem?.description ?? '')
      }
    },
    [localItem?.description],
  )

  // --- Due date handler ---

  const handleDueDateSave = useCallback(async () => {
    const current = localItem?.dueDate ?? ''
    if (dueDateValue === current) return
    await saveField('dueDate', dueDateValue || null)
  }, [dueDateValue, localItem?.dueDate, saveField])

  // --- Label handlers ---

  const handleAddLabel = useCallback(async () => {
    if (!newLabel.trim() || !localItem) return
    const trimmed = newLabel.trim()
    setNewLabel('')
    setAddingLabel(false)
    if (localItem.labels.includes(trimmed)) return
    await saveField('labels', [...localItem.labels, trimmed])
  }, [newLabel, localItem, saveField])

  const handleRemoveLabel = useCallback(
    async (label: string) => {
      if (!localItem) return
      await saveField(
        'labels',
        localItem.labels.filter((l) => l !== label),
      )
    },
    [localItem, saveField],
  )

  // --- Attachment handlers ---

  const handleUploadFile = useCallback(async (file: File) => {
    if (!item) return
    setUploadingAttachment(true)
    setAttachmentError(null)
    try {
      const att = await api.attachments.upload(item.id, file)
      setAttachments((prev) => [...prev, att])
    } catch (err) {
      setAttachmentError(err instanceof ApiError ? err.detail : 'Upload failed')
    } finally {
      setUploadingAttachment(false)
    }
  }, [item])

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      if (fileInputRef.current) fileInputRef.current.value = ''
      void handleUploadFile(file)
    },
    [handleUploadFile],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const file = e.dataTransfer.files?.[0]
      if (!file) return
      void handleUploadFile(file)
    },
    [handleUploadFile],
  )

  const handleOpenPreview = useCallback(async (att: AttachmentResponse) => {
    setPreviewAttachment(att)
    try {
      const url = await api.attachments.downloadBlobUrl(att.id)
      previewBlobUrlRef.current = url
      setPreviewBlobUrl(url)
    } catch {
      setPreviewAttachment(null)
    }
  }, [])

  const handleClosePreview = useCallback(() => {
    if (previewBlobUrlRef.current) {
      URL.revokeObjectURL(previewBlobUrlRef.current)
      previewBlobUrlRef.current = null
    }
    setPreviewBlobUrl(null)
    setPreviewAttachment(null)
  }, [])

  const handleOpenMarkdown = useCallback(async (att: AttachmentResponse) => {
    try {
      const url = await api.attachments.downloadBlobUrl(att.id)
      window.open(url, '_blank')
      // Revoke after a short delay — browser needs time to read the blob
      setTimeout(() => URL.revokeObjectURL(url), 2000)
    } catch {
      setAttachmentError('Failed to open file')
    }
  }, [])

  const handleDeleteAttachment = useCallback(async () => {
    if (!deleteAttachmentTarget) return
    setDeletingAttachment(true)
    try {
      await api.attachments.delete(deleteAttachmentTarget.id)
      // Revoke and remove thumbnail blob URL
      const thumbUrl = thumbnailUrlsRef.current[deleteAttachmentTarget.id]
      if (thumbUrl) {
        URL.revokeObjectURL(thumbUrl)
        const next = { ...thumbnailUrlsRef.current }
        delete next[deleteAttachmentTarget.id]
        thumbnailUrlsRef.current = next
        setThumbnailUrls(next)
      }
      // Remove from list
      setAttachments((prev) => prev.filter((a) => a.id !== deleteAttachmentTarget.id))
      // Close preview if it was showing the deleted attachment
      if (previewAttachment?.id === deleteAttachmentTarget.id) {
        handleClosePreview()
      }
      setDeleteAttachmentTarget(null)
    } catch (err) {
      setAttachmentError(err instanceof ApiError ? err.detail : 'Delete failed')
      setDeleteAttachmentTarget(null)
    } finally {
      setDeletingAttachment(false)
    }
  }, [deleteAttachmentTarget, previewAttachment, handleClosePreview])

  // --- Comment / dispatch handlers ---

  const handleSend = async () => {
    if (!item || !newComment.trim()) return
    setSaving(true)
    try {
      const created = await api.items.createComment(item.id, { contentMarkdown: newComment })
      setComments((prev) => [...prev, created])
      setNewComment('')
    } catch {
      // silently fail
    } finally {
      setSaving(false)
    }
  }

  const handleDispatch = useCallback(async (mode: 'build' | 'plan' = dispatchMode) => {
    if (!item || !localItem) return
    setDispatching(true)
    setDispatchError(null)
    try {
      const run = await api.items.dispatch(item.id, {
        mode,
        ...(defaultMaxTurns !== undefined ? { maxTurns: defaultMaxTurns } : {}),
        ...(dispatchHostId ? { dispatchHostId } : {}),
      })
      setActiveRun(run)
      setConfirmOpen(false)
      setDispatchMode('build')
      // Slide drawer up and away, then close. Keep dispatchAnimating=true
      // through the close so MUI's transitionDuration stays 0 and it doesn't
      // replay its default right-slide exit. The flag is reset by the
      // useEffect below once `item` goes null.
      setDispatchAnimating(true)
      setTimeout(() => {
        onClose()
      }, 380)
    } catch (err) {
      if (err instanceof ApiError && err.blockers && err.blockers.length > 0) {
        const list = err.blockers.map((b) => `• ${b.title} (${b.status})`).join('\n')
        setDispatchError(`${err.detail}\n\n${list}`)
      } else {
        setDispatchError(err instanceof ApiError ? err.detail : 'Dispatch failed')
      }
    } finally {
      setDispatching(false)
    }
  }, [item, localItem, dispatchMode, defaultMaxTurns, dispatchHostId])

  const handleCopy = () => {
    if (!item) return
    void navigator.clipboard.writeText(item.id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const isRunActive = activeRun && ['pending', 'cloning', 'running'].includes(activeRun.status)
  const isRunQueued = activeRun?.status === 'pending'
  // dispatchConfigured: null = unknown (endpoint not available), treat as ok
  // For project members, treat dispatch as configured — the backend uses the owner's settings.
  const isDispatchConfigured = projectIsOwner ? dispatchConfigured !== false : true
  // AC-21: item locked by an active wave
  const isLockedByRollout = Boolean(item?.lockedByRolloutId)
  const canDispatch = Boolean(projectGitOrigin) && !isRunActive && isDispatchConfigured && !isLockedByRollout
  const isSaving = savingField !== null

  function getDispatchTooltip(): string {
    if (isLockedByRollout) return 'This item is locked by an active wave.'
    if (dispatchConfigured === false) return 'Configure dispatch in Settings → Agent Dispatch.'
    if (isRunQueued) return 'Queued — waiting for a free slot (capped at 6 concurrent runs)'
    if (isRunActive) return 'Agent is working'
    if (!projectGitOrigin) return 'No git origin'
    return 'Dispatch to Remote Agent'
  }

  // Keyboard shortcuts: D = dispatch build, Shift+D = dispatch plan
  useHotkeys('d', () => {
    if (!item || !canDispatch) return
    void handleDispatch('build')
  }, {
    enabled: Boolean(item),
    enableOnFormTags: false,
  }, [item, canDispatch, handleDispatch])

  useHotkeys('shift+d', (e) => {
    e.preventDefault()
    if (!item || !canDispatch) return
    void handleDispatch('plan')
  }, {
    enabled: Boolean(item),
    enableOnFormTags: false,
  }, [item, canDispatch, handleDispatch])

  return (
    <>
      <Drawer
        anchor="right"
        open={Boolean(item)}
        onClose={dispatchAnimating ? undefined : onClose}
        variant="temporary"
        transitionDuration={dispatchAnimating ? 0 : undefined}
        sx={{
          '& .MuiDrawer-paper': {
            width: { xs: '100vw', sm: DRAWER_WIDTH },
            boxSizing: 'border-box',
            top: '64px',
            height: 'calc(100% - 64px)',
            ...(dispatchAnimating && {
              animation: 'dispatchSlideUp 380ms cubic-bezier(0.4, 0, 1, 1) forwards',
            }),
          },
          ...(dispatchAnimating && {
            '@keyframes dispatchSlideUp': {
              '0%':   { transform: 'translateX(0)',    opacity: 1 },
              '100%': { transform: 'translateY(-110%)', opacity: 0 },
            },
          }),
          ...(dispatchAnimating && {
            '& .MuiBackdrop-root': {
              opacity: '0 !important',
              transition: 'none !important',
            },
          }),
        }}
      >
        {localItem && (
          <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Header */}
            <Box sx={{ p: 2, display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                {/* Editable title */}
                {editingTitle ? (
                  <TextField
                    value={titleValue}
                    onChange={(e) => setTitleValue(e.target.value)}
                    onBlur={() => void handleTitleSave()}
                    onKeyDown={handleTitleKeyDown}
                    variant="standard"
                    fullWidth
                    size="small"
                    disabled={isSaving}
                    autoFocus
                    slotProps={{
                      input: {
                        sx: { fontSize: '1.25rem', fontWeight: 500, lineHeight: 1.3 },
                      },
                    }}
                  />
                ) : (
                  <Typography
                    variant="h6"
                    sx={{
                      lineHeight: 1.3,
                      cursor: 'text',
                      borderRadius: 0.5,
                      px: 0.5,
                      mx: -0.5,
                      '&:hover': { bgcolor: 'action.hover' },
                    }}
                    onClick={() => {
                      setEditingTitle(true)
                      setTitleValue(localItem.title)
                    }}
                    title="Click to edit title"
                  >
                    {localItem.title}
                    {savingField === 'title' && (
                      <CircularProgress size={12} sx={{ ml: 1, verticalAlign: 'middle' }} />
                    )}
                  </Typography>
                )}

                {/* ID row */}
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25, mb: 1 }}>
                  <Typography variant="caption" color="text.disabled">
                    #{localItem.id.slice(0, 8)}
                  </Typography>
                  <Tooltip title={copied ? 'Copied!' : 'Copy ID'} placement="right">
                    <IconButton
                      size="small"
                      onClick={handleCopy}
                      sx={{ p: 0.25 }}
                      aria-label="Copy item ID"
                    >
                      {copied ? (
                        <CheckIcon sx={{ fontSize: 14, color: 'success.main' }} />
                      ) : (
                        <ContentCopyIcon sx={{ fontSize: 14 }} />
                      )}
                    </IconButton>
                  </Tooltip>
                </Box>

                <Accordion
                  expanded={metadataExpanded}
                  onChange={(_, isExpanded) => setMetadataExpanded(isExpanded)}
                  disableGutters
                  elevation={0}
                  sx={{
                    '&:before': { display: 'none' },
                    bgcolor: 'transparent',
                    mt: 0.5,
                  }}
                >
                  <AccordionSummary
                    expandIcon={<ExpandMoreIcon sx={{ fontSize: 16 }} />}
                    sx={{
                      px: 0,
                      minHeight: 0,
                      '& .MuiAccordionSummary-content': { my: 0.5 },
                    }}
                  >
                    <Typography variant="caption" color="text.secondary">
                      Details · {STATUS_LABELS[localItem.status]}
                    </Typography>
                  </AccordionSummary>
                  <AccordionDetails sx={{ px: 0, pt: 0.5, pb: 0 }}>
                {/* Editable status + priority row */}
                <Box sx={{ display: 'flex', gap: 1, mt: 0.5, flexWrap: 'wrap', alignItems: 'center' }}>
                  {/* Status select */}
                  <FormControl size="small" disabled={isSaving}>
                    <InputLabel
                      id="drawer-status-label"
                      sx={{ fontSize: '0.7rem', top: '-4px', '&.MuiInputLabel-shrink': { top: 0 } }}
                    >
                      Status
                    </InputLabel>
                    <Select
                      labelId="drawer-status-label"
                      value={localItem.status}
                      label="Status"
                      onChange={(e) => void saveField('status', e.target.value)}
                      sx={{
                        fontSize: '0.75rem',
                        height: 28,
                        minWidth: 100,
                        '& .MuiSelect-select': { py: '2px', px: 1 },
                      }}
                    >
                      {Object.entries(STATUS_LABELS)
                        .filter(([value]) => value !== 'inbox')
                        .map(([value, label]) => (
                        <MenuItem key={value} value={value} sx={{ fontSize: '0.8rem' }}>
                          {label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>

                  {/* Priority select */}
                  <FormControl size="small" disabled={isSaving}>
                    <InputLabel
                      id="drawer-priority-label"
                      sx={{ fontSize: '0.7rem', top: '-4px', '&.MuiInputLabel-shrink': { top: 0 } }}
                    >
                      Priority
                    </InputLabel>
                    <Select
                      labelId="drawer-priority-label"
                      value={localItem.priority}
                      label="Priority"
                      onChange={(e) => void saveField('priority', e.target.value)}
                      sx={{
                        fontSize: '0.75rem',
                        height: 28,
                        minWidth: 80,
                        '& .MuiSelect-select': { py: '2px', px: 1 },
                        // Color tint based on priority
                        ...(localItem.priority === 'urgent' && { color: 'error.main' }),
                        ...(localItem.priority === 'high' && { color: 'warning.main' }),
                      }}
                    >
                      <MenuItem value="low" sx={{ fontSize: '0.8rem' }}>Low</MenuItem>
                      <MenuItem value="normal" sx={{ fontSize: '0.8rem' }}>Normal</MenuItem>
                      <MenuItem value="high" sx={{ fontSize: '0.8rem' }}>High</MenuItem>
                      <MenuItem value="urgent" sx={{ fontSize: '0.8rem' }}>Urgent</MenuItem>
                    </Select>
                  </FormControl>

                  {/* Project select */}
                  <FormControl size="small" disabled={isSaving}>
                    <InputLabel
                      id="drawer-project-label"
                      sx={{ fontSize: '0.7rem', top: '-4px', '&.MuiInputLabel-shrink': { top: 0 } }}
                    >
                      Project
                    </InputLabel>
                    <Select
                      labelId="drawer-project-label"
                      value={localItem.projectId ?? ''}
                      label="Project"
                      onChange={(e) => void saveField('projectId', e.target.value || null)}
                      sx={{
                        fontSize: '0.75rem',
                        height: 28,
                        minWidth: 120,
                        '& .MuiSelect-select': { py: '2px', px: 1 },
                      }}
                    >
                      <MenuItem value="" sx={{ fontSize: '0.8rem' }}>
                        <em>None</em>
                      </MenuItem>
                      {/* Include current project even if inactive (not in active list) */}
                      {localItem.projectId && !allProjects.some((p) => p.id === localItem.projectId) && (
                        <MenuItem value={localItem.projectId} sx={{ fontSize: '0.8rem' }}>
                          {projectName ?? localItem.projectId}
                        </MenuItem>
                      )}
                      {[...allProjects]
                        .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
                        .map((p) => (
                          <MenuItem key={p.id} value={p.id} sx={{ fontSize: '0.8rem' }}>
                            {p.name}
                          </MenuItem>
                        ))}
                    </Select>
                  </FormControl>

                  {/* Build engine select — only for project items */}
                  {localItem.projectId && (
                    <FormControl size="small" disabled={isSaving}>
                      <InputLabel
                        id="drawer-engine-label"
                        sx={{ fontSize: '0.7rem', top: '-4px', '&.MuiInputLabel-shrink': { top: 0 } }}
                      >
                        Build engine
                      </InputLabel>
                      <Select
                        labelId="drawer-engine-label"
                        value={localItem.buildEngine ?? ''}
                        label="Build engine"
                        onChange={(e) => void saveField('buildEngine', e.target.value || null)}
                        sx={{
                          fontSize: '0.75rem',
                          height: 28,
                          minWidth: 120,
                          '& .MuiSelect-select': { py: '2px', px: 1 },
                        }}
                      >
                        <MenuItem value="" sx={{ fontSize: '0.8rem' }}>
                          <em>Default</em>
                        </MenuItem>
                        {BUILD_ENGINE_OPTIONS.map((opt) => (
                          <MenuItem key={opt.value} value={opt.value} sx={{ fontSize: '0.8rem' }}>
                            {opt.displayLabel}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}

                  {/* Editable due date */}
                  <TextField
                    type="date"
                    label="Due date"
                    size="small"
                    value={dueDateValue}
                    onChange={(e) => setDueDateValue(e.target.value)}
                    onBlur={() => void handleDueDateSave()}
                    slotProps={{ inputLabel: { shrink: true } }}
                    disabled={savingField === 'dueDate'}
                    sx={{ width: 150, '& input': { fontSize: '0.75rem', py: '2px' } }}
                  />
                  {/* Assignee select */}
                  <FormControl size="small" disabled={isSaving}>
                    <InputLabel
                      id="drawer-assignee-label"
                      sx={{ fontSize: '0.7rem', top: '-4px', '&.MuiInputLabel-shrink': { top: 0 } }}
                    >
                      Assignee
                    </InputLabel>
                    <Select
                      labelId="drawer-assignee-label"
                      value={localItem.assignedTo}
                      label="Assignee"
                      onChange={(e) => void saveField('assignedTo', e.target.value)}
                      sx={{
                        fontSize: '0.75rem',
                        height: 28,
                        minWidth: 120,
                        '& .MuiSelect-select': { py: '2px', px: 1 },
                      }}
                    >
                      <MenuItem value="" sx={{ fontSize: '0.8rem' }}>
                        <em>Unassigned</em>
                      </MenuItem>
                      {user?.email && (
                        <MenuItem value={user.email} sx={{ fontSize: '0.8rem' }}>
                          Me ({user.email})
                        </MenuItem>
                      )}
                      {projectMembers
                        .filter((m) => m.email !== user?.email)
                        .map((m) => (
                          <MenuItem key={m.userId} value={m.email} sx={{ fontSize: '0.8rem' }}>
                            {m.email}
                          </MenuItem>
                        ))}
                    </Select>
                  </FormControl>

                </Box>

                {/* Editable labels row */}
                {(localItem.labels.length > 0 || addingLabel) && (
                  <Box sx={{ display: 'flex', gap: 0.5, mt: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                    {localItem.labels.map((label) => (
                      <Chip
                        key={label}
                        label={label}
                        size="small"
                        variant="outlined"
                        onDelete={isSaving ? undefined : () => void handleRemoveLabel(label)}
                        disabled={savingField === 'labels'}
                      />
                    ))}
                    {addingLabel && (
                      <TextField
                        size="small"
                        value={newLabel}
                        onChange={(e) => setNewLabel(e.target.value)}
                        onBlur={() => void handleAddLabel()}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            void handleAddLabel()
                          }
                          if (e.key === 'Escape') {
                            setAddingLabel(false)
                            setNewLabel('')
                          }
                        }}
                        placeholder="Label…"
                        autoFocus
                        sx={{ width: 90, '& input': { py: '2px', fontSize: '0.75rem' } }}
                        disabled={isSaving}
                      />
                    )}
                  </Box>
                )}

                {/* Add label chip — shown when not already adding */}
                {!addingLabel && (
                  <Box sx={{ mt: 1 }}>
                    <Chip
                      label="+ Label"
                      size="small"
                      variant="outlined"
                      onClick={() => setAddingLabel(true)}
                      disabled={isSaving}
                      sx={{ cursor: 'pointer', fontSize: '0.7rem' }}
                    />
                  </Box>
                )}
                  </AccordionDetails>
                </Accordion>

                {/* Blocked by section */}
                {(localItem.blockers?.length ?? 0) === 0 && !blockerExpanded ? (
                  <Box sx={{ mt: 0.5 }}>
                    <Button
                      size="small"
                      onClick={() => setBlockerExpanded(true)}
                      disabled={isSaving}
                      sx={{
                        fontSize: '0.7rem',
                        px: 0.5,
                        py: 0,
                        color: 'text.secondary',
                        textTransform: 'none',
                        minHeight: 0,
                      }}
                    >
                      + Add blocker
                    </Button>
                  </Box>
                ) : (
                  <Box sx={{ mt: 1 }}>
                    <Typography variant="caption" color="text.secondary">
                      Blocked by
                    </Typography>
                    <Box sx={{ mt: 0.5 }}>
                      {loadingBlockers ? (
                        <CircularProgress size={16} />
                      ) : (
                        <BlockerPicker
                          itemId={localItem.id}
                          blockers={localItem.blockers ?? []}
                          onChange={(newBlockers) => {
                            const updated = { ...localItem, blockers: newBlockers }
                            setLocalItem(updated)
                            onItemUpdated?.(updated)
                          }}
                          disabled={isSaving}
                        />
                      )}
                    </Box>
                  </Box>
                )}
              </Box>

              {/* Action buttons */}
              {projectGitOrigin && localItem.status !== 'done' && (
                <Tooltip title={getDispatchTooltip()}>
                  <span>
                    <IconButton
                      size="small"
                      onClick={() => {
                        setDispatchMode(localItem?.status === 'new' ? 'plan' : 'build')
                        setConfirmOpen(true)
                      }}
                      disabled={!canDispatch}
                      color="secondary"
                    >
                      {isRunQueued ? (
                        <HourglassEmptyIcon
                          fontSize="small"
                          sx={{ color: 'text.disabled' }}
                        />
                      ) : (
                        <SmartToyOutlinedIcon
                          fontSize="small"
                          sx={isRunActive ? {
                            animation: 'pulse-green 2s ease-in-out infinite',
                            '@keyframes pulse-green': {
                              '0%, 100%': { color: 'inherit' },
                              '50%': { color: 'success.main' },
                            },
                          } : undefined}
                        />
                      )}
                    </IconButton>
                  </span>
                </Tooltip>
              )}
              <IconButton
                size="small"
                onClick={() => onEdit(localItem)}
                title="Open in edit modal"
              >
                <EditIcon fontSize="small" />
              </IconButton>
              <IconButton size="small" onClick={onClose} title="Close">
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>

            {/* Inline field error */}
            {fieldError && (
              <Alert
                severity="error"
                sx={{ mx: 2, mb: 1, whiteSpace: 'pre-wrap' }}
                onClose={() => setFieldError(null)}
              >
                {fieldError}
              </Alert>
            )}

            <Divider />

            {/* Editable description */}
            <Box
              sx={{
                px: 2,
                py: 1.5,
                maxHeight: editingDescription ? 'none' : '20vh',
                overflow: editingDescription ? 'visible' : 'auto',
              }}
            >
              {editingDescription ? (
                <TextField
                  fullWidth
                  multiline
                  minRows={3}
                  maxRows={12}
                  value={descriptionValue}
                  onChange={(e) => setDescriptionValue(e.target.value)}
                  onBlur={() => void handleDescriptionSave()}
                  onKeyDown={handleDescriptionKeyDown}
                  variant="outlined"
                  size="small"
                  disabled={isSaving}
                  placeholder="Add a description…"
                  autoFocus
                  helperText="Esc to cancel · Tab or click outside to save"
                />
              ) : localItem.description ? (
                <Box
                  component="div"
                  sx={{
                    cursor: 'text',
                    borderRadius: 0.5,
                    p: 0.5,
                    m: -0.5,
                    '&:hover': { bgcolor: 'action.hover' },
                  }}
                  onClick={() => {
                    setEditingDescription(true)
                    setDescriptionValue(localItem.description)
                  }}
                  title="Click to edit description"
                >
                  <MarkdownContent>{localItem.description}</MarkdownContent>
                  {savingField === 'description' && (
                    <CircularProgress size={12} sx={{ ml: 1, verticalAlign: 'middle' }} />
                  )}
                </Box>
              ) : (
                <Typography
                  variant="body2"
                  color="text.disabled"
                  sx={{
                    cursor: 'text',
                    fontStyle: 'italic',
                    borderRadius: 0.5,
                    p: 0.5,
                    m: -0.5,
                    '&:hover': { bgcolor: 'action.hover' },
                  }}
                  onClick={() => {
                    setEditingDescription(true)
                    setDescriptionValue('')
                  }}
                  title="Click to add a description"
                >
                  Click to add a description…
                </Typography>
              )}
            </Box>

            {/* Acceptance Criteria — rendered as an accordion when non-empty */}
            {localItem.acceptanceCriteria.length > 0 && (
              <Accordion
                expanded={acExpanded}
                onChange={(_, isExpanded) => setAcExpanded(isExpanded)}
                disableGutters
                elevation={0}
                sx={{
                  '&:before': { display: 'none' },
                  bgcolor: 'transparent',
                }}
              >
                <AccordionSummary
                  expandIcon={<ExpandMoreIcon sx={{ fontSize: 16 }} />}
                  sx={{
                    px: 2,
                    minHeight: 0,
                    '& .MuiAccordionSummary-content': { my: 0.5 },
                  }}
                >
                  <Typography variant="subtitle2">
                    Acceptance Criteria ({localItem.acceptanceCriteria.length})
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ px: 2, pt: 0.5, pb: 1.5, maxHeight: 240, overflowY: 'auto' }}>
                  <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                    {localItem.acceptanceCriteria.map((ac, i) => (
                      <Typography
                        key={i}
                        component="li"
                        variant="body2"
                        sx={{ mb: 0.25 }}
                      >
                        {ac}
                      </Typography>
                    ))}
                  </Box>
                </AccordionDetails>
              </Accordion>
            )}

            {/* Files to Modify + Out of Scope — rendered as an accordion when either is non-empty */}
            {(localItem.filesToModify.length > 0 || localItem.scopeOut.length > 0) && (
              <Accordion
                expanded={filesToModifyExpanded}
                onChange={(_, isExpanded) => setFilesToModifyExpanded(isExpanded)}
                disableGutters
                elevation={0}
                sx={{
                  '&:before': { display: 'none' },
                  bgcolor: 'transparent',
                }}
              >
                <AccordionSummary
                  expandIcon={<ExpandMoreIcon sx={{ fontSize: 16 }} />}
                  sx={{
                    px: 2,
                    minHeight: 0,
                    '& .MuiAccordionSummary-content': { my: 0.5 },
                  }}
                >
                  <Typography variant="subtitle2">
                    {localItem.filesToModify.length > 0 && localItem.scopeOut.length > 0
                      ? `Files to Modify (${localItem.filesToModify.length}) · Out of Scope (${localItem.scopeOut.length})`
                      : localItem.filesToModify.length > 0
                        ? `Files to Modify (${localItem.filesToModify.length})`
                        : `Out of Scope (${localItem.scopeOut.length})`}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ px: 2, pt: 0.5, pb: 1.5, maxHeight: 240, overflowY: 'auto' }}>
                  {/* Files to Modify table */}
                  {localItem.filesToModify.length > 0 && (
                    <Box
                      component="table"
                      sx={{
                        width: '100%',
                        borderCollapse: 'collapse',
                        fontSize: '0.75rem',
                      }}
                    >
                      <thead>
                        <tr>
                          <Box
                            component="th"
                            sx={{
                              textAlign: 'left',
                              borderBottom: 1,
                              borderColor: 'divider',
                              pb: 0.5,
                              pr: 1,
                              fontWeight: 600,
                              color: 'text.secondary',
                            }}
                          >
                            File
                          </Box>
                          <Box
                            component="th"
                            sx={{
                              textAlign: 'left',
                              borderBottom: 1,
                              borderColor: 'divider',
                              pb: 0.5,
                              fontWeight: 600,
                              color: 'text.secondary',
                            }}
                          >
                            Change
                          </Box>
                        </tr>
                      </thead>
                      <tbody>
                        {localItem.filesToModify.map((spec, i) => (
                          <tr key={i}>
                            <Box
                              component="td"
                              sx={{
                                py: 0.5,
                                pr: 1,
                                fontFamily: 'monospace',
                                verticalAlign: 'top',
                                color: 'text.primary',
                              }}
                            >
                              {spec.path ?? ''}
                            </Box>
                            <Box
                              component="td"
                              sx={{ py: 0.5, verticalAlign: 'top', color: 'text.secondary' }}
                            >
                              {spec.change ?? ''}
                            </Box>
                          </tr>
                        ))}
                      </tbody>
                    </Box>
                  )}

                  {/* Divider + Out of Scope section — only if both files and scope-out exist */}
                  {localItem.filesToModify.length > 0 && localItem.scopeOut.length > 0 && (
                    <Divider sx={{ my: 1 }} />
                  )}

                  {/* Out of Scope list */}
                  {localItem.scopeOut.length > 0 && (
                    <Box>
                      <Typography variant="caption" fontWeight={600} sx={{ display: 'block', mb: 0.5 }}>
                        Out of Scope
                      </Typography>
                      <Box component="ul" sx={{ m: 0, pl: 2 }}>
                        {localItem.scopeOut.map((item, i) => (
                          <Typography key={i} component="li" variant="caption">
                            {item}
                          </Typography>
                        ))}
                      </Box>
                    </Box>
                  )}
                </AccordionDetails>
              </Accordion>
            )}

            {/* Metadata */}
            <Box sx={{ px: 2, pb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Created {new Date(localItem.createdAt).toLocaleDateString()}
                {showAttribution && localItem.createdBy && localItem.createdBy !== 'human'
                  ? ` by ${localItem.createdBy}`
                  : ''}
              </Typography>
            </Box>

            <Divider />

            {/* Attachments section */}
            <Accordion
              expanded={attachmentsExpanded}
              onChange={(_, isExpanded) => setAttachmentsExpanded(isExpanded)}
              disableGutters
              elevation={0}
              sx={{
                '&:before': { display: 'none' },
                bgcolor: 'transparent',
              }}
            >
              <AccordionSummary
                expandIcon={<ExpandMoreIcon sx={{ fontSize: 16 }} />}
                sx={{
                  px: 2,
                  minHeight: 0,
                  '& .MuiAccordionSummary-content': { my: 0.5 },
                }}
              >
                <Typography variant="subtitle2">
                  Attachments ({attachments.length})
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ px: 2, pt: 0.5, pb: 1.5 }}>
                {/* Upload zone with optional drag-and-drop */}
                <Box
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={handleDrop}
                  sx={{ mb: 1 }}
                >
                  <label htmlFor="attachment-file-input">
                    <Button
                      component="span"
                      variant="outlined"
                      size="small"
                      disabled={uploadingAttachment}
                      startIcon={
                        uploadingAttachment ? (
                          <CircularProgress size={14} />
                        ) : (
                          <AttachFileIcon fontSize="small" />
                        )
                      }
                      sx={{ textTransform: 'none', fontSize: '0.75rem' }}
                    >
                      {uploadingAttachment ? 'Uploading…' : 'Attach file'}
                    </Button>
                  </label>
                  <input
                    id="attachment-file-input"
                    ref={fileInputRef}
                    type="file"
                    accept=".jpg,.jpeg,.png,.md,.markdown,image/jpeg,image/png,text/markdown"
                    style={{ display: 'none' }}
                    onChange={handleFileInputChange}
                    aria-label="Attach a file"
                  />
                </Box>

                {/* Upload / delete error */}
                {attachmentError && (
                  <Alert
                    severity="error"
                    onClose={() => setAttachmentError(null)}
                    sx={{ mb: 1, py: 0 }}
                  >
                    {attachmentError}
                  </Alert>
                )}

                {/* Attachment list */}
                {loadingAttachments ? (
                  <CircularProgress size={18} />
                ) : attachments.length === 0 ? (
                  <Typography variant="caption" color="text.disabled">
                    No attachments
                  </Typography>
                ) : (
                  <Box sx={{ maxHeight: 220, overflow: 'auto' }}>
                    {attachments.map((att) => {
                      const isImage = att.mimeType.startsWith('image/')
                      return (
                        <Box
                          key={att.id}
                          sx={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 1,
                            mb: 0.75,
                            p: 0.5,
                            borderRadius: 1,
                            '&:hover': { bgcolor: 'action.hover' },
                          }}
                        >
                          {/* Thumbnail or file icon */}
                          {isImage ? (
                            thumbnailUrls[att.id] ? (
                              <Box
                                component="img"
                                src={thumbnailUrls[att.id]}
                                alt={att.filename}
                                sx={{
                                  maxHeight: 80,
                                  maxWidth: 80,
                                  borderRadius: 0.5,
                                  cursor: 'pointer',
                                  objectFit: 'cover',
                                  flexShrink: 0,
                                }}
                                onClick={() => void handleOpenPreview(att)}
                              />
                            ) : (
                              <Box sx={{ width: 40, height: 40, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                <CircularProgress size={16} />
                              </Box>
                            )
                          ) : (
                            <Box
                              sx={{ cursor: 'pointer', flexShrink: 0, color: 'text.secondary' }}
                              onClick={() => void handleOpenMarkdown(att)}
                            >
                              <InsertDriveFileIcon />
                            </Box>
                          )}

                          {/* Filename + metadata */}
                          <Box
                            sx={{ flex: 1, minWidth: 0, cursor: isImage ? 'pointer' : 'pointer' }}
                            onClick={() =>
                              isImage ? void handleOpenPreview(att) : void handleOpenMarkdown(att)
                            }
                          >
                            <Typography
                              variant="caption"
                              sx={{
                                display: 'block',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                fontWeight: 500,
                              }}
                            >
                              {att.filename}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {formatFileSize(att.sizeBytes)} · {formatRelativeTime(att.createdAt)}
                            </Typography>
                          </Box>

                          {/* Delete button */}
                          <IconButton
                            size="small"
                            aria-label={`Delete attachment ${att.filename}`}
                            onClick={() => setDeleteAttachmentTarget(att)}
                            sx={{ flexShrink: 0 }}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Box>
                      )
                    })}
                  </Box>
                )}
              </AccordionDetails>
            </Accordion>

            <Divider />

            {/* Comments thread — scrollable */}
            <Box sx={{ flex: 1, overflow: 'auto', px: 2, py: 1 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Comments ({comments.length})
              </Typography>
              {loadingComments && comments.length === 0 ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
                  <CircularProgress size={20} />
                </Box>
              ) : comments.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
                  No comments yet.
                </Typography>
              ) : (
                comments.map((c) => (
                  <Box
                    key={c.id}
                    sx={{
                      mb: 1.5,
                      ...(isAgentComment(c) && {
                        pl: 1.5,
                        borderLeft: 3,
                        borderColor: 'secondary.main',
                        bgcolor: 'action.hover',
                        borderRadius: 1,
                        py: 0.5,
                      }),
                    }}
                  >
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 0.25 }}>
                      {isAgentComment(c) && (
                        <SmartToyOutlinedIcon sx={{ fontSize: 14, color: 'secondary.main' }} />
                      )}
                      <Typography variant="caption" fontWeight="bold">
                        {c.createdBy}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {new Date(c.createdAt).toLocaleString()}
                      </Typography>
                    </Box>
                    <MarkdownContent>{c.contentMarkdown}</MarkdownContent>
                  </Box>
                ))
              )}
              <div ref={commentsEndRef} />
            </Box>

            {/* Comment input — pinned to bottom */}
            <Divider />
            <Box sx={{ p: 1.5, display: 'flex', gap: 1 }}>
              <TextField
                fullWidth
                size="small"
                placeholder="Add a comment..."
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    if (newComment.trim() && !saving) handleSend()
                  }
                }}
                multiline
                maxRows={4}
              />
              <IconButton
                color="primary"
                onClick={handleSend}
                disabled={saving || !newComment.trim()}
                size="small"
              >
                {saving ? <CircularProgress size={16} /> : <SendIcon fontSize="small" />}
              </IconButton>
            </Box>
          </Box>
        )}
      </Drawer>

      {/* Image Preview Dialog */}
      <Dialog
        open={Boolean(previewAttachment)}
        onClose={handleClosePreview}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
          {previewAttachment?.filename}
          {previewAttachment && (
            <Typography variant="caption" color="text.secondary">
              {formatFileSize(previewAttachment.sizeBytes)}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent sx={{ textAlign: 'center', p: 1 }}>
          {previewBlobUrl ? (
            <Box
              component="img"
              src={previewBlobUrl}
              alt={previewAttachment?.filename ?? ''}
              sx={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain' }}
            />
          ) : (
            <CircularProgress />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClosePreview}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Delete Attachment Confirmation Dialog */}
      <Dialog
        open={Boolean(deleteAttachmentTarget)}
        onClose={() => setDeleteAttachmentTarget(null)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Delete Attachment</DialogTitle>
        <DialogContent>
          <Typography>
            Delete &ldquo;{deleteAttachmentTarget?.filename}&rdquo;? This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteAttachmentTarget(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => void handleDeleteAttachment()}
            disabled={deletingAttachment}
          >
            {deletingAttachment ? <CircularProgress size={20} /> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Dispatch Confirmation Dialog */}
      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Dispatch to Remote Agent</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Dispatch a headless agent to work on this task?
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            <strong>Task:</strong> {localItem?.title}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            <strong>Repo:</strong> {projectGitOrigin}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            <strong>Max turns:</strong> {defaultMaxTurns ?? 'server default'}
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, mt: 1.5, mb: 1 }}>
            <Button
              variant={dispatchMode === 'build' ? 'contained' : 'outlined'}
              size="small"
              onClick={() => setDispatchMode('build')}
            >
              Build
            </Button>
            <Button
              variant={dispatchMode === 'plan' ? 'contained' : 'outlined'}
              size="small"
              onClick={() => setDispatchMode('plan')}
            >
              Plan
            </Button>
          </Box>
          {dispatchHosts.length > 0 && (
            <FormControl fullWidth size="small" sx={{ mt: 1.5 }}>
              <InputLabel id="dispatch-host-label">Host</InputLabel>
              <Select
                labelId="dispatch-host-label"
                label="Host"
                value={dispatchHostId}
                onChange={(e) => setDispatchHostId(e.target.value)}
              >
                <MenuItem value="">{'(auto-route)'}</MenuItem>
                {dispatchHosts.map((h) => (
                  <MenuItem key={h.id} value={h.id}>{h.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <Typography variant="caption" color="text.secondary">
            {dispatchMode === 'build'
              ? 'Agent will implement the task and push a branch for review.'
              : 'Agent will groom the task: read codebase, write acceptance criteria, identify files.'}
          </Typography>
          {!localItem?.description && (
            <Typography variant="body2" color="warning.main" sx={{ mt: 1 }}>
              This task has no description. The agent will only have the title to work from.
            </Typography>
          )}
          {dispatchError && (
            <Typography variant="body2" color="error" sx={{ mt: 1, whiteSpace: 'pre-wrap' }}>
              {dispatchError}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => void handleDispatch(dispatchMode)}
            disabled={dispatching}
            startIcon={dispatching ? <CircularProgress size={16} /> : <SmartToyOutlinedIcon />}
          >
            {dispatchMode === 'plan' ? 'Plan' : 'Dispatch'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
