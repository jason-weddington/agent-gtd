import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BlockerPicker } from '../BlockerPicker'
import type { BlockerSummary } from '../../types'

// ---------------------------------------------------------------------------
// Mock the api module.  vi.mock() is hoisted so both the component and the
// test body get the same mocked instances.
// ---------------------------------------------------------------------------
vi.mock('../../api', () => ({
  api: {
    items: {
      search: vi.fn(),
      blockers: {
        add: vi.fn(),
        remove: vi.fn(),
        list: vi.fn(),
      },
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

import { api, ApiError } from '../../api'

const mockSearch = vi.mocked(api.items.search)
const mockAdd = vi.mocked(api.items.blockers.add)
const mockRemove = vi.mocked(api.items.blockers.remove)

const ITEM_ID = 'ffffffff-ffff-ffff-ffff-ffffffffffff'

const blocker1: BlockerSummary = {
  id: 'aaaaaaaa-1111-1111-1111-111111111111',
  title: 'Fix the auth bug',
  status: 'active',
  projectId: 'proj-alpha',
  projectName: 'Alpha',
}

const blocker2: BlockerSummary = {
  id: 'bbbbbbbb-2222-2222-2222-222222222222',
  title: 'Write documentation',
  status: 'done',
  projectId: null,
  projectName: null,
}

const candidate: BlockerSummary = {
  id: 'cccccccc-3333-3333-3333-333333333333',
  title: 'New blocker candidate',
  status: 'new',
  projectId: null,
  projectName: null,
}

describe('BlockerPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearch.mockResolvedValue([])
    mockAdd.mockResolvedValue(candidate)
    mockRemove.mockResolvedValue(undefined)
  })

  // -------------------------------------------------------------------------
  // 1. Renders existing blockers as chips
  // -------------------------------------------------------------------------
  it('renders existing blockers as chips', () => {
    render(
      <BlockerPicker
        itemId={ITEM_ID}
        blockers={[blocker1, blocker2]}
        onChange={vi.fn()}
      />,
    )

    expect(
      screen.getByTitle(`${blocker1.id} | Alpha | Fix the auth bug`),
    ).toBeInTheDocument()
    expect(
      screen.getByTitle(`${blocker2.id} | — | Write documentation`),
    ).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // 2. Clicking X calls api.items.blockers.remove and invokes onChange
  // -------------------------------------------------------------------------
  it('clicking X triggers api.items.blockers.remove and calls onChange', async () => {
    const onChange = vi.fn()
    render(
      <BlockerPicker itemId={ITEM_ID} blockers={[blocker1]} onChange={onChange} />,
    )

    const removeBtn = screen.getByLabelText('Remove blocker')
    await userEvent.click(removeBtn)

    await waitFor(() => {
      expect(mockRemove).toHaveBeenCalledWith(ITEM_ID, blocker1.id)
      expect(onChange).toHaveBeenCalledWith([])
    })
  })

  // -------------------------------------------------------------------------
  // 3. Typing in the autocomplete calls api.items.search with 250 ms debounce
  // -------------------------------------------------------------------------
  describe('debounced search', () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('does not call search before 250ms and calls it after', async () => {
      render(<BlockerPicker itemId={ITEM_ID} blockers={[]} onChange={vi.fn()} />)

      // Open the picker
      fireEvent.click(screen.getByRole('button', { name: /add blocker/i }))

      const input = screen.getByRole('combobox')
      fireEvent.change(input, { target: { value: 'test query' } })

      // Not called immediately
      expect(mockSearch).not.toHaveBeenCalled()

      // Just before 250ms — still not called
      act(() => { vi.advanceTimersByTime(249) })
      expect(mockSearch).not.toHaveBeenCalled()

      // At 250ms the debounce fires; use async act to flush the microtask queue
      // so the async timeout callback runs fully (mockSearch is called sync
      // before any await inside the callback).
      await act(async () => { vi.advanceTimersByTime(1) })
      expect(mockSearch).toHaveBeenCalledWith('test query')
    })

    it('resets the debounce timer on each keystroke (calls search only once)', async () => {
      render(<BlockerPicker itemId={ITEM_ID} blockers={[]} onChange={vi.fn()} />)

      fireEvent.click(screen.getByRole('button', { name: /add blocker/i }))
      const input = screen.getByRole('combobox')

      // Rapid keystrokes — each should reset the timer
      fireEvent.change(input, { target: { value: 'a' } })
      act(() => { vi.advanceTimersByTime(100) })
      fireEvent.change(input, { target: { value: 'ab' } })
      act(() => { vi.advanceTimersByTime(100) })
      fireEvent.change(input, { target: { value: 'abc' } })
      act(() => { vi.advanceTimersByTime(100) })

      // 300ms total elapsed but each keystroke reset the clock — not called yet
      expect(mockSearch).not.toHaveBeenCalled()

      // Fire the final debounce; flush microtasks via async act
      await act(async () => { vi.advanceTimersByTime(150) })
      expect(mockSearch).toHaveBeenCalledTimes(1)
      expect(mockSearch).toHaveBeenCalledWith('abc')
    })
  })

  // -------------------------------------------------------------------------
  // 4. Selecting an option calls api.items.blockers.add
  // -------------------------------------------------------------------------
  it('selecting an option calls api.items.blockers.add and collapses the picker', async () => {
    mockSearch.mockResolvedValue([candidate])
    mockAdd.mockResolvedValue(candidate)

    const onChange = vi.fn()
    render(<BlockerPicker itemId={ITEM_ID} blockers={[]} onChange={onChange} />)

    await userEvent.click(screen.getByRole('button', { name: /add blocker/i }))

    const input = screen.getByRole('combobox')
    await userEvent.type(input, 'cand')

    // Wait for debounce + search mock to resolve
    await waitFor(() => expect(mockSearch).toHaveBeenCalled(), { timeout: 1000 })

    // Option should appear in the dropdown
    const option = await screen.findByRole('option', {
      name: /cccccccc.*New blocker candidate/,
    }, { timeout: 1000 })
    await userEvent.click(option)

    await waitFor(() => {
      expect(mockAdd).toHaveBeenCalledWith(ITEM_ID, candidate.id)
      expect(onChange).toHaveBeenCalledWith([candidate])
    })

    // Picker should collapse back to the button
    expect(screen.getByRole('button', { name: /add blocker/i })).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // 5. 400 response from add shows inline error
  // -------------------------------------------------------------------------
  it('shows an inline error message when add returns 400', async () => {
    mockSearch.mockResolvedValue([candidate])
    mockAdd.mockRejectedValue(new ApiError(400, 'Would create a dependency cycle'))

    render(<BlockerPicker itemId={ITEM_ID} blockers={[]} onChange={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: /add blocker/i }))

    const input = screen.getByRole('combobox')
    await userEvent.type(input, 'cand')

    await waitFor(() => expect(mockSearch).toHaveBeenCalled(), { timeout: 1000 })

    const option = await screen.findByRole('option', {
      name: /cccccccc.*New blocker candidate/,
    }, { timeout: 1000 })
    await userEvent.click(option)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Would create a dependency cycle',
      )
    })
  })

  // -------------------------------------------------------------------------
  // 6. Already-attached blockers are filtered from autocomplete suggestions
  // -------------------------------------------------------------------------
  it('filters already-attached blockers from autocomplete suggestions', async () => {
    // Search returns both the already-attached blocker1 AND a new candidate
    mockSearch.mockResolvedValue([blocker1, candidate])

    render(
      <BlockerPicker itemId={ITEM_ID} blockers={[blocker1]} onChange={vi.fn()} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /add blocker/i }))

    const input = screen.getByRole('combobox')
    await userEvent.type(input, 'bug')

    await waitFor(() => expect(mockSearch).toHaveBeenCalled(), { timeout: 1000 })

    // blocker1 (already attached) must NOT appear as an option
    await waitFor(() => {
      expect(
        screen.queryByRole('option', { name: /Fix the auth bug/ }),
      ).not.toBeInTheDocument()
    }, { timeout: 1000 })

    // The unattached candidate SHOULD appear
    expect(
      await screen.findByRole('option', { name: /New blocker candidate/ }, { timeout: 1000 }),
    ).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Accessibility: X button has the correct aria-label
  // -------------------------------------------------------------------------
  it('X button has aria-label "Remove blocker"', () => {
    render(
      <BlockerPicker itemId={ITEM_ID} blockers={[blocker1]} onChange={vi.fn()} />,
    )
    expect(screen.getByLabelText('Remove blocker')).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Accessibility: does not render delete buttons when disabled
  // -------------------------------------------------------------------------
  it('does not render delete buttons when disabled', () => {
    render(
      <BlockerPicker
        itemId={ITEM_ID}
        blockers={[blocker1]}
        onChange={vi.fn()}
        disabled
      />,
    )
    expect(screen.queryByLabelText('Remove blocker')).not.toBeInTheDocument()
  })
})
