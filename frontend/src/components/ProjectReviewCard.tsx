import { useState } from 'react'
import { Box, Paper, Typography, Chip, IconButton, Collapse } from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import CheckIcon from '@mui/icons-material/Check'
import SnoozeIcon from '@mui/icons-material/Snooze'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import type { Project, Item } from '../types'
import ReviewItemRow, { type ReviewAction } from './review/ReviewItemRow'

interface ProjectReviewCardProps {
  project: Project
  items: Item[]
  projectMap: Record<string, Project>
  onDone: (id: string) => void
  onDelete: (id: string) => void
  onUpdateStatus: (id: string, status: string) => void
}

function formatRelativeTime(dateStr: string): string {
  const diffMs = Date.now() - new Date(dateStr).getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 30) return `${diffDays}d ago`
  return `${Math.floor(diffDays / 30)}mo ago`
}

export default function ProjectReviewCard({
  project,
  items,
  projectMap,
  onDone,
  onDelete,
  onUpdateStatus,
}: ProjectReviewCardProps) {
  const [expanded, setExpanded] = useState(false)

  const hasNextAction = items.some((i) => i.status === 'next_action')
  const isStuck = !hasNextAction && items.length > 0

  const lastActivity = items.length > 0
    ? items.reduce((latest, item) =>
        item.updatedAt > latest ? item.updatedAt : latest,
      items[0].updatedAt)
    : project.updatedAt

  // Build per-item actions based on item status
  const getItemActions = (item: Item): ReviewAction[] => {
    const itemActions: ReviewAction[] = [
      {
        label: 'Done',
        icon: <CheckIcon fontSize="small" />,
        color: 'success',
        onClick: () => onDone(item.id),
      },
    ]
    if (item.status === 'next_action') {
      itemActions.push({
        label: 'Shelve',
        icon: <SnoozeIcon fontSize="small" />,
        onClick: () => onUpdateStatus(item.id, 'someday_maybe'),
      })
    }
    if (item.status === 'someday_maybe' || item.status === 'waiting_for') {
      itemActions.push({
        label: 'Activate',
        icon: <PlayArrowIcon fontSize="small" />,
        onClick: () => onUpdateStatus(item.id, 'next_action'),
      })
    }
    return itemActions
  }

  return (
    <Paper
      variant="outlined"
      sx={{
        mb: 1,
        borderLeft: isStuck ? 3 : 1,
        borderLeftColor: isStuck ? 'warning.main' : 'divider',
        overflow: 'hidden',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          p: 2,
          cursor: 'pointer',
          '&:hover': { bgcolor: 'action.hover' },
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="subtitle2">{project.name}</Typography>
          {hasNextAction ? (
            <Chip label="Has next action" size="small" color="success" />
          ) : (
            <Chip label="No next action" size="small" color="warning" />
          )}
          <Chip label={`${items.length} item${items.length !== 1 ? 's' : ''}`} size="small" variant="outlined" />
          <Typography variant="caption" color="text.secondary">
            {formatRelativeTime(lastActivity)}
          </Typography>
        </Box>
        <IconButton
          size="small"
          sx={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
          }}
        >
          <ExpandMoreIcon />
        </IconButton>
      </Box>
      <Collapse in={expanded}>
        <Box sx={{ px: 2, pb: 2 }}>
          {items.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
              No items in this project.
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
        </Box>
      </Collapse>
    </Paper>
  )
}
