import { useState, useEffect, useRef, useCallback } from 'react'
import {
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
  IconButton,
  TextField,
  Typography,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import CloseIcon from '@mui/icons-material/Close'
import SendIcon from '@mui/icons-material/Send'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import { api, ApiError } from '../api'
import type { Item, Comment, Run, RunStatus, ItemStatus, Priority } from '../types'
import { useEvents } from '../contexts/EventStreamContext'

const DRAWER_WIDTH = 440

const STATUS_LABELS: Record<ItemStatus, string> = {
  inbox: 'Inbox',
  next_action: 'To Do',
  waiting_for: 'Waiting',
  someday_maybe: 'Someday',
  active: 'In Progress',
  done: 'Done',
}

const PRIORITY_COLORS: Record<Priority, 'default' | 'info' | 'warning' | 'error'> = {
  low: 'default',
  normal: 'info',
  high: 'warning',
  urgent: 'error',
}

const RUN_STATUS_COLORS: Record<RunStatus, 'default' | 'info' | 'success' | 'error' | 'warning'> = {
  pending: 'default',
  cloning: 'info',
  running: 'info',
  success: 'success',
  failed: 'error',
  timeout: 'error',
  cancelled: 'warning',
}

const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  pending: 'Queued',
  cloning: 'Cloning',
  running: 'Working',
  success: 'Done',
  failed: 'Failed',
  timeout: 'Timeout',
  cancelled: 'Cancelled',
}

function isAgentComment(c: Comment): boolean {
  const by = c.createdBy.toLowerCase()
  return by.includes('claude') || by.includes('dispatch') || by.includes('agent')
}

interface ItemDetailDrawerProps {
  item: Item | null
  onClose: () => void
  onEdit: (item: Item) => void
  projectName?: string
  projectGitOrigin?: string
}

export default function ItemDetailDrawer({
  item,
  onClose,
  onEdit,
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
  const [dispatchError, setDispatchError] = useState<string | null>(null)
  const commentsEndRef = useRef<HTMLDivElement>(null)
  const { onEvent } = useEvents()

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

  const handleDispatch = async () => {
    if (!item) return
    setDispatching(true)
    setDispatchError(null)
    try {
      const run = await api.items.dispatch(item.id)
      setActiveRun(run)
      setConfirmOpen(false)
    } catch (err) {
      setDispatchError(err instanceof ApiError ? err.detail : 'Dispatch failed')
    } finally {
      setDispatching(false)
    }
  }

  const isRunActive = activeRun && ['pending', 'cloning', 'running'].includes(activeRun.status)
  const canDispatch = Boolean(projectGitOrigin) && !isRunActive

  return (
    <>
      <Drawer
        anchor="right"
        open={Boolean(item)}
        onClose={onClose}
        variant="temporary"
        sx={{
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            top: '64px',
            height: 'calc(100% - 64px)',
          },
        }}
      >
        {item && (
          <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Header */}
            <Box sx={{ p: 2, display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <Box sx={{ flex: 1 }}>
                <Typography variant="h6" sx={{ lineHeight: 1.3 }}>{item.title}</Typography>
                <Box sx={{ display: 'flex', gap: 0.5, mt: 1, flexWrap: 'wrap' }}>
                  <Chip label={STATUS_LABELS[item.status]} size="small" variant="outlined" />
                  <Chip label={item.priority} size="small" color={PRIORITY_COLORS[item.priority]} />
                  {projectName && <Chip label={projectName} size="small" variant="outlined" />}
                  {item.dueDate && <Chip label={item.dueDate} size="small" variant="outlined" />}
                  {item.assignedTo && (
                    <Chip label={`@ ${item.assignedTo}`} size="small" variant="outlined" />
                  )}
                  {activeRun && (
                    <Chip
                      label={RUN_STATUS_LABELS[activeRun.status]}
                      size="small"
                      color={RUN_STATUS_COLORS[activeRun.status]}
                      icon={isRunActive ? <CircularProgress size={12} /> : undefined}
                    />
                  )}
                </Box>
              </Box>
              {projectGitOrigin && item.status !== 'done' && (
                <IconButton
                  size="small"
                  onClick={() => setConfirmOpen(true)}
                  disabled={!canDispatch}
                  title={canDispatch ? 'Send to Claude' : isRunActive ? 'Agent is working' : 'No git origin'}
                  color="secondary"
                >
                  <SmartToyOutlinedIcon fontSize="small" />
                </IconButton>
              )}
              <IconButton size="small" onClick={() => onEdit(item)} title="Edit">
                <EditIcon fontSize="small" />
              </IconButton>
              <IconButton size="small" onClick={onClose} title="Close">
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>

            <Divider />

            {/* Description */}
            {item.description && (
              <Box sx={{ px: 2, py: 1.5 }}>
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
                  {item.description}
                </Typography>
              </Box>
            )}

            {/* Metadata */}
            <Box sx={{ px: 2, pb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Created {new Date(item.createdAt).toLocaleDateString()}
                {item.createdBy && ` by ${item.createdBy}`}
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
            <strong>Task:</strong> {item?.title}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            <strong>Repo:</strong> {projectGitOrigin}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            <strong>Max turns:</strong> server default
          </Typography>
          {!item?.description && (
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
            onClick={handleDispatch}
            disabled={dispatching}
            startIcon={dispatching ? <CircularProgress size={16} /> : <SmartToyOutlinedIcon />}
          >
            Dispatch
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
