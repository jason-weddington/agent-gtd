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
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import { api, ApiError } from '../api'
import type { Project, ProjectStatus, DispatchAgentInfo } from '../types'

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
  const [planDispatchAgent, setPlanDispatchAgent] = useState<string | null>(null)
  const [buildDispatchAgent, setBuildDispatchAgent] = useState<string | null>(null)
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
      setPlanDispatchAgent(editing.planDispatchAgent ?? null)
      setBuildDispatchAgent(editing.buildDispatchAgent ?? null)
    } else {
      setName('')
      setDescription('')
      setStatus('active')
      setArea('')
      setGitOrigin('')
      setKbProjectRef('')
      setPlanDispatchAgent(null)
      setBuildDispatchAgent(null)
    }
    setSaveError(null)
  }, [open, editing])

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      let saved: Project
      if (editing) {
        saved = await api.projects.update(editing.id, {
          name,
          description,
          status,
          area,
          gitOrigin,
          kbProjectRef,
          planDispatchAgent,
          buildDispatchAgent,
        })
      } else {
        saved = await api.projects.create({ name, description, status, area, gitOrigin, kbProjectRef })
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
        <TextField
          fullWidth
          label="Git Origin"
          value={gitOrigin}
          onChange={(e) => setGitOrigin(e.target.value)}
          margin="normal"
          size="small"
          placeholder="e.g. git@github.com:org/repo.git"
          helperText="Repository URL for agent dispatch"
        />
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
        <Autocomplete<string | null>
          options={planOptions}
          value={planDispatchAgent}
          onChange={(_, val) => setPlanDispatchAgent(val)}
          disabled={dispatchCapabilitiesError !== null}
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
        <Autocomplete<string | null>
          options={buildOptions}
          value={buildDispatchAgent}
          onChange={(_, val) => setBuildDispatchAgent(val)}
          disabled={dispatchCapabilitiesError !== null}
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
