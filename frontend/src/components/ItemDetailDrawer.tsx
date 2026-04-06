import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Box,
  Drawer,
  Typography,
  Chip,
  IconButton,
  TextField,
  CircularProgress,
  Divider,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import CloseIcon from '@mui/icons-material/Close'
import SendIcon from '@mui/icons-material/Send'
import { api } from '../api'
import type { Item, Comment, ItemStatus, Priority } from '../types'
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

interface ItemDetailDrawerProps {
  item: Item | null
  onClose: () => void
  onEdit: (item: Item) => void
  projectName?: string
}

export default function ItemDetailDrawer({ item, onClose, onEdit, projectName }: ItemDetailDrawerProps) {
  const [comments, setComments] = useState<Comment[]>([])
  const [newComment, setNewComment] = useState('')
  const [saving, setSaving] = useState(false)
  const [loadingComments, setLoadingComments] = useState(false)
  const commentsEndRef = useRef<HTMLDivElement>(null)
  const { onEvent } = useEvents()

  const loadComments = useCallback(async () => {
    if (!item) return
    setLoadingComments(true)
    try {
      const data = await api.items.comments(item.id)
      setComments(data)
    } catch {
      // silently fail — comments are non-critical
    } finally {
      setLoadingComments(false)
    }
  }, [item])

  useEffect(() => {
    if (item) {
      loadComments()
      setNewComment('')
    } else {
      setComments([])
    }
  }, [item, loadComments])

  // Refresh comments on SSE events
  useEffect(() => {
    const unsubs = [
      onEvent('comment_created', () => loadComments()),
      onEvent('comment_updated', () => loadComments()),
      onEvent('comment_deleted', () => loadComments()),
    ]
    return () => unsubs.forEach((u) => u())
  }, [onEvent, loadComments])

  // Scroll to bottom when new comments arrive
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

  return (
    <Drawer
      anchor="right"
      open={Boolean(item)}
      onClose={onClose}
      variant="persistent"
      sx={{
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          boxSizing: 'border-box',
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
                {item.waitingOn && (
                  <Chip label={`Waiting: ${item.waitingOn}`} size="small" variant="outlined" />
                )}
              </Box>
            </Box>
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
                <Box key={c.id} sx={{ mb: 1.5 }}>
                  <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 0.25 }}>
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
  )
}
