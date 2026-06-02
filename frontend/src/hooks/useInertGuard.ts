import { useEffect } from 'react'
import { isModalOpen } from '../utils'

/**
 * Global guard that removes stranded MUI `inert` / `aria-hidden="true"`
 * attributes from the app-root container node(s).
 *
 * ### Why this is needed
 *
 * MUI's ModalManager marks the Modal portal's siblings (i.e. direct children
 * of `document.body` — typically the React `#root` element) with `inert` and
 * `aria-hidden="true"` while a modal is open.  When a modal unmounts without
 * its cleanup running (e.g. because a Suspense boundary or concurrent-mode
 * tear-down interrupts the close transition), those attributes are left
 * stranded.  The Sidebar is part of `#root`, so it becomes invisible-to-events
 * even though it looks perfectly normal; clicking nav items does nothing until
 * the user performs a full page reload.
 *
 * ### Why a MutationObserver instead of a route-change effect
 *
 * The strand happens during the destination page's own mount — i.e. at the
 * same time as React is committing the new route's component tree.  A
 * `useEffect` that fires on `pathname` changes runs *after* the commit, but
 * by then the modal has already been torn down and its cleanup skipped.  The
 * MutationObserver fires on the attribute mutation itself, which guarantees
 * the guard wins the race regardless of when in the render/commit cycle the
 * strand occurs.
 *
 * ### Safety
 *
 * The guard only removes the attributes when **no `.MuiModal-root` element is
 * present** in the document.  When a modal really is open, the attributes are
 * legitimate and are left untouched.
 *
 * Mount this hook once, high in the component tree (Layout or App), so it is
 * active on every route.
 */
export function useInertGuard(): void {
  useEffect(() => {
    function handleMutation(mutation: MutationRecord): void {
      const target = mutation.target as Element
      // Only act on direct children of <body> — that is where MUI ModalManager
      // sets inert / aria-hidden to suppress the rest of the app.
      if (target.parentElement !== document.body) return
      // A live modal means the inert is intentional — leave it alone.
      if (isModalOpen(document)) return
      // No modal present: the attributes are stranded.  Strip them.
      if (target.hasAttribute('inert')) {
        target.removeAttribute('inert')
      }
      if (target.getAttribute('aria-hidden') === 'true') {
        target.removeAttribute('aria-hidden')
      }
    }

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type !== 'attributes') continue
        const attr = mutation.attributeName
        if (attr !== 'inert' && attr !== 'aria-hidden') continue
        handleMutation(mutation)
      }
    })

    // Observe document.body with subtree:true so we catch mutations on its
    // direct children.  The attributeFilter limits callbacks to the two
    // attributes we care about, keeping overhead negligible.
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['inert', 'aria-hidden'],
      subtree: true,
    })

    return () => {
      observer.disconnect()
    }
  }, [])
}
