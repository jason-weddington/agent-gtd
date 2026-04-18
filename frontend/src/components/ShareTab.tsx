import { useState, useEffect, useCallback } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Snackbar,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import { api, ApiError } from '../api'
import type { MemberSummary } from '../types'

interface ShareTabProps {
  projectId: string
  isOwner: boolean
  ownerEmail?: string
}

export default function ShareTab({ projectId, isOwner, ownerEmail }: ShareTabProps) {
  const [members, setMembers] = useState<MemberSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [email, setEmail] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<string | null>(null)
  const [toastMsg, setToastMsg] = useState<string | null>(null)

  const loadMembers = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.projects.members.list(projectId)
      setMembers(data)
    } catch {
      // silently fail — may 404 if backend not yet deployed
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    loadMembers()
  }, [loadMembers])

  const handleAdd = async () => {
    const trimmed = email.trim()
    if (!trimmed) return
    setAdding(true)
    setAddError(null)
    try {
      const result = await api.projects.members.add(projectId, trimmed)
      setEmail('')
      if (result.blockersPurged && result.blockersPurged > 0) {
        setToastMsg(`${result.blockersPurged} cross-project blocker(s) were removed.`)
      }
      await loadMembers()
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 404) {
          setAddError('User not found. They must have an account to be added.')
        } else if (err.status === 422) {
          setAddError(err.detail)
        } else {
          setAddError(err.detail)
        }
      } else {
        setAddError('Failed to add member.')
      }
    } finally {
      setAdding(false)
    }
  }

  const handleRemove = async (userId: string) => {
    if (!window.confirm('Remove this member? They will lose access to the project.')) return
    setRemoveTarget(userId)
    try {
      await api.projects.members.remove(projectId, userId)
      await loadMembers()
    } catch {
      // ignore errors silently
    } finally {
      setRemoveTarget(null)
    }
  }

  if (!isOwner) {
    // Read-only view for project members
    return (
      <Box>
        {ownerEmail && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Shared by <strong>{ownerEmail}</strong>
          </Typography>
        )}
        {loading ? (
          <CircularProgress size={20} />
        ) : members.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No other members.
          </Typography>
        ) : (
          <List dense disablePadding>
            {members.map((m) => (
              <ListItem key={m.userId} disablePadding sx={{ py: 0.5 }}>
                <ListItemText
                  primary={m.email}
                  secondary={`Added ${new Date(m.addedAt).toLocaleDateString()}`}
                />
              </ListItem>
            ))}
          </List>
        )}
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Share this project
      </Typography>

      {/* Add member form */}
      <Box sx={{ display: 'flex', gap: 1, mb: 1, maxWidth: 500 }}>
        <TextField
          size="small"
          label="Share with (email address)"
          type="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
            setAddError(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !adding) void handleAdd()
          }}
          sx={{ flex: 1 }}
          disabled={adding}
          error={Boolean(addError)}
        />
        <Button
          variant="contained"
          size="small"
          onClick={() => void handleAdd()}
          disabled={adding || !email.trim()}
        >
          {adding ? <CircularProgress size={18} /> : 'Add'}
        </Button>
      </Box>

      {addError && (
        <Alert severity="error" sx={{ mb: 2, maxWidth: 500 }} onClose={() => setAddError(null)}>
          {addError}
        </Alert>
      )}

      {/* Member list */}
      {loading ? (
        <CircularProgress size={20} />
      ) : members.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
          Not shared with anyone yet.
        </Typography>
      ) : (
        <List dense disablePadding sx={{ maxWidth: 500 }}>
          {members.map((m) => (
            <ListItem
              key={m.userId}
              disablePadding
              secondaryAction={
                <Tooltip title="Remove member">
                  <span>
                    <IconButton
                      size="small"
                      edge="end"
                      onClick={() => handleRemove(m.userId)}
                      disabled={removeTarget === m.userId}
                    >
                      {removeTarget === m.userId ? (
                        <CircularProgress size={16} />
                      ) : (
                        <DeleteIcon fontSize="small" />
                      )}
                    </IconButton>
                  </span>
                </Tooltip>
              }
              sx={{ py: 0.5 }}
            >
              <ListItemText
                primary={m.email}
                secondary={`Added ${new Date(m.addedAt).toLocaleDateString()}`}
              />
            </ListItem>
          ))}
        </List>
      )}

      {/* Toast for purged blockers */}
      <Snackbar
        open={toastMsg !== null}
        autoHideDuration={5000}
        onClose={() => setToastMsg(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="info" onClose={() => setToastMsg(null)} sx={{ width: '100%' }}>
          {toastMsg}
        </Alert>
      </Snackbar>
    </Box>
  )
}
