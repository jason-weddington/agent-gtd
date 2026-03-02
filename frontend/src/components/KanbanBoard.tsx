import { useState, useCallback, useMemo } from 'react'
import { Box, Chip, Typography, Collapse, IconButton } from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { DragDropProvider } from '@dnd-kit/react'
import { isSortableOperation } from '@dnd-kit/react/sortable'
import KanbanColumn from './KanbanColumn'
import { api } from '../api'
import type { Item, ItemStatus } from '../types'

/** Column definitions: id -> { title, statuses that map to this column } */
const COLUMNS = [
  { id: 'inbox', title: 'Inbox', statuses: ['inbox'] as ItemStatus[] },
  { id: 'next_action', title: 'Next Action', statuses: ['next_action'] as ItemStatus[] },
  { id: 'in_progress', title: 'In Progress', statuses: ['active', 'waiting_for', 'scheduled'] as ItemStatus[] },
  { id: 'someday', title: 'Someday', statuses: ['someday_maybe'] as ItemStatus[] },
]

/** Map a column ID to the default status when dropping into it */
const COLUMN_DEFAULT_STATUS: Record<string, ItemStatus> = {
  inbox: 'inbox',
  next_action: 'next_action',
  in_progress: 'active',
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

  // Group items into columns by status
  const columnItems = useMemo(() => {
    const grouped: Record<string, Item[]> = {}
    for (const col of COLUMNS) {
      grouped[col.id] = items
        .filter((item) => col.statuses.includes(item.status))
        .sort((a, b) => a.sortOrder - b.sortOrder)
    }
    return grouped
  }, [items])

  const doneItems = useMemo(
    () => items.filter((item) => item.status === 'done').sort((a, b) => {
      // Most recently completed first
      const aTime = a.completedAt ?? a.updatedAt
      const bTime = b.completedAt ?? b.updatedAt
      return bTime.localeCompare(aTime)
    }),
    [items],
  )

  const handleDragEnd = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async (event: any) => {
      const { operation, canceled } = event
      if (canceled || !isSortableOperation(operation)) return

      const { source, target } = operation
      if (!source || !target) return

      const srcGroup = source.initialGroup as string
      const dstGroup = (target.group ?? srcGroup) as string
      const itemId = source.id as string

      // If same column and same index, nothing to do
      if (srcGroup === dstGroup && source.initialIndex === target.index) return

      // Compute new status from destination column
      const newStatus = COLUMN_DEFAULT_STATUS[dstGroup]
      if (!newStatus) return

      // Compute new sortOrder based on destination column items
      const dstItems = columnItems[dstGroup] ?? []
      // Filter out the dragged item from destination for correct midpoint
      const filtered = dstItems.filter((i) => i.id !== itemId)
      const newSortOrder = computeSortOrder(filtered, target.index)

      // Fire API update (optimistic via SSE refresh)
      try {
        const update: Record<string, unknown> = { sortOrder: newSortOrder }
        // Only change status if moving between columns
        if (srcGroup !== dstGroup) {
          update.status = newStatus
        }
        await api.items.update(itemId, update)
      } catch {
        // Refresh to restore correct state on error
      }
      await onRefresh()
    },
    [columnItems, onRefresh],
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
      <DragDropProvider onDragEnd={handleDragEnd}>
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
      </DragDropProvider>

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
