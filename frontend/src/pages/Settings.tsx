import { useState, useEffect, useCallback } from 'react'
import type { HTMLAttributes, Key } from 'react'
import {
  Alert,
  Autocomplete,
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
import { api, ApiError } from '../api'
import { apiKeyFieldPlaceholder } from '../utils'
import type { ApiKeyInfo, DispatchCapabilities } from '../types'

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
  const [dispatchMaxTurns, setDispatchMaxTurns] = useState<number>(100)
  const [dispatchTimeoutMinutes, setDispatchTimeoutMinutes] = useState<number>(30)
  const [maxConcurrent, setMaxConcurrent] = useState<number>(6)
  const [engine, setEngine] = useState<string>('claude')
  const [agentName, setAgentName] = useState<string>('')
  const [planAgentName, setPlanAgentName] = useState<string>('')
  const [buildAgentName, setBuildAgentName] = useState<string>('')
  const [dispatchServiceUrl, setDispatchServiceUrl] = useState('')
  const [dispatchApiKeyInput, setDispatchApiKeyInput] = useState('')
  const [dispatchApiKeyPreview, setDispatchApiKeyPreview] = useState('')
  const [savingDispatch, setSavingDispatch] = useState(false)
  const [capabilities, setCapabilities] = useState<DispatchCapabilities | null>(null)
  const [capabilitiesFailed, setCapabilitiesFailed] = useState(false)

  const handleMaxTurnsChange = (raw: string) => {
    const v = parseInt(raw, 10)
    if (isNaN(v)) return
    const clamped = Math.max(10, Math.min(500, v))
    setDispatchMaxTurns(clamped)
  }

  const handleTimeoutMinutesChange = (raw: string) => {
    const v = parseInt(raw, 10)
    if (isNaN(v)) return
    const clamped = Math.max(5, Math.min(480, v))
    setDispatchTimeoutMinutes(clamped)
  }

  const saveMaxTurns = async () => {
    try {
      const res = await api.settings.updateDispatch({ defaultMaxTurns: dispatchMaxTurns })
      setDispatchMaxTurns(res.defaultMaxTurns)
    } catch {
      // handled by api client
    }
  }

  const saveTimeoutMinutes = async () => {
    try {
      const res = await api.settings.updateDispatch({ defaultTimeoutMinutes: dispatchTimeoutMinutes })
      setDispatchTimeoutMinutes(res.defaultTimeoutMinutes)
    } catch {
      // handled by api client
    }
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
    planAgentName?: string
    buildAgentName?: string
    serviceUrl?: string
    serviceApiKey?: string
  }) => {
    setSavingDispatch(true)
    try {
      const res = await api.settings.updateDispatch(fields)
      setEngine(res.engine)
      setAgentName(res.agentName)
      setPlanAgentName(res.planAgentName)
      setBuildAgentName(res.buildAgentName)
      setDispatchMaxTurns(res.defaultMaxTurns)
      setDispatchTimeoutMinutes(res.defaultTimeoutMinutes)
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

  // Change password state
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [savingPw, setSavingPw] = useState(false)
  const [pwError, setPwError] = useState<string | null>(null)
  const [pwSuccess, setPwSuccess] = useState(false)

  const handleChangePassword = async () => {
    setPwError(null)
    setPwSuccess(false)
    if (newPw !== confirmPw) {
      setPwError('New passwords do not match.')
      return
    }
    setSavingPw(true)
    try {
      await api.auth.changePassword(currentPw, newPw)
      setPwSuccess(true)
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (err) {
      if (err instanceof ApiError) setPwError(err.detail)
    } finally {
      setSavingPw(false)
    }
  }

  // API key state
  const [apiKeys, setApiKeys] = useState<ApiKeyInfo[]>([])
  const [newApiKey, setNewApiKey] = useState<{ key: string; name: string } | null>(null)
  const [apiKeyCopied, setApiKeyCopied] = useState(false)
  const [mcpCopied, setMcpCopied] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [revokeTarget, setRevokeTarget] = useState<ApiKeyInfo | null>(null)

  useEffect(() => {
    api.config.get().then((cfg) => setVersion(cfg.version)).catch(() => {})
    api.settings.getMaxConcurrent().then((res) => setMaxConcurrent(res.value)).catch(() => {})
    api.settings.getDispatch().then((res) => {
      setEngine(res.engine)
      setAgentName(res.agentName)
      setPlanAgentName(res.planAgentName)
      setBuildAgentName(res.buildAgentName)
      setDispatchMaxTurns(res.defaultMaxTurns)
      setDispatchTimeoutMinutes(res.defaultTimeoutMinutes)
      setDispatchServiceUrl(res.serviceUrl)
      setDispatchApiKeyPreview(res.serviceApiKeyPreview)
    }).catch(() => {})
    api.dispatch.capabilities().then((caps) => {
      setCapabilities(caps)
    }).catch(() => {
      setCapabilitiesFailed(true)
    })
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

  const handleCopyMcpJson = async () => {
    if (!newApiKey) return
    const mcpJson = JSON.stringify(
      {
        mcpServers: {
          'agent-gtd': {
            command: 'uvx',
            args: ['agent-gtd-mcp'],
            env: {
              AGENT_GTD_API_KEY: newApiKey.key,
              AGENT_GTD_URL: window.location.origin,
            },
          },
        },
      },
      null,
      2,
    )
    await navigator.clipboard.writeText(mcpJson)
    setMcpCopied(true)
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
          <Divider sx={{ my: 2 }} />
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Change password</Typography>
          {pwError && <Alert severity="error" sx={{ mb: 1 }}>{pwError}</Alert>}
          {pwSuccess && <Alert severity="success" sx={{ mb: 1 }}>Password updated.</Alert>}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, maxWidth: 360 }}>
            <TextField label="Current password" type="password" size="small" fullWidth
              value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
            <TextField label="New password" type="password" size="small" fullWidth
              value={newPw} onChange={(e) => setNewPw(e.target.value)} />
            <TextField label="Confirm new password" type="password" size="small" fullWidth
              value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleChangePassword() }} />
            <Button variant="outlined" size="small" onClick={() => void handleChangePassword()}
              disabled={savingPw} sx={{ alignSelf: 'flex-start' }}>
              Update password
            </Button>
          </Box>
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
            {(() => {
              const knownAgentNames = capabilities?.agents.map((a) => a.name) ?? []
              const agentOptions: string[] = ['', ...knownAgentNames]
              if (agentName && !knownAgentNames.includes(agentName)) {
                agentOptions.push(agentName)
              }
              const agentFieldDisabled =
                capabilitiesFailed ||
                (capabilities !== null && capabilities.agents.length === 0)
              const agentFieldHelperText = capabilitiesFailed
                ? 'Dispatch service unavailable.'
                : capabilities !== null && capabilities.agents.length === 0
                  ? 'No agents advertised by the dispatch service.'
                  : 'Passed to the CLI as --agent'
              return (
                <>
                  <Autocomplete
                    size="small"
                    fullWidth
                    options={agentOptions}
                    value={agentName}
                    disabled={agentFieldDisabled}
                    onChange={(_, newValue) => {
                      const v = newValue ?? ''
                      setAgentName(v)
                      if (!savingDispatch) void saveDispatchSettings({ agentName: v })
                    }}
                    isOptionEqualToValue={(option, value) => option === value}
                    getOptionLabel={(option) => {
                      if (option === '') return 'None'
                      if (!knownAgentNames.includes(option)) return `${option} (unknown)`
                      return option
                    }}
                    renderOption={(props, option) => {
                      const { key, ...liProps } = props as HTMLAttributes<HTMLLIElement> & { key: Key }
                      if (option === '') {
                        return <li key={key} {...liProps}>None</li>
                      }
                      const agent = capabilities?.agents.find((a) => a.name === option)
                      return (
                        <li key={key} {...liProps}>
                          <ListItemText primary={option} secondary={agent?.description} />
                        </li>
                      )
                    }}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Custom agent name (optional)"
                        helperText={agentFieldHelperText}
                      />
                    )}
                  />
                  {capabilities !== null && !capabilitiesFailed && (
                    <Typography variant="caption" color="text.secondary" sx={{ mt: -1 }}>
                      Engine:{' '}
                      {capabilities.engine
                        ? `${capabilities.engine}${capabilities.version ? ` ${capabilities.version}` : ''}`
                        : 'unknown'}
                    </Typography>
                  )}
                </>
              )
            })()}
            <TextField
              label="Plan Agent"
              size="small"
              value={planAgentName}
              onChange={(e) => setPlanAgentName(e.target.value)}
              onBlur={() => {
                if (!savingDispatch) void saveDispatchSettings({ planAgentName })
              }}
              placeholder="Agent used for plan-mode runs"
              helperText="Overrides Default Agent for plan-mode runs"
              fullWidth
            />
            <TextField
              label="Build Agent"
              size="small"
              value={buildAgentName}
              onChange={(e) => setBuildAgentName(e.target.value)}
              onBlur={() => {
                if (!savingDispatch) void saveDispatchSettings({ buildAgentName })
              }}
              placeholder="Agent used for build-mode runs"
              helperText="Overrides Default Agent for build-mode runs"
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
              slotProps={{ inputLabel: { shrink: true } }}
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
                  onBlur={() => { void saveMaxTurns() }}
                  slotProps={{ htmlInput: { min: 10, max: 500 } }}
                  sx={{ width: 180 }}
                />
              </Box>
            )}
            <Box>
              <TextField
                label="Default timeout (min)"
                type="number"
                size="small"
                value={dispatchTimeoutMinutes}
                onChange={(e) => handleTimeoutMinutesChange(e.target.value)}
                onBlur={() => { void saveTimeoutMinutes() }}
                slotProps={{ htmlInput: { min: 5, max: 480 } }}
                sx={{ width: 180 }}
              />
            </Box>
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

      {/* API Key Created Dialog */}
      <Dialog
        open={newApiKey !== null}
        onClose={() => { setNewApiKey(null); setApiKeyCopied(false); setMcpCopied(false) }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>API Key Created</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            This key won't be shown again. Save it somewhere safe before closing.
          </Alert>
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              API Key
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <TextField
                fullWidth
                size="small"
                value={newApiKey?.key ?? ''}
                slotProps={{ input: { readOnly: true } }}
                sx={{ fontFamily: 'monospace' }}
              />
              <Tooltip title={apiKeyCopied ? 'Copied!' : 'Copy to clipboard'}>
                <IconButton onClick={handleCopyApiKey}>
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              MCP Server Config
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <TextField
                fullWidth
                size="small"
                multiline
                rows={10}
                value={newApiKey ? JSON.stringify(
                  {
                    mcpServers: {
                      'agent-gtd': {
                        command: 'uvx',
                        args: ['agent-gtd-mcp'],
                        env: {
                          AGENT_GTD_API_KEY: newApiKey.key,
                          AGENT_GTD_URL: window.location.origin,
                        },
                      },
                    },
                  },
                  null,
                  2,
                ) : ''}
                slotProps={{ input: { readOnly: true, sx: { fontFamily: 'monospace', fontSize: '0.75rem' } } }}
              />
              <Tooltip title={mcpCopied ? 'Copied!' : 'Copy to clipboard'}>
                <IconButton onClick={handleCopyMcpJson}>
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button
            variant="contained"
            onClick={() => { setNewApiKey(null); setApiKeyCopied(false); setMcpCopied(false) }}
          >
            Done
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
