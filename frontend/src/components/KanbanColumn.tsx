import { Box, Typography, Button, Chip } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import { Droppable } from '@hello-pangea/dnd'
import KanbanCard from './KanbanCard'
import type { Item } from '../types'

interface KanbanColumnProps {
  id: string
  title: string
  items: Item[]
  onEdit: (item: Item) => void
  onDelete: (item: Item) => void
  onAdd: (columnId: string) => void
}

export default function KanbanColumn({
  id,
  title,
  items,
  onEdit,
  onDelete,
  onAdd,
}: KanbanColumnProps) {
  return (
    <Box
      sx={{
        minWidth: 240,
        maxWidth: 280,
        flex: '1 0 240px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Column header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, px: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
        <Chip label={items.length} size="small" sx={{ height: 20, minWidth: 20 }} />
      </Box>

      {/* Drop zone */}
      <Droppable droppableId={id}>
        {(provided, snapshot) => (
          <Box
            ref={provided.innerRef}
            {...provided.droppableProps}
            sx={{
              flex: 1,
              minHeight: 80,
              p: 0.5,
              borderRadius: 1,
              bgcolor: snapshot.isDraggingOver ? 'action.hover' : 'transparent',
              border: items.length === 0 && !snapshot.isDraggingOver ? '2px dashed' : 'none',
              borderColor: 'divider',
              transition: 'background-color 0.15s',
            }}
          >
            {items.map((item, index) => (
              <KanbanCard
                key={item.id}
                item={item}
                index={index}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
            {provided.placeholder}
          </Box>
        )}
      </Droppable>

      {/* Add button */}
      <Button
        size="small"
        startIcon={<AddIcon />}
        onClick={() => onAdd(id)}
        sx={{ mt: 0.5, justifyContent: 'flex-start', textTransform: 'none' }}
      >
        Add item
      </Button>
    </Box>
  )
}
