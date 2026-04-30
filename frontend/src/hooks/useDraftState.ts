import { useState, useEffect, useRef, useCallback } from 'react'
import type { Dispatch, SetStateAction } from 'react'

/**
 * Persist transient form state to storage (default: localStorage) on every
 * value change (debounced), restore on mount, and clear on explicit dismiss.
 *
 * Domain-agnostic — works with any form in any app.
 *
 * @param key     Storage key. Callers are responsible for namespacing, e.g.
 *                `myapp:draft:new-post` or `myapp:draft:comment:${itemId}`.
 * @param initialValue  Value to use when no stored draft exists (or on clear).
 * @param options  debounceMs (default 300), storage (default localStorage).
 *
 * @returns  [value, setValue, clearDraft]
 *   - `setValue`   — standard React state setter; schedules a debounced write.
 *   - `clearDraft` — removes the key from storage AND resets state to
 *                    `initialValue`.  Call on successful submit or explicit
 *                    Cancel.  Do NOT call on backdrop / Escape — that way an
 *                    accidental dismiss preserves the draft.
 */
export function useDraftState<T>(
  key: string,
  initialValue: T,
  options?: { debounceMs?: number; storage?: Storage },
): [T, Dispatch<SetStateAction<T>>, () => void] {
  const debounceMs = options?.debounceMs ?? 300

  // Storage handle. localStorage / a passed-in Storage are stable singletons,
  // so a direct ref-free read each render is fine — the value never changes.
  const storage: Storage | null =
    typeof window !== 'undefined' ? (options?.storage ?? localStorage) : null

  // Capture initialValue once; never updated so clearDraft always resets to
  // the original value regardless of what the caller passes on later renders.
  const initialValueRef = useRef<T>(initialValue)

  // Pending debounce timer handle.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // When clearDraft() is called it resets state to initialValue, which would
  // otherwise trigger the write effect and immediately re-persist the empty
  // initial value.  This flag lets the effect skip that one spurious write.
  const skipNextWriteRef = useRef(false)

  // Initialise state from storage.  If the stored JSON is malformed, fall back
  // to initialValue and remove the bad entry so it doesn't poison future mounts.
  const [state, setState] = useState<T>(() => {
    if (!storage) return initialValue
    try {
      const raw = storage.getItem(key)
      if (raw === null) return initialValue
      return JSON.parse(raw) as T
    } catch {
      try {
        storage.removeItem(key)
      } catch {
        // ignore storage errors
      }
      return initialValue
    }
  })

  // Debounced write — fires when state changes.  The cleanup cancels any
  // pending timer so rapid edits coalesce into a single write per window.
  useEffect(() => {
    if (!storage) return

    // Skip the write that would otherwise immediately follow clearDraft().
    if (skipNextWriteRef.current) {
      skipNextWriteRef.current = false
      return
    }

    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
    }

    // Capture state in the closure so the write always reflects the value that
    // triggered this particular effect invocation.
    const snapshot = state
    timerRef.current = setTimeout(() => {
      try {
        storage.setItem(key, JSON.stringify(snapshot))
      } catch {
        // ignore quota / security errors
      }
      timerRef.current = null
    }, debounceMs)

    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [state, key, debounceMs, storage])

  // clearDraft: remove the key from storage, cancel any pending write, and
  // reset in-memory state to the original initialValue.
  const clearDraft = useCallback(() => {
    if (storage) {
      try {
        storage.removeItem(key)
      } catch {
        // ignore storage errors
      }
    }
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    skipNextWriteRef.current = true
    setState(initialValueRef.current)
  }, [key, storage])

  return [state, setState, clearDraft]
}
