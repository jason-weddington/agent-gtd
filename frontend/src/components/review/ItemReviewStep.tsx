import { type ReactNode } from 'react'
import { Typography } from '@mui/material'
import ReviewItemList from './ReviewItemList'
import type { ReviewAction } from './ReviewItemRow'
import type { Item, Project } from '../../types'

interface ItemReviewStepProps {
  title: string
  description: string
  items: Item[]
  projectMap: Record<string, Project>
  actions: ReviewAction[]
  onDelete: (id: string) => void
  /** If provided, clicking a row body opens the item detail drawer */
  onItemClick?: (item: Item) => void
  emptyIcon: ReactNode
  emptyTitle: string
  emptyDescription: string
}

export default function ItemReviewStep({
  title,
  description,
  items,
  projectMap,
  actions,
  onDelete,
  onItemClick,
  emptyIcon,
  emptyTitle,
  emptyDescription,
}: ItemReviewStepProps) {
  return (
    <>
      <Typography variant="h6" gutterBottom>{title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {description}
      </Typography>
      <ReviewItemList
        items={items}
        projectMap={projectMap}
        actions={actions}
        onDelete={(item) => onDelete(item.id)}
        onItemClick={onItemClick}
        emptyIcon={emptyIcon}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
      />
    </>
  )
}
