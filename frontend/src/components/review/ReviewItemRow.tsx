import { useState, type ReactNode } from 'react'
import {
  Box,
  Typography,
  Chip,
  IconButton,
  Collapse,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import type { Item, Project, ItemStatus } from '../../types'

const PRIORITY_COLORS: Record<string, 'default' | 'info' | 'warning' | 'error'> = {
  low: 'default',
  normal: 'info',
  high: 'warning',
  urgent: 'error',
}

function formatRelativeAge(dateStr: string): string {
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

export interface ReviewAction {
  label: string
  icon?: ReactNode
  color?: 'inherit' | 'primary' | 'secondary' | 'success' | 'error' | 'info' | 'warning'
  onClick: (item: Item) => void
}

interface ReviewItemRowProps {
  item: Item
  projectMap: Record<string, Project>
  actions: ReviewAction[]
  onDelete?: (item: Item) => void
  /** If provided, enables inline triage (for inbox step) */
  triageConfig?: {
    projects: Project[]
    onTriage: (itemId: string, status: ItemStatus, projectId: string | null) => void
  }
  /** ID of item currently showing triage panel (controlled by parent) */
  triageOpenId?: string | null
  onTriageToggle?: (itemId: string | null) => void
}

export default function ReviewItemRow({
  item,
  projectMap,
  actions,
  onDelete,
  triageConfig,
  triageOpenId,
  onTriageToggle,
}: ReviewItemRowProps) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [triageStatus, setTriageStatus] = useState<ItemStatus>('next_action')
  const [triageProjectId, setTriageProjectId] = useState('')

  const isTriageOpen = triageOpenId === item.id

  if (confirmDelete) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          py: 1,
          px: 2,
          border: 1,
          borderColor: 'error.main',
          borderRadius: 1,
          mb: 0.5,
        }}
      >
        <Typography variant="body2" color="error">
          Delete &ldquo;{item.title}&rdquo;?
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button size="small" color="error" variant="contained" onClick={() => { onDelete?.(item); setConfirmDelete(false) }}>
            Yes
          </Button>
          <Button size="small" onClick={() => setConfirmDelete(false)}>
            No
          </Button>
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{ mb: 0.5, minWidth: 0 }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          py: 1,
          px: 2,
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          overflow: 'hidden',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, flex: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 500 }} noWrap>
            {item.title}
          </Typography>
          {item.projectId && projectMap[item.projectId] && (
            <Chip label={projectMap[item.projectId].name} size="small" variant="outlined" />
          )}
          <Chip label={item.priority} size="small" color={PRIORITY_COLORS[item.priority]} />
          <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
            {formatRelativeAge(item.createdAt)}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 1, flexShrink: 0 }}>
          {actions.map((action) => (
            <Button
              key={action.label}
              size="small"
              variant="text"
              color={action.color ?? 'primary'}
              onClick={() => action.onClick(item)}
              startIcon={action.icon}
              sx={{ minWidth: 'auto', textTransform: 'none', px: 1 }}
            >
              {action.label}
            </Button>
          ))}
          {triageConfig && (
            <Button
              size="small"
              variant={isTriageOpen ? 'contained' : 'text'}
              onClick={() => onTriageToggle?.(isTriageOpen ? null : item.id)}
              sx={{ minWidth: 'auto', textTransform: 'none', px: 1 }}
            >
              Triage
            </Button>
          )}
          {onDelete && (
            <IconButton size="small" onClick={() => setConfirmDelete(true)} title="Delete">
              <DeleteIcon fontSize="small" />
            </IconButton>
          )}
        </Box>
      </Box>

      {/* Inline triage panel */}
      {triageConfig && (
        <Collapse in={isTriageOpen}>
          <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', px: 2, py: 1.5, bgcolor: 'action.hover', borderRadius: '0 0 4px 4px' }}>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Status</InputLabel>
              <Select
                value={triageStatus}
                onChange={(e) => setTriageStatus(e.target.value as ItemStatus)}
                label="Status"
              >
                <MenuItem value="next_action">Next Action</MenuItem>
                <MenuItem value="waiting_for">Waiting For</MenuItem>
                <MenuItem value="scheduled">Scheduled</MenuItem>
                <MenuItem value="someday_maybe">Someday</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Project</InputLabel>
              <Select
                value={triageProjectId}
                onChange={(e) => setTriageProjectId(e.target.value)}
                label="Project"
              >
                <MenuItem value=""><em>None</em></MenuItem>
                {triageConfig.projects.map((p) => (
                  <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              size="small"
              variant="contained"
              onClick={() => {
                triageConfig.onTriage(item.id, triageStatus, triageProjectId || null)
                onTriageToggle?.(null)
                setTriageStatus('next_action')
                setTriageProjectId('')
              }}
            >
              Confirm
            </Button>
          </Box>
        </Collapse>
      )}
    </Box>
  )
}
