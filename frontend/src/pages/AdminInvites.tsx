import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Button,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  Chip,
  CircularProgress,
  IconButton,
  Tooltip,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { api } from '../api'
import { ApiError } from '../api'
import type { Invite, CreatedInvite } from '../types'

export default function AdminInvites() {
  const [invites, setInvites] = useState<Invite[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // New invite dialog
  const [newDialogOpen, setNewDialogOpen] = useState(false)
  const [newNote, setNewNote] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Created invite URL dialog
  const [createdInvite, setCreatedInvite] = useState<CreatedInvite | null>(null)
  const [copied, setCopied] = useState(false)

  // Revoke dialog
  const [revokeToken, setRevokeToken] = useState<string | null>(null)
  const [revoking, setRevoking] = useState(false)

  const loadInvites = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.admin.invites.list()
      // Most-recent-first
      setInvites(data.sort((a, b) => b.createdAt.localeCompare(a.createdAt)))
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Failed to load invites.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadInvites()
  }, [loadInvites])

  const handleCreate = async () => {
    setCreateError(null)
    setCreating(true)
    try {
      const result = await api.admin.invites.create(newNote)
      setNewDialogOpen(false)
      setNewNote('')
      setCreatedInvite(result)
      setCopied(false)
      await loadInvites()
    } catch (err) {
      if (err instanceof ApiError) {
        setCreateError(err.detail)
      } else {
        setCreateError('Failed to create invite.')
      }
    } finally {
      setCreating(false)
    }
  }

  const handleRevoke = async () => {
    if (!revokeToken) return
    setRevoking(true)
    try {
      await api.admin.invites.revoke(revokeToken)
      setRevokeToken(null)
      await loadInvites()
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Failed to revoke invite.')
      }
    } finally {
      setRevoking(false)
    }
  }

  const handleCopy = async () => {
    if (!createdInvite) return
    try {
      await navigator.clipboard.writeText(createdInvite.url)
      setCopied(true)
    } catch {
      // fallback: select the text
    }
  }

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Invites
        </Typography>
        <Button variant="contained" onClick={() => { setNewDialogOpen(true); setCreateError(null); setNewNote('') }}>
          New invite
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Note</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Used by</TableCell>
                <TableCell>Used at</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {invites.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} sx={{ textAlign: 'center', color: 'text.secondary', py: 4 }}>
                    No invites yet. Create one to invite a new user.
                  </TableCell>
                </TableRow>
              ) : (
                invites.map((invite) => (
                  <TableRow key={invite.token}>
                    <TableCell sx={{ maxWidth: 200 }}>
                      <Typography variant="body2" noWrap title={invite.note}>
                        {invite.note || <span style={{ color: 'gray' }}>—</span>}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{formatDate(invite.createdAt)}</Typography>
                    </TableCell>
                    <TableCell>
                      {invite.usedAt ? (
                        <Chip label="Used" size="small" color="default" />
                      ) : (
                        <Chip label="Available" size="small" color="success" />
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{invite.usedBy ?? '—'}</Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">
                        {invite.usedAt ? formatDate(invite.usedAt) : '—'}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      {!invite.usedAt && (
                        <Tooltip title="Revoke invite">
                          <Button
                            size="small"
                            color="error"
                            variant="outlined"
                            onClick={() => setRevokeToken(invite.token)}
                          >
                            Revoke
                          </Button>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* New invite dialog */}
      <Dialog open={newDialogOpen} onClose={() => setNewDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Invite</DialogTitle>
        <DialogContent>
          {createError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {createError}
            </Alert>
          )}
          <TextField
            fullWidth
            label="Note (optional)"
            placeholder="e.g. For Alice — joining the team"
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
            margin="normal"
            size="small"
            autoFocus
            onKeyDown={(e) => { if (e.key === 'Enter') void handleCreate() }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={() => void handleCreate()} disabled={creating}>
            {creating ? <CircularProgress size={20} color="inherit" /> : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Invite created — copy URL dialog */}
      <Dialog open={createdInvite !== null} onClose={() => setCreatedInvite(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Invite Created</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Share this link with the person you want to invite. It can only be used once.
          </Typography>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              p: 1.5,
              bgcolor: 'action.hover',
              borderRadius: 1,
              border: 1,
              borderColor: 'divider',
              wordBreak: 'break-all',
            }}
          >
            <Typography variant="body2" sx={{ flexGrow: 1, fontFamily: 'monospace', fontSize: '0.8rem' }}>
              {createdInvite?.url}
            </Typography>
            <Tooltip title={copied ? 'Copied!' : 'Copy link'}>
              <IconButton size="small" onClick={() => void handleCopy()} color={copied ? 'success' : 'default'}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
          <Button
            fullWidth
            variant="contained"
            startIcon={<ContentCopyIcon />}
            onClick={() => void handleCopy()}
            sx={{ mt: 2 }}
            color={copied ? 'success' : 'primary'}
          >
            {copied ? 'Copied!' : 'Copy invite link'}
          </Button>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreatedInvite(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Revoke confirmation dialog */}
      <Dialog open={revokeToken !== null} onClose={() => setRevokeToken(null)}>
        <DialogTitle>Revoke Invite</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to revoke this invite? The link will no longer work.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRevokeToken(null)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void handleRevoke()}
            disabled={revoking}
          >
            {revoking ? <CircularProgress size={20} color="inherit" /> : 'Revoke'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
