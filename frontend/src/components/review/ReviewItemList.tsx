import { Box, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import ReviewItemRow, { type ReviewAction } from './ReviewItemRow'
import type { Item, Project, ItemStatus } from '../../types'

interface ReviewItemListProps {
  items: Item[]
  projectMap: Record<string, Project>
  actions: ReviewAction[]
  onDelete?: (item: Item) => void
  emptyIcon?: ReactNode
  emptyTitle: string
  emptyDescription: string
  /** Inbox triage config */
  triageConfig?: {
    projects: Project[]
    onTriage: (itemId: string, status: ItemStatus, projectId: string | null) => void
  }
  triageOpenId?: string | null
  onTriageToggle?: (itemId: string | null) => void
}

export default function ReviewItemList({
  items,
  projectMap,
  actions,
  onDelete,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  triageConfig,
  triageOpenId,
  onTriageToggle,
}: ReviewItemListProps) {
  if (items.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', py: 4 }}>
        {emptyIcon}
        <Typography variant="h6" color="text.secondary" gutterBottom>
          {emptyTitle}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {emptyDescription}
        </Typography>
      </Box>
    )
  }

  return (
    <Box>
      {items.map((item) => (
        <ReviewItemRow
          key={item.id}
          item={item}
          projectMap={projectMap}
          actions={actions}
          onDelete={onDelete}
          triageConfig={triageConfig}
          triageOpenId={triageOpenId}
          onTriageToggle={onTriageToggle}
        />
      ))}
    </Box>
  )
}
