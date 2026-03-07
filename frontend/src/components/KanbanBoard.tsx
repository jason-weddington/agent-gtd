import { useState, useCallback, useMemo } from 'react'
import { flushSync } from 'react-dom'
import { Box, Chip, Typography, Collapse, IconButton } from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { DragDropContext, type DropResult } from '@hello-pangea/dnd'
import KanbanColumn from './KanbanColumn'
import { api } from '../api'
import type { Item, ItemStatus } from '../types'

/** Column definitions */
const COLUMNS = [
  { id: 'next_action', title: 'To Do', statuses: ['next_action'] as ItemStatus[] },
  { id: 'in_progress', title: 'In Progress', statuses: ['active', 'scheduled'] as ItemStatus[] },
  { id: 'waiting_for', title: 'Waiting', statuses: ['waiting_for'] as ItemStatus[] },
  { id: 'someday', title: 'Someday', statuses: ['someday_maybe'] as ItemStatus[] },
]

/** Map a column ID to the default status when dropping into it */
const COLUMN_DEFAULT_STATUS: Record<string, ItemStatus> = {
  next_action: 'next_action',
  in_progress: 'active',
  waiting_for: 'waiting_for',
  someday: 'someday_maybe',
}

/** Compute the midpoint sortOrder between two items, or at start/end */
function computeSortOrder(items: Item[], targetIndex: number): number {
  if (items.length === 0) return 1000
  if (targetIndex <= 0) return items[0].sortOrder - 1000
  if (targetIndex >= items.length) return items[items.length - 1].sortOrder + 1000
  return (items[targetIndex - 1].sortOrder + items[targetIndex].sortOrder) / 2
}

interface KanbanBoardProps {
  items: Item[]
  onRefresh: () => Promise<void>
  onEditItem: (item: Item) => void
  onDeleteItem: (item: Item) => void
  onAddItem: (status: ItemStatus) => void
}

export default function KanbanBoard({
  items,
  onRefresh,
  onEditItem,
  onDeleteItem,
  onAddItem,
}: KanbanBoardProps) {
  const [doneExpanded, setDoneExpanded] = useState(false)
  // Optimistic override — applied instantly on drop so cards don't pop back to source column
  const [optimistic, setOptimistic] = useState<Item[] | null>(null)
  const displayItems = optimistic ?? items

  // Group items into columns by status
  const columnItems = useMemo(() => {
    const grouped: Record<string, Item[]> = {}
    for (const col of COLUMNS) {
      grouped[col.id] = displayItems
        .filter((item) => col.statuses.includes(item.status))
        .sort((a, b) => a.sortOrder - b.sortOrder)
    }
    return grouped
  }, [displayItems])

  const doneItems = useMemo(
    () => displayItems.filter((item) => item.status === 'done').sort((a, b) => {
      const aTime = a.completedAt ?? a.updatedAt
      const bTime = b.completedAt ?? b.updatedAt
      return bTime.localeCompare(aTime)
    }),
    [displayItems],
  )

  const handleDragEnd = useCallback(
    async (result: DropResult) => {
      const { source, destination, draggableId } = result
      if (!destination) return

      // Dropped in same position
      if (source.droppableId === destination.droppableId && source.index === destination.index) return

      const dstColumnId = destination.droppableId
      const newStatus = COLUMN_DEFAULT_STATUS[dstColumnId]
      if (!newStatus) return

      // Compute sortOrder from destination column items (excluding the dragged item)
      const dstItems = (columnItems[dstColumnId] ?? []).filter((i) => i.id !== draggableId)
      const newSortOrder = computeSortOrder(dstItems, destination.index)

      // Optimistic update — flushSync forces React to paint before the browser
      // renders the intermediate state (card back in source column)
      flushSync(() => {
        setOptimistic(
          items.map((item) =>
            item.id === draggableId
              ? { ...item, status: newStatus, sortOrder: newSortOrder }
              : item,
          ),
        )
      })

      try {
        await api.items.update(draggableId, { status: newStatus, sortOrder: newSortOrder })
      } catch {
        // API error — refresh will restore correct state
      }
      setOptimistic(null)
      await onRefresh()
    },
    [columnItems, items, onRefresh],
  )

  const handleAddToColumn = useCallback(
    (columnId: string) => {
      const status = COLUMN_DEFAULT_STATUS[columnId]
      if (status) onAddItem(status)
    },
    [onAddItem],
  )

  return (
    <Box>
      <DragDropContext onDragEnd={handleDragEnd}>
        <Box
          sx={{
            display: 'flex',
            gap: 2,
            overflowX: 'auto',
            pb: 2,
            minHeight: 200,
          }}
        >
          {COLUMNS.map((col) => (
            <KanbanColumn
              key={col.id}
              id={col.id}
              title={col.title}
              items={columnItems[col.id] ?? []}
              onEdit={onEditItem}
              onDelete={onDeleteItem}
              onAdd={handleAddToColumn}
            />
          ))}
        </Box>
      </DragDropContext>

      {/* Done section (collapsed) */}
      <Box sx={{ mt: 1, borderTop: 1, borderColor: 'divider', pt: 1 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            cursor: 'pointer',
          }}
          onClick={() => setDoneExpanded(!doneExpanded)}
        >
          <Typography variant="subtitle2" color="text.secondary">
            Done
          </Typography>
          <Chip label={doneItems.length} size="small" sx={{ height: 20, minWidth: 20 }} />
          <IconButton size="small">
            {doneExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
          </IconButton>
        </Box>
        <Collapse in={doneExpanded}>
          <Box sx={{ mt: 1, pl: 1 }}>
            {doneItems.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No completed items
              </Typography>
            ) : (
              doneItems.map((item) => (
                <Typography
                  key={item.id}
                  variant="body2"
                  sx={{ textDecoration: 'line-through', color: 'text.secondary', py: 0.25 }}
                >
                  {item.title}
                </Typography>
              ))
            )}
          </Box>
        </Collapse>
      </Box>
    </Box>
  )
}
