/**
 * Tests for KanbanBoard.
 *
 * The rollout selection mode this file originally covered was removed with the
 * human rollout create/start UI path (item d6ddc1c3) — agents drive rollouts,
 * so the board is now plain drag-and-drop.
 *
 * This one assertion is deliberately kept. It is NOT about selection mode: an
 * item locked by a running rollout must still render on the board. The board
 * has no business hiding work just because a rollout holds a lock on it, and
 * nothing else asserts that. When the selection-mode tests were deleted this
 * property lost its only guard, so it is restored here on its own.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DragDropContext } from '@hello-pangea/dnd'
import KanbanBoard from '../KanbanBoard'
import type { Item } from '../../types'

vi.mock('../../api', () => ({
  api: {
    items: {
      update: vi.fn(),
    },
  },
  ApiError: class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail)
      this.name = 'ApiError'
      this.status = status
      this.detail = detail
    }
  },
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-123',
      email: 'test@example.com',
      isAdmin: false,
      createdAt: '2026-05-01T00:00:00Z',
    },
  }),
}))

function makeMockItem(overrides: Partial<Item> = {}): Item {
  return {
    id: `item-${Math.random().toString(36).slice(2, 9)}`,
    projectId: 'proj-123',
    title: 'Test item',
    description: 'Test description',
    status: 'ready',
    priority: 'normal',
    dueDate: null,
    completedAt: null,
    createdBy: 'user-123',
    assignedTo: '',
    waitingOn: '',
    sortOrder: 1000,
    labels: [],
    version: 1,
    lockedByRolloutId: null,
    buildEngine: null,
    commitType: '',
    acceptanceCriteria: [],
    filesToModify: [],
    scopeOut: [],
    createdAt: '2026-05-01T00:00:00Z',
    updatedAt: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

describe('KanbanBoard', () => {
  it('renders ready items whether or not a rollout holds a lock on them', () => {
    const unlockedReady = makeMockItem({
      id: 'item-unlocked',
      title: 'Unlocked ready item',
      status: 'ready',
      lockedByRolloutId: null,
    })
    const lockedReady = makeMockItem({
      id: 'item-locked',
      title: 'Locked ready item',
      status: 'ready',
      lockedByRolloutId: 'rollout-123',
    })

    render(
      <DragDropContext onDragEnd={() => {}}>
        <KanbanBoard
          items={[unlockedReady, lockedReady]}
          onRefresh={vi.fn()}
          onEditItem={vi.fn()}
          onDeleteItem={vi.fn()}
          onAddItem={vi.fn()}
        />
      </DragDropContext>,
    )

    expect(screen.getByText('Unlocked ready item')).toBeInTheDocument()
    expect(screen.getByText('Locked ready item')).toBeInTheDocument()
  })
})
