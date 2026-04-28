import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Box,
  Card,
  CardContent,
  TextField,
  Button,
  Typography,
  InputAdornment,
  IconButton,
  Alert,
  CircularProgress,
  Container,
} from '@mui/material'
import AppsIcon from '@mui/icons-material/Apps'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'
import { api, ApiError } from '../api'

export default function ResetPassword() {
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  if (!token) {
    return (
      <Container maxWidth="sm" sx={{ mt: 8 }}>
        <Alert severity="warning">
          This page requires a password-reset link — please contact an admin.
        </Alert>
      </Container>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setSubmitting(true)
    try {
      await api.auth.passwordReset(token, newPassword)
      navigate('/login', { state: { message: 'Password reset — please log in.' } })
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400) setError('Invalid reset link.')
        else if (err.status === 410) setError('This link has expired or already been used.')
        else setError(err.detail)
      } else {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
      }}
    >
      <Card
        sx={{
          width: '100%',
          maxWidth: 400,
          bgcolor: 'background.paper',
          border: 1,
          borderColor: 'divider',
        }}
      >
        <CardContent sx={{ p: 4 }}>
          <Box sx={{ textAlign: 'center', mb: 4 }}>
            <AppsIcon
              sx={{ fontSize: 48, color: 'primary.main', mb: 1 }}
            />
            <Typography variant="h5" gutterBottom>
              Agent Gtd
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Set a new password
            </Typography>
          </Box>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
              {error}
            </Alert>
          )}

          <Box component="form" onSubmit={handleSubmit}>
            <TextField
              fullWidth
              label="New password"
              type={showPassword ? 'text' : 'password'}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              margin="normal"
              autoFocus
              required
              size="small"
              slotProps={{
                input: {
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton
                        size="small"
                        onClick={() => setShowPassword(!showPassword)}
                        edge="end"
                      >
                        {showPassword ? (
                          <VisibilityOffIcon fontSize="small" />
                        ) : (
                          <VisibilityIcon fontSize="small" />
                        )}
                      </IconButton>
                    </InputAdornment>
                  ),
                },
              }}
            />
            <TextField
              fullWidth
              label="Confirm new password"
              type={showPassword ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              margin="normal"
              required
              size="small"
              slotProps={{
                input: {
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton
                        size="small"
                        onClick={() => setShowPassword(!showPassword)}
                        edge="end"
                      >
                        {showPassword ? (
                          <VisibilityOffIcon fontSize="small" />
                        ) : (
                          <VisibilityIcon fontSize="small" />
                        )}
                      </IconButton>
                    </InputAdornment>
                  ),
                },
              }}
            />
            <Button
              fullWidth
              variant="contained"
              type="submit"
              size="large"
              disabled={submitting}
              sx={{ mt: 3, mb: 1 }}
            >
              {submitting ? (
                <CircularProgress size={24} color="inherit" />
              ) : (
                'Reset Password'
              )}
            </Button>
          </Box>
        </CardContent>
      </Card>
    </Box>
  )
}
