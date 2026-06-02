/**
 * Regression guard for GTD aec3ee1f — "guaranteed nav-recovery: clear
 * stranded MUI inert/aria-hidden that kills the sidebar after a project page
 * loads".
 *
 * Root cause: MUI's ModalManager marks the direct children of document.body
 * (typically the React #root element) with `inert` and `aria-hidden="true"`
 * while a modal is open.  When a modal unmounts without its cleanup running,
 * those attributes are stranded: the Sidebar stays visible but inert, so
 * clicks are swallowed until the user reloads.
 *
 * Fix: useInertGuard (Layout.tsx) installs a MutationObserver that fires on
 * attribute mutations and strips both attributes from body-child elements when
 * no .MuiModal-root is present in the DOM.
 *
 * Test approach: real-DOM attribute assertions.  happy-dom supports
 * inert/aria-hidden as DOM attributes (unlike pointer-events/layout which it
 * does not compute), so we can assert the guard's cleanup without a real
 * browser.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { useInertGuard } from '../hooks/useInertGuard'

// ---------------------------------------------------------------------------
// Module mocks (same pattern as ProjectNavRegression.test.tsx)
// ---------------------------------------------------------------------------

const navigateMock = vi.fn()

vi.mock('react-router-dom', async (importActual) => {
  const actual = await importActual<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))

import Sidebar from '../components/Sidebar'

// ---------------------------------------------------------------------------
// Minimal harness that mounts only the guard effect
// ---------------------------------------------------------------------------

function InertGuardHarness(): null {
  useInertGuard()
  return null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Append a fresh div to document.body and return it + a cleanup fn. */
function appendBodyChild(): { el: HTMLDivElement; cleanup: () => void } {
  const el = document.createElement('div')
  document.body.appendChild(el)
  return {
    el,
    cleanup: () => {
      if (el.parentElement === document.body) document.body.removeChild(el)
    },
  }
}

// ---------------------------------------------------------------------------
// Suite 1: guard removes stranded attributes when no modal is open
// ---------------------------------------------------------------------------

describe('useInertGuard — stranded inert (no modal open)', () => {
  let bodyChildCleanup: (() => void) | null = null

  afterEach(() => {
    bodyChildCleanup?.()
    bodyChildCleanup = null
    // Remove any lingering .MuiModal-root sentinels
    document.querySelectorAll('.MuiModal-root').forEach((el) => el.remove())
  })

  it('removes stranded `inert` from a direct body child when no modal is open', async () => {
    render(<InertGuardHarness />)

    const { el, cleanup } = appendBodyChild()
    bodyChildCleanup = cleanup

    el.setAttribute('inert', '')

    await waitFor(() => {
      expect(el.hasAttribute('inert')).toBe(false)
    })
  })

  it('removes stranded `aria-hidden="true"` from a direct body child when no modal is open', async () => {
    render(<InertGuardHarness />)

    const { el, cleanup } = appendBodyChild()
    bodyChildCleanup = cleanup

    el.setAttribute('aria-hidden', 'true')

    await waitFor(() => {
      expect(el.getAttribute('aria-hidden')).not.toBe('true')
    })
  })

  it('removes BOTH stranded attributes together (MUI always sets them as a pair)', async () => {
    render(<InertGuardHarness />)

    const { el, cleanup } = appendBodyChild()
    bodyChildCleanup = cleanup

    // MUI ModalManager always sets both attributes together when suppressing siblings
    el.setAttribute('inert', '')
    el.setAttribute('aria-hidden', 'true')

    await waitFor(() => {
      expect(el.hasAttribute('inert')).toBe(false)
      expect(el.getAttribute('aria-hidden')).not.toBe('true')
    })
  })

  it('does NOT strip `aria-hidden` with a value other than "true"', async () => {
    render(<InertGuardHarness />)

    const { el, cleanup } = appendBodyChild()
    bodyChildCleanup = cleanup

    el.setAttribute('aria-hidden', 'false')

    // Wait a tick so any observer callback would have had a chance to fire
    await new Promise<void>((resolve) => setTimeout(resolve, 50))

    // "false" must not be touched — only "true" is the ModalManager's strand marker
    expect(el.getAttribute('aria-hidden')).toBe('false')
  })
})

// ---------------------------------------------------------------------------
// Suite 2: guard leaves attributes untouched when a modal IS open
// ---------------------------------------------------------------------------

describe('useInertGuard — legitimate inert (modal is open)', () => {
  let bodyChildCleanup: (() => void) | null = null
  let modalCleanup: (() => void) | null = null

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    bodyChildCleanup?.()
    bodyChildCleanup = null
    modalCleanup?.()
    modalCleanup = null
  })

  it('does NOT strip inert / aria-hidden when a .MuiModal-root exists', async () => {
    render(<InertGuardHarness />)

    // Simulate an open MUI modal by appending a .MuiModal-root sentinel to body
    const modal = document.createElement('div')
    modal.className = 'MuiModal-root'
    document.body.appendChild(modal)
    modalCleanup = () => {
      if (modal.parentElement === document.body) document.body.removeChild(modal)
    }

    const { el, cleanup } = appendBodyChild()
    bodyChildCleanup = cleanup

    el.setAttribute('inert', '')
    el.setAttribute('aria-hidden', 'true')

    // Give the observer a full tick to fire (it must NOT remove)
    await new Promise<void>((resolve) => setTimeout(resolve, 50))

    expect(el.hasAttribute('inert')).toBe(true)
    expect(el.getAttribute('aria-hidden')).toBe('true')
  })
})

// ---------------------------------------------------------------------------
// Suite 3: Sidebar nav items are interactive after stranded inert is cleared
// ---------------------------------------------------------------------------

describe('Sidebar nav — interactive after inert recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('Sidebar nav click invokes navigate after stranded inert is cleared', async () => {
    const user = userEvent.setup()

    // Render guard + Sidebar together; the render container is a direct body
    // child so we can strand it to simulate the real-world MUI scenario.
    const { container } = render(
      <MemoryRouter>
        <InertGuardHarness />
        <Sidebar open isMobile={false} onClose={() => {}} />
      </MemoryRouter>,
    )

    // Strand both attributes on the container (direct child of body)
    container.setAttribute('inert', '')
    container.setAttribute('aria-hidden', 'true')

    // Guard should strip them
    await waitFor(() => {
      expect(container.hasAttribute('inert')).toBe(false)
    })
    expect(container.getAttribute('aria-hidden')).not.toBe('true')

    // Now nav items must be clickable and invoke navigate
    await user.click(screen.getByText('Next Actions'))
    expect(navigateMock).toHaveBeenCalledWith('/next-actions')
  })
})
