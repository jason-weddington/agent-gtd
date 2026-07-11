/**
 * Tests for Runs.tsx failure feed rendering.
 *
 * AC-7: Frontend vitest tests covering Runs.tsx failures section and
 * stale section rendering (mock API responses).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import Runs from '../pages/Runs'
import type { FailedRun, StaleRun } from '../types'

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('../api', () => ({
  api: {
    runs: {
      failures: vi.fn(),
      stale: vi.fn(),
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function getApi() {
  const mod = await import('../api')
  return mod.api
}

function makeFailedRun(overrides: Partial<FailedRun> = {}): FailedRun {
  return {
    id: 'run-001',
    itemId: 'item-001',
    projectId: 'proj-001',
    status: 'failed',
    featureBranch: 'feat/test-branch',
    workspaceDir: '',
    maxTurns: 100,
    mode: 'build',
    startedAt: null,
    finishedAt: '2026-05-18T12:00:00.000Z',
    errorMsg: 'agent exited non-zero',
    createdAt: '2026-05-18T11:00:00.000Z',
    updatedAt: '2026-05-18T12:00:00.000Z',
    rolloutId: null,
    itemTitle: 'Fix login bug',
    projectName: 'My Project',
    dispatchHostUrl: undefined,
    ...overrides,
  }
}

function makeStaleRun(overrides: Partial<StaleRun> = {}): StaleRun {
  return {
    id: 'run-002',
    itemId: 'item-002',
    projectId: 'proj-001',
    status: 'success',
    featureBranch: 'feat/stale-branch',
    workspaceDir: '',
    maxTurns: 100,
    mode: 'build',
    startedAt: null,
    finishedAt: '2026-05-18T10:00:00.000Z',
    errorMsg: '',
    createdAt: '2026-05-18T09:00:00.000Z',
    updatedAt: '2026-05-18T10:00:00.000Z',
    rolloutId: null,
    itemTitle: 'Add dark mode',
    projectName: 'My Project',
    itemStatus: 'active',
    dispatchHostUrl: undefined,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Runs page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders "Failed Runs" section heading', async () => {
    const api = await getApi()
    vi.mocked(api.runs.failures).mockResolvedValue([makeFailedRun()])
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText('Failed Runs')).toBeInTheDocument()
    })
  })

  it('renders "Stale" section heading', async () => {
    const api = await getApi()
    vi.mocked(api.runs.failures).mockResolvedValue([])
    vi.mocked(api.runs.stale).mockResolvedValue([makeStaleRun()])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText(/Stale — Completed but Not Advanced/)).toBeInTheDocument()
    })
  })

  it('shows "No failed runs" empty state when failures list is empty', async () => {
    const api = await getApi()
    vi.mocked(api.runs.failures).mockResolvedValue([])
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText(/No failed runs/)).toBeInTheDocument()
    })
  })

  it('shows "No stale runs" empty state when stale list is empty', async () => {
    const api = await getApi()
    vi.mocked(api.runs.failures).mockResolvedValue([])
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText(/No stale runs/)).toBeInTheDocument()
    })
  })

  it('renders failed run data in the table', async () => {
    const api = await getApi()
    const run = makeFailedRun({ itemTitle: 'Fix the big bug', errorMsg: 'non-zero exit' })
    vi.mocked(api.runs.failures).mockResolvedValue([run])
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText('Fix the big bug')).toBeInTheDocument()
    })
    expect(screen.getByText('non-zero exit')).toBeInTheDocument()
    expect(screen.getByText('My Project')).toBeInTheDocument()
  })

  it('renders stale run data in the table', async () => {
    const api = await getApi()
    const run = makeStaleRun({ itemTitle: 'Stale feature', itemStatus: 'active' })
    vi.mocked(api.runs.failures).mockResolvedValue([])
    vi.mocked(api.runs.stale).mockResolvedValue([run])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText('Stale feature')).toBeInTheDocument()
    })
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('shows error alert when API call fails', async () => {
    const api = await getApi()
    const { ApiError } = await import('../api')
    vi.mocked(api.runs.failures).mockRejectedValue(new ApiError(500, 'Internal Server Error'))
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText('Internal Server Error')).toBeInTheDocument()
    })
  })

  it('shows failed runs count chip when there are failures', async () => {
    const api = await getApi()
    const runs = [makeFailedRun({ id: 'r1' }), makeFailedRun({ id: 'r2' })]
    vi.mocked(api.runs.failures).mockResolvedValue(runs)
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      // The chip shows the count
      expect(screen.getByText('2')).toBeInTheDocument()
    })
  })

  it('renders dispatch host URL in failed runs table when present', async () => {
    const api = await getApi()
    const run = makeFailedRun({ dispatchHostUrl: 'http://pironman01:8001' })
    vi.mocked(api.runs.failures).mockResolvedValue([run])
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText('http://pironman01:8001')).toBeInTheDocument()
    })
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
  })

  it('renders em-dash placeholder in failed runs table when host is absent', async () => {
    const api = await getApi()
    const run = makeFailedRun({ dispatchHostUrl: undefined })
    vi.mocked(api.runs.failures).mockResolvedValue([run])
    vi.mocked(api.runs.stale).mockResolvedValue([])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText('Failed Runs')).toBeInTheDocument()
    })
    // em-dash placeholder rendered; literal 'undefined' must not appear
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
  })

  it('renders dispatch host URL in stale runs table when present', async () => {
    const api = await getApi()
    const run = makeStaleRun({ dispatchHostUrl: 'http://pironman01:8001' })
    vi.mocked(api.runs.failures).mockResolvedValue([])
    vi.mocked(api.runs.stale).mockResolvedValue([run])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText('http://pironman01:8001')).toBeInTheDocument()
    })
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
  })

  it('renders em-dash placeholder in stale runs table when host is absent', async () => {
    const api = await getApi()
    const run = makeStaleRun({ dispatchHostUrl: undefined })
    vi.mocked(api.runs.failures).mockResolvedValue([])
    vi.mocked(api.runs.stale).mockResolvedValue([run])

    render(<Runs />)

    await waitFor(() => {
      expect(screen.getByText(/Stale — Completed but Not Advanced/)).toBeInTheDocument()
    })
    // em-dash placeholder rendered; literal 'undefined' must not appear
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
  })
})
