import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Typography, Button, Box } from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import InboxIcon from '@mui/icons-material/Inbox'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import ReviewItemList from './ReviewItemList'
import type { ReviewAction } from './ReviewItemRow'
import type { Item, Project, ItemStatus } from '../../types'

interface InboxReviewStepProps {
  items: Item[]
  projectMap: Record<string, Project>
  projects: Project[]
  onDone: (id: string) => void
  onDelete: (id: string) => void
  onTriage: (itemId: string, status: ItemStatus, projectId: string | null) => void
}

export default function InboxReviewStep({
  items,
  projectMap,
  projects,
  onDone,
  onDelete,
  onTriage,
}: InboxReviewStepProps) {
  const navigate = useNavigate()
  const [triageOpenId, setTriageOpenId] = useState<string | null>(null)

  const actions: ReviewAction[] = [
    {
      label: 'Done',
      icon: <CheckIcon fontSize="small" />,
      color: 'success',
      onClick: (item) => onDone(item.id),
    },
  ]

  return (
    <>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="h6">Process Inbox</Typography>
        {items.length > 0 && (
          <Button
            size="small"
            startIcon={<OpenInNewIcon />}
            onClick={() => navigate('/inbox/process', { state: { returnTo: '/review' } })}
          >
            Process one-by-one
          </Button>
        )}
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Triage each inbox item: assign a status and optional project, mark done, or delete.
      </Typography>
      <ReviewItemList
        items={items}
        projectMap={projectMap}
        actions={actions}
        onDelete={(item) => onDelete(item.id)}
        emptyIcon={<InboxIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />}
        emptyTitle="Inbox is clear"
        emptyDescription="No items to process. Nice work!"
        triageConfig={{ projects, onTriage }}
        triageOpenId={triageOpenId}
        onTriageToggle={setTriageOpenId}
      />
    </>
  )
}
