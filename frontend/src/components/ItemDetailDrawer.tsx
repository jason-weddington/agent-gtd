import { useState, useEffect, useRef, useCallback } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import {
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
import CloseIcon from '@mui/icons-material/Close'
import SendIcon from '@mui/icons-material/Send'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'
import { api, ApiError } from '../api'
import type { Item, Comment, Project, Run, ItemStatus } from '../types'
import { useEvents } from '../contexts/EventStreamContext'

const DRAWER_WIDTH = 440

function getDispatchMaxTurns(): number | undefined {
  const stored = localStorage.getItem('agent_gtd-dispatch-max-turns')
  if (!stored) return undefined
  const v = parseInt(stored, 10)
  return !isNaN(v) ? v : undefined
}

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
}

export default function ItemDetailDrawer({
  item,
  onClose,
  onEdit,
  onItemUpdated,
  projectName,
  projectGitOrigin,
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

  // Local item state — stays in sync with prop, then updated optimistically on each inline save
  const [localItem, setLocalItem] = useState<Item | null>(null)

  // Inline edit state
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleValue, setTitleValue] = useState('')
  const [editingDescription, setEditingDescription] = useState(false)
  const [descriptionValue, setDescriptionValue] = useState('')
  const [savingField, setSavingField] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [addingLabel, setAddingLabel] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [allProjects, setAllProjects] = useState<Project[]>([])

  const commentsEndRef = useRef<HTMLDivElement>(null)
  const { onEvent } = useEvents()

  // Sync localItem and reset inline edit state whenever a new item is opened
  useEffect(() => {
    setLocalItem(item)
    setEditingTitle(false)
    setEditingDescription(false)
    setTitleValue(item?.title ?? '')
    setDescriptionValue(item?.description ?? '')
    setFieldError(null)
    setAddingLabel(false)
    setNewLabel('')
  }, [item])

  // Load active projects once for the project dropdown
  useEffect(() => {
    api.projects.list({ status: 'active' }).then(setAllProjects).catch(() => {})
  }, [])

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

  useEffect(() => {
    if (item) {
      loadComments()
      loadActiveRun()
      setNewComment('')
      setDispatchError(null)
    } else {
      setComments([])
      setActiveRun(null)
    }
  }, [item, loadComments, loadActiveRun])

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
        setFieldError(
          err instanceof ApiError
            ? err.status === 409
              ? 'This item was updated elsewhere — refresh to see the latest version.'
              : err.detail
            : 'Failed to update',
        )
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
      const maxTurns = getDispatchMaxTurns()
      const run = await api.items.dispatch(item.id, {
        mode,
        ...(maxTurns !== undefined ? { maxTurns } : {}),
      })
      setActiveRun(run)
      setConfirmOpen(false)
      setDispatchMode('build')
      // Slide drawer up and away, then close
      setDispatchAnimating(true)
      setTimeout(() => {
        setDispatchAnimating(false)
        onClose()
      }, 380)
    } catch (err) {
      setDispatchError(err instanceof ApiError ? err.detail : 'Dispatch failed')
    } finally {
      setDispatching(false)
    }
  }, [item, localItem, dispatchMode])

  const handleCopy = () => {
    if (!item) return
    void navigator.clipboard.writeText(item.id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const isRunActive = activeRun && ['pending', 'cloning', 'running'].includes(activeRun.status)
  const canDispatch = Boolean(projectGitOrigin) && !isRunActive
  const isSaving = savingField !== null

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
            width: DRAWER_WIDTH,
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
                      {Object.entries(STATUS_LABELS).map(([value, label]) => (
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
                      {allProjects.map((p) => (
                        <MenuItem key={p.id} value={p.id} sx={{ fontSize: '0.8rem' }}>
                          {p.name}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>

                  {/* Static chips for due date, assigned to */}
                  {localItem.dueDate && (
                    <Chip label={localItem.dueDate} size="small" variant="outlined" />
                  )}
                  {localItem.assignedTo && (
                    <Chip label={`@ ${localItem.assignedTo}`} size="small" variant="outlined" />
                  )}

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
              </Box>

              {/* Action buttons */}
              {projectGitOrigin && localItem.status !== 'done' && (
                <IconButton
                  size="small"
                  onClick={() => {
                    setDispatchMode(localItem?.status === 'new' ? 'plan' : 'build')
                    setConfirmOpen(true)
                  }}
                  disabled={!canDispatch}
                  title={canDispatch ? 'Send to Claude' : isRunActive ? 'Agent is working' : 'No git origin'}
                  color="secondary"
                >
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
                </IconButton>
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
                sx={{ mx: 2, mb: 1 }}
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
                maxHeight: editingDescription ? 'none' : '30vh',
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
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{
                    whiteSpace: 'pre-wrap',
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
                  {localItem.description}
                  {savingField === 'description' && (
                    <CircularProgress size={12} sx={{ ml: 1, verticalAlign: 'middle' }} />
                  )}
                </Typography>
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

            {/* Metadata */}
            <Box sx={{ px: 2, pb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Created {new Date(localItem.createdAt).toLocaleDateString()}
                {localItem.createdBy && ` by ${localItem.createdBy}`}
              </Typography>
            </Box>

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
                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                      {c.contentMarkdown}
                    </Typography>
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

      {/* Dispatch Confirmation Dialog */}
      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Send to Claude</DialogTitle>
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
            <strong>Max turns:</strong> {getDispatchMaxTurns() ?? 'server default'}
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
            <Typography variant="body2" color="error" sx={{ mt: 1 }}>
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
