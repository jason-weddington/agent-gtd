import { memo } from 'react'
import { Box, Typography, Chip, IconButton, Tooltip, Checkbox } from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { Draggable } from '@hello-pangea/dnd'
import type { Item } from '../types'
import { PRIORITY_BORDER } from '../priorityColors'

interface KanbanCardProps {
  item: Item
  index: number
  onEdit: (item: Item) => void
  onDelete: (item: Item) => void
  selectionMode?: boolean
  isSelectable?: boolean
  isSelected?: boolean
  onToggleSelect?: (id: string) => void
}

const ENGINE_LABEL: Record<string, { label: string; color: 'warning' | 'default' }> = {
  'claude-code-ollama': { label: 'Ollama', color: 'warning' },
  'claude-code': { label: 'Anthropic', color: 'default' },
}

export default memo(function KanbanCard({
  item,
  index,
  onEdit,
  onDelete,
  selectionMode,
  isSelectable,
  isSelected,
  onToggleSelect,
}: KanbanCardProps) {
  const isOverdue = item.dueDate && new Date(item.dueDate) < new Date()
  const engineChip = item.buildEngine ? (ENGINE_LABEL[item.buildEngine] ?? { label: item.buildEngine, color: 'default' as const }) : null
  const selectableCard = selectionMode && isSelectable

  return (
    <Draggable draggableId={item.id} index={index}>
      {(provided, snapshot) => (
        <Box
          ref={provided.innerRef}
          {...provided.draggableProps}
          {...provided.dragHandleProps}
          style={{
            ...provided.draggableProps.style,
            // Make drop animation near-instant so onDragEnd fires immediately.
            ...(snapshot.isDropAnimating ? { transitionDuration: '0.001s' } : {}),
          }}
          onClick={() => selectableCard ? onToggleSelect?.(item.id) : onEdit(item)}
          sx={{
            p: 1.5,
            mb: 1,
            bgcolor: 'background.paper',
            borderRadius: 1,
            borderLeft: 3,
            borderColor: PRIORITY_BORDER[item.priority],
            boxShadow: snapshot.isDragging ? 4 : 1,
            cursor: snapshot.isDragging ? 'grabbing' : 'pointer',
            position: 'relative',
            // Promote to GPU layer to prevent Safari compositor flash
            // when switching between CPU and GPU rendering during drag.
            transform: 'translateZ(0)',
            WebkitBackfaceVisibility: 'hidden',
            backfaceVisibility: 'hidden',
            '&:hover .kanban-actions': { opacity: 1 },
          }}
        >
          {selectableCard && (
            <Checkbox
              checked={isSelected ?? false}
              size="small"
              sx={{
                position: 'absolute',
                top: 4,
                right: 4,
                p: 0.25,
              }}
              onClick={(e) => e.stopPropagation()}
              onChange={() => onToggleSelect?.(item.id)}
            />
          )}
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5, pr: selectableCard ? 3 : 0 }}>
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
            {engineChip && (
              <Chip
                label={engineChip.label}
                size="small"
                color={engineChip.color}
                sx={{ height: 20, fontSize: '0.7rem' }}
              />
            )}

            <Box sx={{ flex: 1 }} />

            <Box
              className="kanban-actions"
              sx={{ opacity: 0, transition: 'opacity 0.15s', display: selectableCard ? 'none' : 'flex' }}
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
      )}
    </Draggable>
  )
})
