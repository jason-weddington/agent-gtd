import { useState, useEffect, useCallback } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DeleteIcon from '@mui/icons-material/Delete'
import { useThemeMode } from '../contexts/ThemeContext'
import { useAuth } from '../contexts/AuthContext'
import { api } from '../api'
import { apiKeyFieldPlaceholder } from '../utils'
import type { ApiKeyInfo } from '../types'

function getInitialMaxTurns(): number {
  const stored = localStorage.getItem('agent_gtd-dispatch-max-turns')
  const parsed = stored ? parseInt(stored, 10) : NaN
  return !isNaN(parsed) && parsed >= 10 && parsed <= 500 ? parsed : 100
}

function clampInt(raw: string, min: number, max: number): number {
  const v = parseInt(raw, 10)
  if (isNaN(v)) return min
  return Math.max(min, Math.min(max, v))
}

export default function Settings() {
  const { mode, toggleTheme } = useThemeMode()
  const { user } = useAuth()
  const [version, setVersion] = useState<string | null>(null)

  // Agent Dispatch settings
  const [dispatchMaxTurns, setDispatchMaxTurns] = useState<number>(getInitialMaxTurns)
  const [maxConcurrent, setMaxConcurrent] = useState<number>(6)
  const [engine, setEngine] = useState<string>('claude')
  const [agentName, setAgentName] = useState<string>('')
  const [dispatchServiceUrl, setDispatchServiceUrl] = useState('')
  const [dispatchApiKeyInput, setDispatchApiKeyInput] = useState('')
  const [dispatchApiKeyPreview, setDispatchApiKeyPreview] = useState('')
  const [savingDispatch, setSavingDispatch] = useState(false)

  const handleMaxTurnsChange = (raw: string) => {
    const v = parseInt(raw, 10)
    if (isNaN(v)) return
    const clamped = Math.max(10, Math.min(500, v))
    setDispatchMaxTurns(clamped)
    localStorage.setItem('agent_gtd-dispatch-max-turns', String(clamped))
  }

  const saveMaxConcurrent = async () => {
    try {
      const res = await api.settings.setMaxConcurrent(maxConcurrent)
      setMaxConcurrent(res.value)
    } catch {
      // handled by api client
    }
  }

  const saveDispatchSettings = async (fields: {
    engine?: string
    agentName?: string
    serviceUrl?: string
    serviceApiKey?: string
  }) => {
    setSavingDispatch(true)
    try {
      const res = await api.settings.updateDispatch(fields)
      setEngine(res.engine)
      setAgentName(res.agentName)
      setDispatchServiceUrl(res.serviceUrl)
      setDispatchApiKeyPreview(res.serviceApiKeyPreview)
      if (fields.serviceApiKey !== undefined) {
        setDispatchApiKeyInput('')
      }
    } catch {
      // handled by api client
    } finally {
      setSavingDispatch(false)
    }
  }

  // API key state
  const [apiKeys, setApiKeys] = useState<ApiKeyInfo[]>([])
  const [newApiKey, setNewApiKey] = useState<{ key: string; name: string } | null>(null)
  const [apiKeyCopied, setApiKeyCopied] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [revokeTarget, setRevokeTarget] = useState<ApiKeyInfo | null>(null)

  useEffect(() => {
    api.config.get().then((cfg) => setVersion(cfg.version)).catch(() => {})
    api.settings.getMaxConcurrent().then((res) => setMaxConcurrent(res.value)).catch(() => {})
    api.settings.getDispatch().then((res) => {
      setEngine(res.engine)
      setAgentName(res.agentName)
      setDispatchServiceUrl(res.serviceUrl)
      setDispatchApiKeyPreview(res.serviceApiKeyPreview)
    }).catch(() => {})
  }, [])

  const loadApiKeys = useCallback(() => {
    api.apiKeys.list().then(({ keys }) => setApiKeys(keys)).catch(() => {})
  }, [])

  useEffect(() => {
    loadApiKeys()
  }, [loadApiKeys])

  const handleCreateApiKey = async () => {
    const name = newKeyName.trim() || 'Untitled'
    try {
      const { apiKey } = await api.apiKeys.create(name)
      setNewApiKey({ key: apiKey, name })
      setApiKeyCopied(false)
      setCreateDialogOpen(false)
      setNewKeyName('')
      loadApiKeys()
    } catch {
      // handled by api client
    }
  }

  const handleCopyApiKey = async () => {
    if (!newApiKey) return
    await navigator.clipboard.writeText(newApiKey.key)
    setApiKeyCopied(true)
  }

  const handleRevokeApiKey = async () => {
    if (!revokeTarget) return
    try {
      await api.apiKeys.revoke(revokeTarget.id)
      setApiKeys((prev) => prev.filter((k) => k.id !== revokeTarget.id))
      if (newApiKey && revokeTarget.name === newApiKey.name) {
        setNewApiKey(null)
      }
      setRevokeTarget(null)
    } catch {
      // handled by api client
    }
  }

  return (
    <Box sx={{ maxWidth: 600 }}>
      <Typography variant="h5" sx={{ mb: 3 }}>
        Settings
      </Typography>

      <Card sx={{ border: 1, borderColor: 'divider', mb: 3 }}>
        <CardContent>
          <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 600 }}>
            Appearance
          </Typography>
          <Box sx={{ mt: 1 }}>
            <FormControlLabel
              control={
                <Switch checked={mode === 'dark'} onChange={toggleTheme} />
              }
              label="Dark mode"
            />
          </Box>
        </CardContent>
      </Card>

      <Card sx={{ border: 1, borderColor: 'divider', mb: 3 }}>
        <CardContent>
          <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 600 }}>
            Account
          </Typography>
          <Divider sx={{ my: 1 }} />
          <Typography variant="body2" color="text.secondary">
            Email
          </Typography>
          <Typography variant="body1">
            {user?.email}
          </Typography>
        </CardContent>
      </Card>

      <Card sx={{ border: 1, borderColor: 'divider', mb: 3 }}>
        <CardContent>
          <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 600 }}>
            API Access
          </Typography>
          <Divider sx={{ my: 1 }} />
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            API keys allow MCP clients and agents to authenticate without a password.
          </Typography>

          {newApiKey && (
            <Alert
              severity="warning"
              sx={{ mb: 2 }}
              action={
                <Tooltip title={apiKeyCopied ? 'Copied!' : 'Copy to clipboard'}>
                  <IconButton size="small" onClick={handleCopyApiKey}>
                    <ContentCopyIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              }
            >
              <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                {newApiKey.name}
              </Typography>
              <Typography
                variant="body2"
                sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}
              >
                {newApiKey.key}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Copy now — it won't be shown again.
              </Typography>
            </Alert>
          )}

          {apiKeys.length > 0 && (
            <List dense disablePadding>
              {apiKeys.map((k) => (
                <ListItem
                  key={k.id}
                  secondaryAction={
                    <IconButton
                      edge="end"
                      size="small"
                      onClick={() => setRevokeTarget(k)}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  }
                >
                  <ListItemText
                    primary={k.name || 'Untitled'}
                    secondary={`agtd_...${k.hashPrefix} · ${new Date(k.createdAt).toLocaleDateString()}`}
                  />
                </ListItem>
              ))}
            </List>
          )}

          <Button
            variant="outlined"
            size="small"
            sx={{ mt: 1 }}
            onClick={() => setCreateDialogOpen(true)}
          >
            Create API Key
          </Button>
        </CardContent>
      </Card>

      <Card sx={{ border: 1, borderColor: 'divider', mb: 3 }}>
        <CardContent>
          <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 600 }}>
            Agent Dispatch
          </Typography>
          <Divider sx={{ my: 1 }} />
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Configure defaults for autonomous agent runs.
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mb: 2, maxWidth: 400 }}>
            <FormControl size="small" fullWidth>
              <InputLabel id="coding-agent-label">Coding Agent</InputLabel>
              <Select
                labelId="coding-agent-label"
                label="Coding Agent"
                value={engine}
                onChange={(e) => {
                  const next = e.target.value
                  setEngine(next)
                  void saveDispatchSettings({ engine: next })
                }}
              >
                <MenuItem value="claude">Claude Code</MenuItem>
                <MenuItem value="kiro">Kiro CLI</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label="Custom agent name (optional)"
              size="small"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              onBlur={() => {
                if (!savingDispatch) void saveDispatchSettings({ agentName })
              }}
              placeholder="Leave blank for the engine's default"
              helperText="Passed to the CLI as --agent"
              fullWidth
            />
            <TextField
              label="Dispatch service URL"
              type="url"
              size="small"
              value={dispatchServiceUrl}
              onChange={(e) => setDispatchServiceUrl(e.target.value)}
              onBlur={() => {
                if (!savingDispatch) void saveDispatchSettings({ serviceUrl: dispatchServiceUrl })
              }}
              placeholder="https://dispatch.example.com"
              fullWidth
            />
            <TextField
              label="Dispatch service API key"
              type="password"
              size="small"
              value={dispatchApiKeyInput}
              onChange={(e) => setDispatchApiKeyInput(e.target.value)}
              onBlur={() => {
                if (!savingDispatch && dispatchApiKeyInput.trim()) {
                  void saveDispatchSettings({ serviceApiKey: dispatchApiKeyInput })
                }
              }}
              placeholder={apiKeyFieldPlaceholder(dispatchApiKeyPreview)}
              fullWidth
              helperText="Leave blank to keep the existing key. Never shown after saving."
            />
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'flex-start', flexWrap: 'wrap', gap: 2 }}>
            {engine === 'claude' && (
              <Box>
                <TextField
                  label="Default max turns"
                  type="number"
                  size="small"
                  value={dispatchMaxTurns}
                  onChange={(e) => handleMaxTurnsChange(e.target.value)}
                  slotProps={{ htmlInput: { min: 10, max: 500 } }}
                  sx={{ width: 180 }}
                />
              </Box>
            )}
            <Box>
              <TextField
                label="Max concurrent runs"
                type="number"
                size="small"
                value={maxConcurrent}
                onChange={(e) => setMaxConcurrent(clampInt(e.target.value, 1, 20))}
                onBlur={() => saveMaxConcurrent()}
                slotProps={{ htmlInput: { min: 1, max: 20 } }}
                sx={{ width: 180 }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                Takes effect after service restart.
              </Typography>
            </Box>
          </Box>
        </CardContent>
      </Card>

      {version && (
        <Typography variant="body2" color="text.disabled" sx={{ mt: 3, textAlign: 'center' }}>
          v{version}
        </Typography>
      )}

      {/* Create API Key Dialog */}
      <Dialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Create API Key</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Key name"
            placeholder="e.g. claude-code"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreateApiKey()
            }}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleCreateApiKey} variant="contained">
            Create
          </Button>
        </DialogActions>
      </Dialog>

      {/* Revoke Confirmation Dialog */}
      <Dialog
        open={revokeTarget !== null}
        onClose={() => setRevokeTarget(null)}
      >
        <DialogTitle>Revoke API Key</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Revoke "{revokeTarget?.name || 'Untitled'}"? Any agents using this key
            will lose access immediately.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRevokeTarget(null)}>Cancel</Button>
          <Button onClick={handleRevokeApiKey} color="error">
            Revoke
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
