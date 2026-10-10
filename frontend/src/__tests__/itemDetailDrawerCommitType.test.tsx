/**
 * Render test for the ItemDetailDrawer "Commit type" Select (groomed
 * squash-commit type; plan_rollout requires it). Follows the narrow-harness
 * pattern of itemDetailDrawerHostDrain.test.tsx: ItemDetailDrawer is
 * rendered directly with mocked ../api and contexts.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ItemDetailDrawer from '../components/ItemDetailDrawer'
import type { Item } from '../types'

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('../api', () => ({
  api: {
    projects: {
      list: vi.fn().mockResolvedValue([]),
      members: { list: vi.fn().mockResolvedValue([]) },
    },
    settings: {
      getDispatch: vi.fn().mockResolvedValue({
        engine: 'claude-code',
        planAgentName: '',
        buildAgentName: '',
        defaultMaxTurns: 100,
        defaultTimeoutMinutes: 90,
        managerDefaultTimeoutMinutes: 240,
        serviceUrl: '',
        serviceApiKeyPreview: '',
      }),
    },
    dispatchHosts: { list: vi.fn().mockResolvedValue([]) },
    items: {
      update: vi.fn(),
      comments: vi.fn().mockResolvedValue([]),
      runs: vi.fn().mockResolvedValue([]),
      blockers: {
        list: vi.fn().mockResolvedValue([]),
      },
    },
    attachments: { list: vi.fn().mockResolvedValue([]) },
  },
  ApiError: class ApiError extends Error {},
}))

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'test@example.com', createdAt: '2024-01-01' },
  }),
}))

vi.mock('../contexts/EventStreamContext', () => ({
  useEvents: () => ({ onEvent: vi.fn(() => vi.fn()) }),
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: 'item-1',
    projectId: 'p1',
    title: 'Do the thing',
    description: '',
    status: 'ready',
    priority: 'normal',
    dueDate: null,
    completedAt: null,
    createdBy: 'test@example.com',
    assignedTo: '',
    waitingOn: '',
    sortOrder: 0,
    labels: [],
    version: 3,
    lockedByRolloutId: null,
    buildEngine: null,
    commitType: '',
    acceptanceCriteria: [],
    filesToModify: [],
    scopeOut: [],
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

function getCommitTypeTrigger(): HTMLElement {
  const trigger = document
    .querySelector('[aria-labelledby~="drawer-commit-type-label"]')
  if (!trigger) throw new Error('Commit type Select not rendered')
  return trigger as HTMLElement
}

async function openCommitTypeSelect(item: Item) {
  render(<ItemDetailDrawer item={item} onClose={() => {}} onEdit={() => {}} />)
  const trigger = await waitFor(getCommitTypeTrigger)
  await userEvent.setup().click(trigger)
  return screen.findByRole('listbox')
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ItemDetailDrawer Commit type Select', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders Unset followed by the 7 commit types in order', async () => {
    const listbox = await openCommitTypeSelect(makeItem())

    const labels = within(listbox)
      .getAllByRole('option')
      .map((o) => o.textContent)
    expect(labels).toEqual(['Unset', 'feat', 'fix', 'perf', 'refactor', 'test', 'docs', 'chore'])
  })

  it('is not rendered for an item without a project', async () => {
    render(
      <ItemDetailDrawer item={makeItem({ projectId: null })} onClose={() => {}} onEdit={() => {}} />,
    )
    await screen.findByText('Do the thing')
    expect(document.querySelector('#drawer-commit-type-label')).toBeNull()
  })

  it('saves the chosen type via commitType', async () => {
    const api = await import('../api')
    const update = vi.mocked(api.api.items.update)
    update.mockResolvedValue(makeItem({ commitType: 'fix', version: 4 }))

    const listbox = await openCommitTypeSelect(makeItem())
    await userEvent.setup().click(within(listbox).getByRole('option', { name: 'fix' }))

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith('item-1', { commitType: 'fix', version: 3 }),
    )
  })

  it('clears the type by sending an empty string when Unset is chosen', async () => {
    const api = await import('../api')
    const update = vi.mocked(api.api.items.update)
    update.mockResolvedValue(makeItem({ version: 4 }))

    const listbox = await openCommitTypeSelect(makeItem({ commitType: 'feat' }))
    await userEvent.setup().click(within(listbox).getByRole('option', { name: 'Unset' }))

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith('item-1', { commitType: '', version: 3 }),
    )
  })
})
