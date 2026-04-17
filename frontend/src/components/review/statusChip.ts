import type { ItemStatus } from '../../types'

type ChipColor = 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'

/**
 * Display label for each status, matching Kanban column titles.
 * Falls back to the raw status string for unknown values.
 */
export const STATUS_CHIP_LABEL: Partial<Record<ItemStatus, string>> = {
  new: 'New',
  ready: 'Ready',
  next_action: 'Ready', // legacy value — kanban groups it into the Ready column
  active: 'In Progress',
  review: 'Review',
  waiting_for: 'Waiting',
  inbox: 'Inbox',
}

/**
 * MUI Chip color for each status.
 * Falls back to 'default' for unknown values.
 */
export const STATUS_CHIP_COLOR: Partial<Record<ItemStatus, ChipColor>> = {
  new: 'default',
  ready: 'info',
  next_action: 'info',
  active: 'primary',
  review: 'warning',
  waiting_for: 'default',
  inbox: 'default',
}
