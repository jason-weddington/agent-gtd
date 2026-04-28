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
  Alert,
  Chip,
  CircularProgress,
  IconButton,
  Tooltip,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { api } from '../api'
import { ApiError } from '../api'
import type { AdminUser, PasswordResetIssued } from '../types'

export default function AdminUsers() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Promote dialog
  const [promoteUserId, setPromoteUserId] = useState<string | null>(null)
  const [promoting, setPromoting] = useState(false)

  // Reset link dialog (copy-URL pattern from AdminInvites)
  const [resetLink, setResetLink] = useState<PasswordResetIssued | null>(null)
  const [copied, setCopied] = useState(false)
  const [resetTargetId, setResetTargetId] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)

  // Delete dialog
  const [deleteUserId, setDeleteUserId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.admin.users.list()
      setUsers(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Failed to load users.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  const handlePromote = async () => {
    if (!promoteUserId) return
    setPromoting(true)
    try {
      await api.admin.users.promote(promoteUserId)
      setPromoteUserId(null)
      await loadUsers()
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Failed to promote user.')
      }
    } finally {
      setPromoting(false)
    }
  }

  const handleReset = async () => {
    if (!resetTargetId) return
    setResetting(true)
    try {
      const result = await api.admin.issuePasswordReset(resetTargetId)
      setResetTargetId(null)
      setResetLink(result)
      setCopied(false)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Failed to issue password reset.')
      }
    } finally {
      setResetting(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteUserId) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await api.admin.users.deleteUser(deleteUserId)
      setDeleteUserId(null)
      await loadUsers()
    } catch (err) {
      if (err instanceof ApiError) {
        setDeleteError(err.detail)
      } else {
        setDeleteError('Failed to delete user.')
      }
    } finally {
      setDeleting(false)
    }
  }

  const handleCopy = async () => {
    if (!resetLink) return
    try {
      await navigator.clipboard.writeText(resetLink.url)
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

  const promoteUser = users.find((u) => u.id === promoteUserId)
  const deleteUser = users.find((u) => u.id === deleteUserId)
  const resetUser = users.find((u) => u.id === resetTargetId)

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Users
        </Typography>
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
                <TableCell>Email</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>Joined</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} sx={{ textAlign: 'center', color: 'text.secondary', py: 4 }}>
                    No users found.
                  </TableCell>
                </TableRow>
              ) : (
                users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>
                      <Typography variant="body2">{user.email}</Typography>
                    </TableCell>
                    <TableCell>
                      {user.isAdmin ? (
                        <Chip label="Admin" size="small" color="primary" />
                      ) : (
                        <Chip label="User" size="small" color="default" />
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{formatDate(user.createdAt)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                        {!user.isAdmin && (
                          <Tooltip title="Promote to admin">
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => setPromoteUserId(user.id)}
                            >
                              Promote
                            </Button>
                          </Tooltip>
                        )}
                        <Tooltip title="Generate password reset link">
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => setResetTargetId(user.id)}
                          >
                            Reset
                          </Button>
                        </Tooltip>
                        <Tooltip title="Delete user">
                          <Button
                            size="small"
                            color="error"
                            variant="outlined"
                            onClick={() => { setDeleteUserId(user.id); setDeleteError(null) }}
                          >
                            Delete
                          </Button>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Promote confirmation dialog */}
      <Dialog open={promoteUserId !== null} onClose={() => setPromoteUserId(null)}>
        <DialogTitle>Promote to Admin</DialogTitle>
        <DialogContent>
          <Typography>
            Promote <strong>{promoteUser?.email}</strong> to admin? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPromoteUserId(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => void handlePromote()}
            disabled={promoting}
          >
            {promoting ? <CircularProgress size={20} color="inherit" /> : 'Promote'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Reset password confirmation dialog */}
      <Dialog open={resetTargetId !== null} onClose={() => setResetTargetId(null)}>
        <DialogTitle>Reset Password</DialogTitle>
        <DialogContent>
          <Typography>
            Generate a one-time password reset link for <strong>{resetUser?.email}</strong>? The link expires in 12 hours.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetTargetId(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => void handleReset()}
            disabled={resetting}
          >
            {resetting ? <CircularProgress size={20} color="inherit" /> : 'Generate link'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Password reset link — copy URL dialog */}
      <Dialog open={resetLink !== null} onClose={() => setResetLink(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Password Reset Link</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Share this link with the user to let them reset their password. It expires in 12 hours and can only be used once.
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
              {resetLink?.url}
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
            {copied ? 'Copied!' : 'Copy reset link'}
          </Button>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetLink(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteUserId !== null} onClose={() => setDeleteUserId(null)}>
        <DialogTitle>Delete User</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Permanently delete <strong>{deleteUser?.email}</strong>? This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteUserId(null)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void handleDelete()}
            disabled={deleting}
          >
            {deleting ? <CircularProgress size={20} color="inherit" /> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
