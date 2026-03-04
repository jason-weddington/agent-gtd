import { useState } from 'react'
import {
  Box,
  Button,
  Collapse,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Switch,
  TextField,
  CircularProgress,
  Typography,
} from '@mui/material'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import CheckIcon from '@mui/icons-material/Check'
import DeleteIcon from '@mui/icons-material/Delete'
import type { Project, Priority } from '../types'

type Outcome =
  | 'next_action'
  | 'waiting_for'
  | 'scheduled'
  | 'someday_maybe'
  | 'project'
  | 'done'
  | 'trash'

export interface ProcessorResult {
  outcome: Outcome
  projectId?: string
  priority?: Priority
  waitingOn?: string
  dueDate?: string
  newProjectName?: string
  keepAsAction?: boolean
}

interface ProcessorActionsProps {
  itemTitle: string
  projects: Project[]
  onConfirm: (result: ProcessorResult) => Promise<void>
  submitting: boolean
}

export default function ProcessorActions({
  itemTitle,
  projects,
  onConfirm,
  submitting,
}: ProcessorActionsProps) {
  const [selected, setSelected] = useState<Outcome | null>(null)

  // Shared fields
  const [projectId, setProjectId] = useState('')
  const [priority, setPriority] = useState<Priority>('normal')

  // Waiting For
  const [waitingOn, setWaitingOn] = useState('')

  // Scheduled
  const [dueDate, setDueDate] = useState('')

  // Project outcome
  const [newProjectName, setNewProjectName] = useState(itemTitle)
  const [keepAsAction, setKeepAsAction] = useState(true)

  // Trash confirmation
  const [trashConfirmed, setTrashConfirmed] = useState(false)

  const handleSelect = (outcome: Outcome) => {
    if (outcome === selected) {
      setSelected(null)
      return
    }
    setSelected(outcome)
    setTrashConfirmed(false)

    // Reset fields when switching
    if (outcome === 'project') {
      setNewProjectName(itemTitle)
      setKeepAsAction(true)
    }

    // Instant outcomes
    if (outcome === 'done') {
      onConfirm({ outcome: 'done' })
    }
  }

  const handleConfirm = () => {
    if (!selected) return

    const result: ProcessorResult = { outcome: selected }

    if (selected === 'next_action' || selected === 'waiting_for' || selected === 'scheduled') {
      if (projectId) result.projectId = projectId
      result.priority = priority
    }

    if (selected === 'waiting_for') {
      result.waitingOn = waitingOn
    }

    if (selected === 'scheduled') {
      result.dueDate = dueDate
    }

    if (selected === 'someday_maybe') {
      if (projectId) result.projectId = projectId
    }

    if (selected === 'project') {
      result.newProjectName = newProjectName
      result.keepAsAction = keepAsAction
    }

    if (selected === 'trash') {
      if (!trashConfirmed) {
        setTrashConfirmed(true)
        return
      }
    }

    onConfirm(result)
  }

  const needsConfirmButton =
    selected !== null && selected !== 'done'

  const isConfirmDisabled =
    submitting ||
    (selected === 'scheduled' && !dueDate) ||
    (selected === 'project' && !newProjectName.trim())

  return (
    <Box>
      {/* Assign to project */}
      <Typography variant="overline" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
        Assign to project&hellip;
      </Typography>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr',
          gap: 1,
          mb: 2,
        }}
      >
        <Button
          variant={selected === 'next_action' ? 'contained' : 'outlined'}
          onClick={() => handleSelect('next_action')}
          disabled={submitting}
          fullWidth
        >
          Next Action
        </Button>
        <Button
          variant={selected === 'scheduled' ? 'contained' : 'outlined'}
          onClick={() => handleSelect('scheduled')}
          disabled={submitting}
          fullWidth
        >
          Scheduled
        </Button>
        <Button
          variant={selected === 'waiting_for' ? 'contained' : 'outlined'}
          onClick={() => handleSelect('waiting_for')}
          disabled={submitting}
          fullWidth
        >
          Waiting For
        </Button>
      </Box>

      {/* Other outcomes */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 1,
          mb: 2,
        }}
      >
        <Button
          variant={selected === 'someday_maybe' ? 'contained' : 'outlined'}
          onClick={() => handleSelect('someday_maybe')}
          disabled={submitting}
          fullWidth
        >
          Someday / Maybe
        </Button>
        <Button
          variant={selected === 'project' ? 'contained' : 'outlined'}
          onClick={() => handleSelect('project')}
          disabled={submitting}
          fullWidth
        >
          Convert to Project&hellip;
        </Button>
        <Button
          variant={selected === 'done' ? 'contained' : 'outlined'}
          color="success"
          onClick={() => handleSelect('done')}
          disabled={submitting}
          startIcon={<CheckIcon />}
          fullWidth
        >
          Done
        </Button>
        <Button
          variant={selected === 'trash' ? 'contained' : 'outlined'}
          color="error"
          onClick={() => handleSelect('trash')}
          disabled={submitting}
          startIcon={<DeleteIcon />}
          fullWidth
        >
          Trash
        </Button>
      </Box>

      {/* Follow-up fields for Next Action / Waiting For / Scheduled */}
      <Collapse in={selected === 'next_action' || selected === 'waiting_for' || selected === 'scheduled'}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, mb: 2 }}>
          {selected === 'waiting_for' && (
            <TextField
              fullWidth
              label="Waiting On"
              value={waitingOn}
              onChange={(e) => setWaitingOn(e.target.value)}
              size="small"
              placeholder="Who or what are you waiting on?"
            />
          )}
          {selected === 'scheduled' && (
            <TextField
              fullWidth
              label="Due Date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              size="small"
              type="date"
              slotProps={{ inputLabel: { shrink: true } }}
            />
          )}
          <FormControl fullWidth size="small">
            <InputLabel>Project</InputLabel>
            <Select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              label="Project"
            >
              <MenuItem value="">
                <em>None</em>
              </MenuItem>
              {projects.map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth size="small">
            <InputLabel>Priority</InputLabel>
            <Select
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
              label="Priority"
            >
              <MenuItem value="low">Low</MenuItem>
              <MenuItem value="normal">Normal</MenuItem>
              <MenuItem value="high">High</MenuItem>
              <MenuItem value="urgent">Urgent</MenuItem>
            </Select>
          </FormControl>
        </Box>
      </Collapse>

      {/* Follow-up fields for Someday/Maybe */}
      <Collapse in={selected === 'someday_maybe'}>
        <Box sx={{ mb: 2 }}>
          <FormControl fullWidth size="small">
            <InputLabel>Project (optional)</InputLabel>
            <Select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              label="Project (optional)"
            >
              <MenuItem value="">
                <em>None</em>
              </MenuItem>
              {projects.map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </Collapse>

      {/* Follow-up fields for Project */}
      <Collapse in={selected === 'project'}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, mb: 2 }}>
          <TextField
            fullWidth
            label="Project Name"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            size="small"
          />
          <FormControlLabel
            control={
              <Switch
                checked={keepAsAction}
                onChange={(e) => setKeepAsAction(e.target.checked)}
                size="small"
              />
            }
            label="Keep item as first action"
          />
        </Box>
      </Collapse>

      {/* Trash confirmation */}
      <Collapse in={selected === 'trash'}>
        <Box sx={{ mb: 2 }}>
          {trashConfirmed ? (
            <Typography variant="body2" color="error">
              Click confirm to delete permanently.
            </Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Click confirm to delete this item.
            </Typography>
          )}
        </Box>
      </Collapse>

      {/* Confirm button */}
      {needsConfirmButton && (
        <Button
          variant="contained"
          fullWidth
          onClick={handleConfirm}
          disabled={isConfirmDisabled}
          endIcon={submitting ? <CircularProgress size={16} /> : <ArrowForwardIcon />}
        >
          {selected === 'trash' && !trashConfirmed ? 'Delete permanently?' : 'Confirm'}
        </Button>
      )}
    </Box>
  )
}
