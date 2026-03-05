import { useState } from 'react'
import {
  Typography,
  Box,
  IconButton,
  TextField,
  Chip,
  CircularProgress,
  Paper,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import FolderIcon from '@mui/icons-material/Folder'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import CheckIcon from '@mui/icons-material/Check'
import SnoozeIcon from '@mui/icons-material/Snooze'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ReviewItemRow, { type ReviewAction } from './ReviewItemRow'
import type { Item, Project } from '../../types'

interface ProjectsReviewStepProps {
  projects: Project[]
  projectItems: Record<string, Item[]>
  projectMap: Record<string, Project>
  onDone: (id: string) => void
  onDelete: (id: string) => void
  onUpdateStatus: (id: string, status: string) => void
  onAddItem: (projectId: string, title: string) => Promise<void>
}

export default function ProjectsReviewStep({
  projects,
  projectItems,
  projectMap,
  onDone,
  onDelete,
  onUpdateStatus,
  onAddItem,
}: ProjectsReviewStepProps) {
  const [projectIndex, setProjectIndex] = useState(0)
  const [addText, setAddText] = useState('')
  const [adding, setAdding] = useState(false)

  if (projects.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', py: 4 }}>
        <FolderIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
        <Typography variant="h6" color="text.secondary" gutterBottom>
          No active projects
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Create a project to start organizing your work.
        </Typography>
      </Box>
    )
  }

  const project = projects[projectIndex]
  const items = projectItems[project.id] ?? []
  const hasNextAction = items.some((i) => i.status === 'next_action')
  const isStuck = !hasNextAction && items.length > 0

  const handlePrev = () => {
    setProjectIndex((i) => Math.max(i - 1, 0))
    setAddText('')
  }
  const handleNext = () => {
    setProjectIndex((i) => Math.min(i + 1, projects.length - 1))
    setAddText('')
  }

  const handleAdd = async () => {
    const title = addText.trim()
    if (!title) return
    setAdding(true)
    try {
      await onAddItem(project.id, title)
      setAddText('')
    } finally {
      setAdding(false)
    }
  }

  const getItemActions = (item: Item): ReviewAction[] => {
    const actions: ReviewAction[] = [
      {
        label: 'Done',
        icon: <CheckIcon fontSize="small" />,
        color: 'success',
        onClick: () => onDone(item.id),
      },
    ]
    if (item.status === 'next_action') {
      actions.push({
        label: 'Shelve',
        icon: <SnoozeIcon fontSize="small" />,
        onClick: () => onUpdateStatus(item.id, 'someday_maybe'),
      })
    }
    if (item.status === 'someday_maybe' || item.status === 'waiting_for') {
      actions.push({
        label: 'Activate',
        icon: <PlayArrowIcon fontSize="small" />,
        onClick: () => onUpdateStatus(item.id, 'next_action'),
      })
    }
    return actions
  }

  return (
    <>
      <Typography variant="h6" gutterBottom>Review Projects</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Review each project: mark completed items done, add missing actions.
      </Typography>

      {/* Carousel nav */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <IconButton onClick={handlePrev} disabled={projectIndex === 0} size="small">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="body2" color="text.secondary">
          Project {projectIndex + 1} of {projects.length}
        </Typography>
        <IconButton onClick={handleNext} disabled={projectIndex === projects.length - 1} size="small">
          <ArrowForwardIcon />
        </IconButton>
      </Box>

      {/* Project card */}
      <Paper
        variant="outlined"
        sx={{
          p: 2,
          borderLeft: isStuck ? 3 : 1,
          borderLeftColor: isStuck ? 'warning.main' : 'divider',
        }}
      >
        {/* Project header */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
          <Typography variant="h6" sx={{ flex: 1 }}>{project.name}</Typography>
          <Chip
            label={`${items.length} item${items.length !== 1 ? 's' : ''}`}
            size="small"
            variant="outlined"
          />
          {isStuck && (
            <Chip
              icon={<WarningAmberIcon />}
              label="No next action"
              size="small"
              color="warning"
            />
          )}
          {hasNextAction && (
            <Chip label="Has next action" size="small" color="success" />
          )}
        </Box>

        {/* Items */}
        {items.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
            No items in this project. Add one below.
          </Typography>
        ) : (
          items.map((item) => (
            <ReviewItemRow
              key={item.id}
              item={item}
              projectMap={projectMap}
              actions={getItemActions(item)}
              onDelete={() => onDelete(item.id)}
            />
          ))
        )}

        {/* Quick add */}
        <TextField
          fullWidth
          placeholder={`Add action to ${project.name}...`}
          value={addText}
          onChange={(e) => setAddText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleAdd() }}
          disabled={adding}
          size="small"
          sx={{ mt: 1.5 }}
          slotProps={{
            input: {
              endAdornment: adding ? <CircularProgress size={20} /> : null,
            },
          }}
        />
      </Paper>
    </>
  )
}
