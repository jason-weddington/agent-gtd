/**
 * Narrow-harness render test for the drain indicator in the ItemDetailDrawer
 * host Select (docs/host-drain.md — peer visibility for every consumer).
 *
 * Per AC, this follows the ProjectNavRegression.test.tsx pattern: a full
 * ProjectDetail render is impractical, so ItemDetailDrawer is rendered
 * directly with mocked ../api and contexts. The host Select lives inside the
 * "Dispatch Confirmation Dialog", which is only mounted after the dispatch
 * (SmartToy) IconButton is clicked — so the harness clicks it first.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
        serviceUrl: 'http://dispatch.example.com',
        serviceApiKeyPreview: '****key1',
      }),
    },
    dispatchHosts: { list: vi.fn().mockResolvedValue([]) },
    items: {
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
    version: 1,
    lockedByRolloutId: null,
    buildEngine: null,
    acceptanceCriteria: [],
    filesToModify: [],
    scopeOut: [],
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeHost(drainReason: string | null) {
  return {
    id: 'host-1',
    label: 'pironman01',
    url: 'http://pironman01.local:8100',
    drainReason,
    apiKeyPreview: '****key1',
    capabilityLabels: [],
    createdAt: '2024-01-01T00:00:00Z',
  }
}

async function openDispatchDialog(drainReason: string | null) {
  const api = await import('../api')
  const list = vi.mocked(api.api.dispatchHosts.list)
  list.mockResolvedValue([makeHost(drainReason)])

  render(
    <ItemDetailDrawer
      item={makeItem()}
      onClose={() => {}}
      onEdit={() => {}}
      projectDispatchSource="https://github.com/example/repo"
    />,
  )

  // The dispatch (SmartToy) IconButton has no accessible name; find it via
  // the icon's stable data-testid rendered by @mui/icons-material.
  const dispatchButton = await waitFor(() => {
    const btn = document.querySelector(
      'button svg[data-testid="SmartToyOutlinedIcon"]',
    )?.closest('button')
    if (!btn) throw new Error('dispatch button not rendered yet')
    return btn as HTMLElement
  })
  await userEvent.setup().click(dispatchButton)

  // Confirm the dialog is open.
  await screen.findByText('Dispatch to Remote Agent')

  // MUI mounts the Select's MenuItems only while the menu is open — open the
  // host Select (scoped to the confirm dialog, not the drawer's own selects).
  const dialogRoot = document
    .querySelector('.MuiDialog-paper')!
    .closest('.MuiDialog-root')
  const selectTrigger = dialogRoot?.querySelector(
    '[aria-haspopup="listbox"]',
  ) as HTMLElement | null
  if (!selectTrigger) throw new Error('host Select not rendered')
  await userEvent.setup().click(selectTrigger)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ItemDetailDrawer host Select drain indicator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the draining suffix for a host with a drainReason', async () => {
    await openDispatchDialog('rolling deploy 2.0.2')

    expect(
      await screen.findByText('pironman01 — draining: rolling deploy 2.0.2'),
    ).toBeInTheDocument()
  })

  it('renders no draining suffix for a host with a null drainReason', async () => {
    await openDispatchDialog(null)

    expect(await screen.findByText('pironman01')).toBeInTheDocument()
    expect(screen.queryByText(/draining:/)).not.toBeInTheDocument()
  })
})
