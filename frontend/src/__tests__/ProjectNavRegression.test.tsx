/**
 * Regression guard for GTD 36c1b775 — "app navigation broken after a project
 * page loads".
 *
 * Root cause: the right-side ActivityDrawer / ItemDetailDrawer are `temporary`
 * MUI Drawers (Modals). On open their Modal locks body scroll
 * (`overflow:hidden` + `padding-right` on `document.body`) and mounts a
 * full-viewport backdrop; the `top:'64px'` offset is scoped to the paper only,
 * so the modal/backdrop span the whole viewport including the Sidebar. The fix
 * adds `disableScrollLock` so opening a drawer never mutates `document.body`,
 * guaranteeing no scroll-lock residue can outlive the drawer and leave the
 * Sidebar nav unclickable.
 *
 * NOTE: happy-dom does NOT compute layout, so real pointer-events / z-index
 * stacking cannot be asserted here. Instead this test asserts the observable
 * DOM invariants: (1) ActivityDrawer mounts nothing intercepting the page when
 * closed (no backdrop / modal root), (2) opening it does not scroll-lock the
 * body (the fix), and (3) a Sidebar nav-item click invokes `navigate`.
 *
 * Per AC, a full ProjectDetail render is impractical (heavy Auth/EventStream/
 * QuickCapture context + many api calls), so this uses the blessed narrower
 * harness: a Sidebar render test + an ActivityDrawer render test.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

const navigateMock = vi.fn()

vi.mock('react-router-dom', async (importActual) => {
  const actual = await importActual<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))

// ActivityDrawer (scope='project') renders a RunsTable that calls api.runs.list;
// stub it so no real network access happens (pattern from Runs.test.tsx).
vi.mock('../api', () => ({
  api: {
    runs: { list: vi.fn().mockResolvedValue([]) },
  },
  ApiError: class ApiError extends Error {},
}))

import Sidebar from '../components/Sidebar'
import ActivityDrawer from '../components/ActivityDrawer'

// ---------------------------------------------------------------------------
// Sidebar: a nav-item click must invoke navigate
// ---------------------------------------------------------------------------

describe('Sidebar navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('invokes navigate with the item path when a nav item is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Sidebar open isMobile={false} onClose={() => {}} />
      </MemoryRouter>,
    )

    await user.click(screen.getByText('Next Actions'))
    expect(navigateMock).toHaveBeenCalledWith('/next-actions')

    await user.click(screen.getByText('Settings'))
    expect(navigateMock).toHaveBeenCalledWith('/settings')
  })
})

// ---------------------------------------------------------------------------
// ActivityDrawer: closed-by-default mounts nothing intercepting the page,
// and opening it must not scroll-lock the body (the regression fix).
// ---------------------------------------------------------------------------

describe('ActivityDrawer overlay invariants', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset any leftover inline body style between tests.
    document.body.removeAttribute('style')
  })

  const baseProps = {
    onClose: () => {},
    projectId: 'proj-1',
    activeRolloutId: null,
    scope: 'project' as const,
    onScopeChange: () => {},
  }

  it('renders no intercepting backdrop/modal when closed (open=false)', () => {
    render(<ActivityDrawer {...baseProps} open={false} />)

    // Closed temporary Drawer must not mount a Modal or Backdrop that would sit
    // over the Sidebar and intercept nav clicks.
    expect(document.querySelector('.MuiBackdrop-root')).toBeNull()
    expect(document.querySelector('.MuiModal-root')).toBeNull()
    // And it must not have locked body scroll.
    expect(document.body.style.overflow).not.toBe('hidden')
  })

  it('does not lock body scroll when open (disableScrollLock fix)', async () => {
    render(<ActivityDrawer {...baseProps} open />)

    // The Modal is now mounted...
    await waitFor(() => {
      expect(document.querySelector('.MuiModal-root')).not.toBeNull()
    })
    // ...but disableScrollLock means document.body is NOT mutated, so no
    // scroll-lock residue (overflow:hidden / padding-right) can persist and
    // leave the Sidebar unclickable.
    expect(document.body.style.overflow).not.toBe('hidden')
    expect(document.body.style.paddingRight).toBe('')
  })
})
