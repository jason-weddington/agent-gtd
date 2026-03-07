import { Box, Typography, Chip, IconButton, Tooltip } from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { useSortable } from '@dnd-kit/react/sortable'
import type { Item, Priority } from '../types'

const PRIORITY_BORDER: Record<Priority, string> = {
  low: '#9e9e9e',
  normal: '#2196f3',
  high: '#ff9800',
  urgent: '#f44336',
}

interface KanbanCardProps {
  item: Item
  index: number
  group: string
  onEdit: (item: Item) => void
  onDelete: (item: Item) => void
}

export default function KanbanCard({ item, index, group, onEdit, onDelete }: KanbanCardProps) {
  const { ref, isDragging, isDropTarget } = useSortable({
    id: item.id,
    index,
    group,
    type: 'item',
    accept: 'item',
    data: item,
    plugins: [],       // Disable OptimisticSortingPlugin — it conflicts with external state refresh
    transition: null,  // Disable sort transition — prevents fly-in glitch on cross-column drops
  })

  const isOverdue = item.dueDate && new Date(item.dueDate) < new Date()

  return (
    <Box
      ref={ref}
      onClick={() => onEdit(item)}
      sx={{
        p: 1.5,
        mb: 1,
        bgcolor: 'background.paper',
        borderRadius: 1,
        borderLeft: 3,
        borderColor: PRIORITY_BORDER[item.priority],
        boxShadow: isDragging ? 4 : 1,
        opacity: isDragging ? 0.4 : 1,
        outline: isDropTarget ? '2px solid' : 'none',
        outlineColor: 'primary.main',
        cursor: isDragging ? 'grabbing' : 'pointer',
        '&:hover .kanban-actions': { opacity: 1 },
      }}
    >
      <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
        {item.title}
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
        {item.dueDate && (
          <Chip
            label={item.dueDate}
            size="small"
            variant="outlined"
            color={isOverdue ? 'error' : 'default'}
            sx={{ height: 20, fontSize: '0.7rem' }}
          />
        )}
        {item.labels.map((label) => (
          <Chip
            key={label}
            label={label}
            size="small"
            sx={{ height: 20, fontSize: '0.7rem' }}
          />
        ))}

        <Box sx={{ flex: 1 }} />

        <Box
          className="kanban-actions"
          sx={{ opacity: 0, transition: 'opacity 0.15s', display: 'flex' }}
        >
          <Tooltip title="Edit">
            <IconButton size="small" onClick={(e) => { e.stopPropagation(); onEdit(item) }} sx={{ p: 0.25 }}>
              <EditIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete">
            <IconButton size="small" onClick={(e) => { e.stopPropagation(); onDelete(item) }} sx={{ p: 0.25 }}>
              <DeleteIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
    </Box>
  )
}
