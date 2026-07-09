import { useState, useEffect } from 'react'
import {
  Autocomplete,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import { api, ApiError } from '../api'
import type { Project, ProjectStatus, DispatchAgentInfo, RepoMode } from '../types'

interface ProjectEditDialogProps {
  open: boolean
  onClose: () => void
  /** null = create mode; Project = edit mode */
  editing: Project | null
  onSaved: (project: Project) => void
}

export default function ProjectEditDialog({
  open,
  onClose,
  editing,
  onSaved,
}: ProjectEditDialogProps) {
  // Form state
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<ProjectStatus>('active')
  const [area, setArea] = useState('')
  const [gitOrigin, setGitOrigin] = useState('')
  const [kbProjectRef, setKbProjectRef] = useState('')
  const [repoMode, setRepoMode] = useState<RepoMode>('monorepo')
  const [workspaceRepos, setWorkspaceRepos] = useState<string[]>([''])
  const [planDispatchAgent, setPlanDispatchAgent] = useState<string | null>(null)
  const [buildDispatchAgent, setBuildDispatchAgent] = useState<string | null>(null)
  const [gateCommand, setGateCommand] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Dispatch capabilities/settings
  const [dispatchCapabilities, setDispatchCapabilities] = useState<DispatchAgentInfo[] | null>(null)
  const [dispatchCapabilitiesError, setDispatchCapabilitiesError] = useState<'unavailable' | 'empty' | null>(null)
  const [dispatchGlobalSettings, setDispatchGlobalSettings] = useState<{
    planAgentName: string
    buildAgentName: string
  } | null>(null)

  // Load dispatch capabilities once on mount
  useEffect(() => {
    api.dispatch.capabilities()
      .then((caps) => {
        if (caps.agents.length === 0) {
          setDispatchCapabilitiesError('empty')
        } else {
          setDispatchCapabilities(caps.agents)
        }
      })
      .catch(() => {
        setDispatchCapabilitiesError('unavailable')
      })
  }, [])

  // Load global dispatch settings once on mount
  useEffect(() => {
    api.settings.getDispatch()
      .then((res) => setDispatchGlobalSettings({
        planAgentName: res.planAgentName,
        buildAgentName: res.buildAgentName,
      }))
      .catch(() => { /* non-critical */ })
  }, [])

  // Populate form fields when the dialog opens or the editing target changes
  useEffect(() => {
    if (!open) return
    if (editing) {
      setName(editing.name)
      setDescription(editing.description)
      setStatus(editing.status)
      setArea(editing.area)
      setGitOrigin(editing.gitOrigin || '')
      setKbProjectRef(editing.kbProjectRef || '')
      setRepoMode(editing.repoMode ?? 'monorepo')
      setWorkspaceRepos(editing.workspaceRepos && editing.workspaceRepos.length > 0 ? editing.workspaceRepos : [''])
      setPlanDispatchAgent(editing.planDispatchAgent ?? null)
      setBuildDispatchAgent(editing.buildDispatchAgent ?? null)
      setGateCommand(editing.gateCommand ?? null)
    } else {
      setName('')
      setDescription('')
      setStatus('active')
      setArea('')
      setGitOrigin('')
      setKbProjectRef('')
      setRepoMode('monorepo')
      setWorkspaceRepos([''])
      setPlanDispatchAgent(null)
      setBuildDispatchAgent(null)
      setGateCommand(null)
    }
    setSaveError(null)
  }, [open, editing])

  // Non-owners cannot edit dispatch fields; undefined isOwner = treat as owner
  const isOwner = editing?.isOwner !== false

  // Pre-seed workspaceRepos[0] from gitOrigin when transitioning monorepo → workspace.
  // Only fires when: gitOrigin is non-empty AND every entry in workspaceRepos is ''.
  // All other transitions (workspace→monorepo, workspace→workspace, monorepo→monorepo) are no-ops.
  const handleRepoModeChange = (val: RepoMode) => {
    if (val === null) return
    if (val === 'workspace' && repoMode === 'monorepo') {
      const effectivelyEmpty = workspaceRepos.every((r) => r === '')
      if (gitOrigin.trim() !== '' && effectivelyEmpty) {
        setWorkspaceRepos([gitOrigin.trim()])
      }
    }
    setRepoMode(val)
  }

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true)
    setSaveError(null)
    // Trim repo URLs and drop empty rows; empty resulting list is valid.
    const trimmedRepos = workspaceRepos.map((r) => r.trim()).filter((r) => r !== '')
    try {
      let saved: Project
      if (editing) {
        // Owner-only fields: omit entirely for non-owners to avoid a 403.
        // This also fixes the pre-existing latent bug where planDispatchAgent /
        // buildDispatchAgent were always sent even for member saves.
        const ownerFields = isOwner ? {
          gitOrigin,
          repoMode,
          workspaceRepos: trimmedRepos,
          planDispatchAgent,
          buildDispatchAgent,
          gateCommand,
        } : {}
        saved = await api.projects.update(editing.id, {
          name,
          description,
          status,
          area,
          kbProjectRef,
          ...ownerFields,
        })
      } else {
        saved = await api.projects.create({
          name,
          description,
          status,
          area,
          gitOrigin,
          kbProjectRef,
          repoMode,
          workspaceRepos: trimmedRepos,
          gateCommand: gateCommand ?? undefined,
        })
      }
      onSaved(saved)
      onClose()
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.detail : 'Failed to save project')
    } finally {
      setSaving(false)
    }
  }

  // Derived Autocomplete data
  const capabilityNames = dispatchCapabilities?.map((a) => a.name) ?? []
  const capabilitiesHelperText = dispatchCapabilitiesError === 'unavailable'
    ? 'Dispatch service unavailable'
    : dispatchCapabilitiesError === 'empty'
      ? 'No agents advertised'
      : null
  const planOptions: (string | null)[] = [null, ...capabilityNames]
  const buildOptions: (string | null)[] = [null, ...capabilityNames]
  const globalPlanLabel = dispatchGlobalSettings?.planAgentName
    ? `Inherit from global (${dispatchGlobalSettings.planAgentName})`
    : 'Inherit from global (none)'
  const globalBuildLabel = dispatchGlobalSettings?.buildAgentName
    ? `Inherit from global (${dispatchGlobalSettings.buildAgentName})`
    : 'Inherit from global (none)'

  const renderDispatchOption = (
    props: React.HTMLAttributes<HTMLLIElement> & { key?: React.Key },
    option: string | null,
    globalLabel: string,
  ) => {
    const { key, ...rest } = props
    const agentInfo = option ? dispatchCapabilities?.find((a) => a.name === option) : null
    return (
      <li key={key} {...rest}>
        <Box>
          <Typography variant="body2">
            {option === null ? globalLabel : option}
          </Typography>
          {agentInfo?.description && (
            <Typography variant="caption" color="text.secondary">
              {agentInfo.description}
            </Typography>
          )}
        </Box>
      </li>
    )
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey && ((e.metaKey || e.ctrlKey) || !(e.target instanceof HTMLTextAreaElement))) {
          e.preventDefault()
          if (name.trim() && !saving) handleSave()
        }
      }}
    >
      <DialogTitle>{editing ? 'Edit Project' : 'New Project'}</DialogTitle>
      <DialogContent>
        {saveError && (
          <Typography color="error" variant="body2" sx={{ mb: 1 }}>
            {saveError}
          </Typography>
        )}
        <TextField
          fullWidth
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          margin="normal"
          autoFocus
          size="small"
          required
        />
        <TextField
          fullWidth
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          margin="normal"
          multiline
          rows={3}
          size="small"
        />
        <FormControl fullWidth margin="normal" size="small">
          <InputLabel>Status</InputLabel>
          <Select
            value={status}
            onChange={(e) => setStatus(e.target.value as ProjectStatus)}
            label="Status"
          >
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
            <MenuItem value="on_hold">On Hold</MenuItem>
            <MenuItem value="cancelled">Cancelled</MenuItem>
          </Select>
        </FormControl>
        <TextField
          fullWidth
          label="Area"
          value={area}
          onChange={(e) => setArea(e.target.value)}
          margin="normal"
          size="small"
          placeholder="e.g. work, personal, health"
        />
        <Tooltip
          title={!isOwner && editing !== null ? 'Only the project owner can edit dispatch settings' : ''}
          disableHoverListener={isOwner}
        >
          <span>
            <ToggleButtonGroup
              exclusive
              size="small"
              value={repoMode}
              onChange={(_, val) => handleRepoModeChange(val as RepoMode)}
              disabled={!isOwner && editing !== null}
              sx={{ mt: 2, mb: 0.5 }}
            >
              <ToggleButton value="monorepo">Monorepo</ToggleButton>
              <ToggleButton value="workspace">Workspace</ToggleButton>
            </ToggleButtonGroup>
          </span>
        </Tooltip>
        {repoMode !== 'workspace' ? (
          <TextField
            fullWidth
            label="Git Origin"
            value={gitOrigin}
            onChange={(e) => setGitOrigin(e.target.value)}
            margin="normal"
            size="small"
            placeholder="e.g. git@github.com:org/repo.git"
            helperText="Repository URL for agent dispatch"
            disabled={!isOwner && editing !== null}
          />
        ) : (
          <Box sx={{ mt: 1 }}>
            {workspaceRepos.map((repo, idx) => (
              <Box key={idx} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <TextField
                  fullWidth
                  label="Repo URL"
                  value={repo}
                  onChange={(e) => {
                    const next = [...workspaceRepos]
                    next[idx] = e.target.value
                    setWorkspaceRepos(next)
                  }}
                  size="small"
                  placeholder="e.g. git@github.com:org/repo.git"
                  disabled={!isOwner && editing !== null}
                />
                <IconButton
                  size="small"
                  onClick={() => {
                    const next = workspaceRepos.filter((_, i) => i !== idx)
                    setWorkspaceRepos(next.length > 0 ? next : [''])
                  }}
                  disabled={(!isOwner && editing !== null) || workspaceRepos.length === 1}
                  aria-label="Remove repo"
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
            <Button
              size="small"
              onClick={() => setWorkspaceRepos([...workspaceRepos, ''])}
              disabled={!isOwner && editing !== null}
            >
              Add repo
            </Button>
          </Box>
        )}
        <TextField
          fullWidth
          label="KB Project Ref"
          value={kbProjectRef}
          onChange={(e) => setKbProjectRef(e.target.value)}
          margin="normal"
          size="small"
          placeholder="e.g. my-project"
          helperText="Personal KB project reference for agent context"
        />
        <Tooltip
          title={!isOwner && editing !== null ? 'Only the project owner can edit dispatch settings' : ''}
          disableHoverListener={isOwner}
        >
          <span>
            <Autocomplete<string | null>
              options={planOptions}
              value={planDispatchAgent}
              onChange={(_, val) => setPlanDispatchAgent(val)}
              disabled={dispatchCapabilitiesError !== null || (!isOwner && editing !== null)}
              getOptionLabel={(option) => option === null ? globalPlanLabel : option}
              isOptionEqualToValue={(option, value) => option === value}
              renderOption={(props, option) =>
                renderDispatchOption(
                  props as React.HTMLAttributes<HTMLLIElement> & { key?: React.Key },
                  option,
                  globalPlanLabel,
                )
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Plan Agent Override"
                  size="small"
                  margin="normal"
                  helperText={capabilitiesHelperText ?? 'Agent used for plan-mode runs (overrides Dispatch Agent)'}
                />
              )}
            />
          </span>
        </Tooltip>
        <Tooltip
          title={!isOwner && editing !== null ? 'Only the project owner can edit dispatch settings' : ''}
          disableHoverListener={isOwner}
        >
          <span>
            <Autocomplete<string | null>
              options={buildOptions}
              value={buildDispatchAgent}
              onChange={(_, val) => setBuildDispatchAgent(val)}
              disabled={dispatchCapabilitiesError !== null || (!isOwner && editing !== null)}
              getOptionLabel={(option) => option === null ? globalBuildLabel : option}
              isOptionEqualToValue={(option, value) => option === value}
              renderOption={(props, option) =>
                renderDispatchOption(
                  props as React.HTMLAttributes<HTMLLIElement> & { key?: React.Key },
                  option,
                  globalBuildLabel,
                )
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Build Agent Override"
                  size="small"
                  margin="normal"
                  helperText={capabilitiesHelperText ?? 'Agent used for build-mode runs (overrides Dispatch Agent)'}
                />
              )}
            />
          </span>
        </Tooltip>
        <TextField
          label="Gate Command"
          value={gateCommand ?? ''}
          onChange={(e) => setGateCommand(e.target.value || null)}
          size="small"
          margin="normal"
          fullWidth
          helperText="Shell command that is the repo's quality gate (runs from repo root; exit 0 = green)"
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSave}
          disabled={saving || !name.trim()}
        >
          {saving ? <CircularProgress size={20} /> : editing ? 'Save' : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
