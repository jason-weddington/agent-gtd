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
import type { ApiKeyInfo, DispatchCapabilities, DispatchHost } from '../types'

export default function Settings() {
  const { mode, toggleTheme } = useThemeMode()
  const { user } = useAuth()
  const [version, setVersion] = useState<string | null>(null)

  // Agent Dispatch settings
  const [dispatchMaxTurns, setDispatchMaxTurns] = useState<number>(100)
  const [dispatchTimeoutMinutes, setDispatchTimeoutMinutes] = useState<number>(30)
  const [engine, setEngine] = useState<string>('claude-code')
  const [planAgentName, setPlanAgentName] = useState<string>('')
  const [buildAgentName, setBuildAgentName] = useState<string>('')
  const [savingDispatch, setSavingDispatch] = useState(false)
  const [capabilities, setCapabilities] = useState<DispatchCapabilities | null>(null)
  const [capabilitiesFailed, setCapabilitiesFailed] = useState(false)
  // Dispatch hosts
  const [dispatchHosts, setDispatchHosts] = useState<DispatchHost[]>([])
  const [addingHost, setAddingHost] = useState(false)
  const [hostLabel, setHostLabel] = useState('')
  const [hostUrl, setHostUrl] = useState('')
  const [hostApiKey, setHostApiKey] = useState('')
  const [hostError, setHostError] = useState<string | null>(null)

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

  const saveDispatchSettings = async (fields: {
    engine?: string
    planAgentName?: string
    buildAgentName?: string
  }) => {
    setSavingDispatch(true)
    try {
      const res = await api.settings.updateDispatch(fields)
      setEngine(res.engine)
      setPlanAgentName(res.planAgentName)
      setBuildAgentName(res.buildAgentName)
      setDispatchMaxTurns(res.defaultMaxTurns)
      setDispatchTimeoutMinutes(res.defaultTimeoutMinutes)
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
    api.settings.getDispatch().then((res) => {
      setEngine(res.engine)
      setPlanAgentName(res.planAgentName)
      setBuildAgentName(res.buildAgentName)
      setDispatchMaxTurns(res.defaultMaxTurns)
      setDispatchTimeoutMinutes(res.defaultTimeoutMinutes)
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

  const loadDispatchHosts = useCallback(() => {
    api.dispatchHosts.list().then(setDispatchHosts).catch(() => {})
  }, [])

  useEffect(() => { loadDispatchHosts() }, [loadDispatchHosts])

  const handleAddHost = async () => {
    setHostError(null)
    setAddingHost(true)
    try {
      await api.dispatchHosts.add(hostLabel, hostUrl.trim(), hostApiKey)
      setHostLabel('')
      setHostUrl('')
      setHostApiKey('')
      loadDispatchHosts()
      // Refresh capabilities after adding a host
      api.dispatch.capabilities().then(setCapabilities).catch(() => {})
    } catch (err) {
      if (err instanceof ApiError) setHostError(err.detail)
    } finally {
      setAddingHost(false)
    }
  }

  const handleRemoveHost = async (hostId: string) => {
    try {
      await api.dispatchHosts.remove(hostId)
      loadDispatchHosts()
      api.dispatch.capabilities().then(setCapabilities).catch(() => {})
    } catch {
      // handled by api client
    }
  }

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
                <MenuItem value="claude-code">Claude Code</MenuItem>
                <MenuItem value="kiro">Kiro CLI</MenuItem>
              </Select>
            </FormControl>
            {(() => {
              const knownAgentNames = capabilities?.agents.map((a) => a.name) ?? []
              const agentFieldDisabled =
                capabilitiesFailed ||
                (capabilities !== null && capabilities.agents.length === 0)
              const agentFieldHelperTextBase = capabilitiesFailed
                ? 'Dispatch service unavailable.'
                : capabilities !== null && capabilities.agents.length === 0
                  ? 'No agents advertised by the dispatch service.'
                  : null

              const makePlanOptions = (): string[] => {
                const opts: string[] = ['', ...knownAgentNames]
                if (planAgentName && !knownAgentNames.includes(planAgentName)) {
                  opts.push(planAgentName)
                }
                return opts
              }
              const makeBuildOptions = (): string[] => {
                const opts: string[] = ['', ...knownAgentNames]
                if (buildAgentName && !knownAgentNames.includes(buildAgentName)) {
                  opts.push(buildAgentName)
                }
                return opts
              }

              const getLabel = (option: string, known: string[]): string => {
                if (option === '') return 'None'
                if (!known.includes(option)) return `${option} (unknown)`
                return option
              }

              const renderAgentOption = (
                props: HTMLAttributes<HTMLLIElement> & { key: Key },
                option: string,
              ) => {
                const { key, ...liProps } = props
                if (option === '') return <li key={key} {...liProps}>None</li>
                const agent = capabilities?.agents.find((a) => a.name === option)
                return (
                  <li key={key} {...liProps}>
                    <ListItemText primary={option} secondary={agent?.description} />
                  </li>
                )
              }

              return (
                <>
                  <Autocomplete
                    size="small"
                    fullWidth
                    options={makePlanOptions()}
                    value={planAgentName}
                    disabled={agentFieldDisabled}
                    onChange={(_, newValue) => {
                      const v = newValue ?? ''
                      setPlanAgentName(v)
                      if (!savingDispatch) void saveDispatchSettings({ planAgentName: v })
                    }}
                    isOptionEqualToValue={(option, value) => option === value}
                    getOptionLabel={(option) => getLabel(option, knownAgentNames)}
                    renderOption={(props, option) =>
                      renderAgentOption(props as HTMLAttributes<HTMLLIElement> & { key: Key }, option)
                    }
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Plan Agent"
                        helperText={agentFieldHelperTextBase ?? 'Used for plan-mode dispatches'}
                      />
                    )}
                  />
                  <Autocomplete
                    size="small"
                    fullWidth
                    options={makeBuildOptions()}
                    value={buildAgentName}
                    disabled={agentFieldDisabled}
                    onChange={(_, newValue) => {
                      const v = newValue ?? ''
                      setBuildAgentName(v)
                      if (!savingDispatch) void saveDispatchSettings({ buildAgentName: v })
                    }}
                    isOptionEqualToValue={(option, value) => option === value}
                    getOptionLabel={(option) => getLabel(option, knownAgentNames)}
                    renderOption={(props, option) =>
                      renderAgentOption(props as HTMLAttributes<HTMLLIElement> & { key: Key }, option)
                    }
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Build Agent"
                        helperText={agentFieldHelperTextBase ?? 'Used for build-mode dispatches'}
                      />
                    )}
                  />
                  {capabilities !== null && !capabilitiesFailed && (
                    <Typography variant="caption" color="text.secondary" sx={{ mt: -1 }}>
                      Dispatch service: {capabilities.version ?? 'unknown'}
                    </Typography>
                  )}
                </>
              )
            })()}
          </Box>
          {/* Total Cluster Capacity chip */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Total Cluster Capacity:
            </Typography>
            <Typography variant="body2" fontWeight={600}>
              {capabilities?.totalCapacity != null ? capabilities.totalCapacity : '—'}
            </Typography>
          </Box>

          {/* Host list table */}
          {dispatchHosts.length > 0 && (
            <List dense disablePadding sx={{ mb: 2 }}>
              {dispatchHosts.map((h) => (
                <ListItem
                  key={h.id}
                  secondaryAction={
                    <IconButton edge="end" size="small" onClick={() => void handleRemoveHost(h.id)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  }
                >
                  <ListItemText
                    primary={h.label || h.url}
                    secondary={`${h.url} · ${h.apiKeyPreview}`}
                  />
                </ListItem>
              ))}
            </List>
          )}

          {/* Add Host form */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 2, maxWidth: 400 }}>
            <Typography variant="subtitle2">Add Dispatch Host</Typography>
            <TextField label="Label (optional)" size="small" fullWidth
              value={hostLabel} onChange={(e) => setHostLabel(e.target.value)} />
            <TextField label="URL" size="small" fullWidth required
              value={hostUrl}
              onChange={(e) => { setHostUrl(e.target.value); setHostError(null) }}
              placeholder="https://dispatch.example.com" />
            <TextField label="API Key" type="password" size="small" fullWidth required
              value={hostApiKey}
              onChange={(e) => { setHostApiKey(e.target.value); setHostError(null) }} />
            {hostError && <Alert severity="error">{hostError}</Alert>}
            <Button variant="outlined" size="small" onClick={() => void handleAddHost()}
              disabled={addingHost || !hostUrl.trim() || !hostApiKey.trim()}
              sx={{ alignSelf: 'flex-start' }}>
              Add Host
            </Button>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'flex-start', flexWrap: 'wrap', gap: 2 }}>
            {engine === 'claude-code' && (
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
