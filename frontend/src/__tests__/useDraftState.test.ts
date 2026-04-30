import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useDraftState } from '../hooks/useDraftState'

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useDraftState', () => {
  // --- hydration ---

  it('hydrates state from existing storage on mount', () => {
    localStorage.setItem('draft-key', JSON.stringify('stored value'))
    const { result } = renderHook(() => useDraftState('draft-key', 'initial'))
    expect(result.current[0]).toBe('stored value')
  })

  it('uses initialValue when nothing is in storage', () => {
    const { result } = renderHook(() => useDraftState('draft-key', 'initial'))
    expect(result.current[0]).toBe('initial')
  })

  it('hydrates object values from storage', () => {
    const stored = { title: 'My draft', count: 42 }
    localStorage.setItem('obj-key', JSON.stringify(stored))
    const { result } = renderHook(() =>
      useDraftState('obj-key', { title: '', count: 0 }),
    )
    expect(result.current[0]).toEqual(stored)
  })

  // --- debounced write ---

  it('does not write to storage before the debounce window elapses', () => {
    const { result } = renderHook(() => useDraftState('w-key', 'initial'))

    act(() => {
      result.current[1]('new value')
    })

    // Timer has not fired yet — key should still be absent
    expect(localStorage.getItem('w-key')).toBeNull()
  })

  it('writes the latest value to storage after the debounce window', () => {
    const { result } = renderHook(() => useDraftState('w-key', 'initial'))

    act(() => {
      result.current[1]('new value')
    })

    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(localStorage.getItem('w-key')).toBe(JSON.stringify('new value'))
  })

  it('coalesces rapid edits — only the last value is written', () => {
    const { result } = renderHook(() => useDraftState('w-key', ''))

    act(() => {
      result.current[1]('a')
    })
    act(() => {
      result.current[1]('ab')
    })
    act(() => {
      result.current[1]('abc')
    })

    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(localStorage.getItem('w-key')).toBe(JSON.stringify('abc'))
  })

  it('respects a custom debounceMs option', () => {
    const { result } = renderHook(() =>
      useDraftState('d-key', 'initial', { debounceMs: 1000 }),
    )

    act(() => {
      result.current[1]('hello')
    })

    // 300 ms is not enough for a 1000 ms debounce
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(localStorage.getItem('d-key')).toBeNull()

    act(() => {
      vi.advanceTimersByTime(700)
    })
    expect(localStorage.getItem('d-key')).toBe(JSON.stringify('hello'))
  })

  // --- clearDraft ---

  it('clearDraft() resets state to initialValue', () => {
    localStorage.setItem('c-key', JSON.stringify('stored'))
    const { result } = renderHook(() => useDraftState('c-key', 'initial'))

    expect(result.current[0]).toBe('stored')

    act(() => {
      result.current[2]() // clearDraft
    })

    expect(result.current[0]).toBe('initial')
  })

  it('clearDraft() removes the key from storage', () => {
    localStorage.setItem('c-key', JSON.stringify('stored'))
    const { result } = renderHook(() => useDraftState('c-key', 'initial'))

    act(() => {
      result.current[2]()
    })

    expect(localStorage.getItem('c-key')).toBeNull()
  })

  it('clearDraft() cancels a pending debounced write', () => {
    const { result } = renderHook(() => useDraftState('c-key', 'initial'))

    act(() => {
      result.current[1]('unsaved')
    })

    // Clear before the debounce fires
    act(() => {
      result.current[2]()
    })

    // Advance past the original debounce window
    act(() => {
      vi.advanceTimersByTime(500)
    })

    // The key should not have been written because clearDraft cancelled the timer
    expect(localStorage.getItem('c-key')).toBeNull()
  })

  // --- malformed JSON ---

  it('falls back to initialValue when stored JSON is malformed', () => {
    localStorage.setItem('bad-key', '{not valid json}')
    const { result } = renderHook(() => useDraftState('bad-key', 'fallback'))
    expect(result.current[0]).toBe('fallback')
  })

  it('removes the bad storage entry when JSON is malformed', () => {
    localStorage.setItem('bad-key', '{not valid json}')
    renderHook(() => useDraftState('bad-key', 'fallback'))
    expect(localStorage.getItem('bad-key')).toBeNull()
  })

  // --- key isolation ---

  it('two hooks with different keys are fully independent', () => {
    localStorage.setItem('key-a', JSON.stringify('alpha'))
    localStorage.setItem('key-b', JSON.stringify('beta'))

    const { result: rA } = renderHook(() => useDraftState('key-a', 'init'))
    const { result: rB } = renderHook(() => useDraftState('key-b', 'init'))

    expect(rA.current[0]).toBe('alpha')
    expect(rB.current[0]).toBe('beta')

    // Clear A, B should be unaffected
    act(() => {
      rA.current[2]()
    })

    expect(rA.current[0]).toBe('init')
    expect(rB.current[0]).toBe('beta')
    expect(localStorage.getItem('key-a')).toBeNull()
    expect(localStorage.getItem('key-b')).toBe(JSON.stringify('beta'))
  })

  it('writes from two hooks with different keys do not overwrite each other', () => {
    const { result: rA } = renderHook(() => useDraftState('ka', 'ia'))
    const { result: rB } = renderHook(() => useDraftState('kb', 'ib'))

    act(() => {
      rA.current[1]('value-a')
      rB.current[1]('value-b')
    })

    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(localStorage.getItem('ka')).toBe(JSON.stringify('value-a'))
    expect(localStorage.getItem('kb')).toBe(JSON.stringify('value-b'))
  })

  // --- custom storage ---

  it('accepts a custom storage implementation', () => {
    const store: Record<string, string> = {}
    const customStorage: Storage = {
      getItem: (k) => store[k] ?? null,
      setItem: (k, v) => { store[k] = v },
      removeItem: (k) => { delete store[k] },
      clear: () => { Object.keys(store).forEach((k) => delete store[k]) },
      key: (i) => Object.keys(store)[i] ?? null,
      length: 0,
    }

    store['cs-key'] = JSON.stringify('custom stored')
    const { result } = renderHook(() =>
      useDraftState('cs-key', 'default', { storage: customStorage }),
    )

    expect(result.current[0]).toBe('custom stored')

    act(() => {
      result.current[1]('new')
    })
    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(store['cs-key']).toBe(JSON.stringify('new'))
  })
})
