import { Box, Paper, Typography, Chip, Checkbox, IconButton, FormControlLabel } from '@mui/material'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useNavigate } from 'react-router-dom'
import type { Project, Item } from '../types'

interface ProjectReviewCardProps {
  project: Project
  items: Item[]
  reviewed: boolean
  onToggleReviewed: () => void
}

function formatRelativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diffMs = now - then
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 30) return `${diffDays}d ago`
  const diffMonths = Math.floor(diffDays / 30)
  return `${diffMonths}mo ago`
}

export default function ProjectReviewCard({
  project,
  items,
  reviewed,
  onToggleReviewed,
}: ProjectReviewCardProps) {
  const navigate = useNavigate()

  const hasNextAction = items.some((i) => i.status === 'next_action')

  const lastActivity = items.length > 0
    ? items.reduce((latest, item) =>
        item.updatedAt > latest ? item.updatedAt : latest,
      items[0].updatedAt)
    : project.updatedAt

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 1, opacity: reviewed ? 0.6 : 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <FormControlLabel
            control={<Checkbox checked={reviewed} onChange={onToggleReviewed} size="small" />}
            label={
              <Typography
                variant="subtitle2"
                sx={{
                  cursor: 'pointer',
                  '&:hover': { textDecoration: 'underline' },
                }}
                onClick={(e) => {
                  e.preventDefault()
                  navigate(`/projects/${project.id}`)
                }}
              >
                {project.name}
              </Typography>
            }
            sx={{ mr: 0 }}
          />
        </Box>
        <IconButton
          size="small"
          onClick={() => navigate(`/projects/${project.id}`)}
          title="Open project"
        >
          <OpenInNewIcon fontSize="small" />
        </IconButton>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, ml: 4 }}>
        {hasNextAction ? (
          <Chip label="Has next action" size="small" color="success" />
        ) : (
          <Chip label="No next action" size="small" color="error" />
        )}
        <Chip label={`${items.length} item${items.length !== 1 ? 's' : ''}`} size="small" variant="outlined" />
        <Typography variant="caption" color="text.secondary">
          {formatRelativeTime(lastActivity)}
        </Typography>
      </Box>
    </Paper>
  )
}
