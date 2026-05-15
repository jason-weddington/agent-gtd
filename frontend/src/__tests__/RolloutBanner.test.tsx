/**
 * Tests for RolloutBanner pure helper functions.
 *
 * AC-3, AC-4, AC-5 (pure helper coverage).
 * AC-9, AC-10 (isStateStale helper).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { getStatusColor, getTitleText, getProgressFraction, isStateStale, shouldPrepondRolloutEvent } from '../components/RolloutBanner'
import type { RolloutStatus } from '../types'

// ---------------------------------------------------------------------------
// getStatusColor (AC-4)
// ---------------------------------------------------------------------------

describe('getStatusColor', () => {
  const cases: Array<[RolloutStatus, string]> = [
    ['pending', 'default'],
    ['planning', 'default'],
    ['running', 'info'],
    ['halted', 'warning'],
    ['failed', 'error'],
    ['completed', 'success'],
  ]

  for (const [status, expected] of cases) {
    it(`returns '${expected}' for status '${status}'`, () => {
      expect(getStatusColor(status)).toBe(expected)
    })
  }
})

// ---------------------------------------------------------------------------
// getTitleText (AC-3)
// ---------------------------------------------------------------------------

describe('getTitleText', () => {
  it('returns "Autonomous Dispatch Management in Progress" for pending', () => {
    expect(getTitleText('pending')).toBe('Autonomous Dispatch Management in Progress')
  })

  it('returns "Autonomous Dispatch Management in Progress" for planning', () => {
    expect(getTitleText('planning')).toBe('Autonomous Dispatch Management in Progress')
  })

  it('returns "Autonomous Dispatch Management in Progress" for running', () => {
    expect(getTitleText('running')).toBe('Autonomous Dispatch Management in Progress')
  })

  it('returns "Wave Halted — Review Needed" for halted', () => {
    expect(getTitleText('halted')).toBe('Wave Halted — Review Needed')
  })

  it('returns "Wave Failed" for failed', () => {
    expect(getTitleText('failed')).toBe('Wave Failed')
  })

  it('returns "Wave Completed" for completed', () => {
    expect(getTitleText('completed')).toBe('Wave Completed')
  })
})

// ---------------------------------------------------------------------------
// getProgressFraction (AC-5)
// ---------------------------------------------------------------------------

describe('getProgressFraction', () => {
  it('returns 0 when totalCount is 0', () => {
    expect(getProgressFraction(0, 0)).toBe(0)
  })

  it('returns 0 when doneCount is 0', () => {
    expect(getProgressFraction(0, 10)).toBe(0)
  })

  it('returns 0.5 when half done', () => {
    expect(getProgressFraction(5, 10)).toBe(0.5)
  })

  it('returns 1 when all done', () => {
    expect(getProgressFraction(10, 10)).toBe(1)
  })

  it('clamps to 1 when doneCount exceeds totalCount', () => {
    expect(getProgressFraction(12, 10)).toBe(1)
  })

  it('handles single item done', () => {
    expect(getProgressFraction(1, 5)).toBeCloseTo(0.2)
  })
})

// ---------------------------------------------------------------------------
// isStateStale (AC-9, AC-10)
// ---------------------------------------------------------------------------

describe('isStateStale', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns true when updatedAt is null', () => {
    expect(isStateStale(null)).toBe(true)
  })

  it('returns false when updatedAt is within threshold (fresh)', () => {
    vi.useFakeTimers()
    const now = new Date('2026-05-13T12:00:00Z')
    vi.setSystemTime(now)
    // 1 minute ago — within 5-minute default threshold
    const oneMinuteAgo = new Date(now.getTime() - 60_000).toISOString()
    expect(isStateStale(oneMinuteAgo)).toBe(false)
  })

  it('returns true when updatedAt exceeds default 5-minute threshold', () => {
    vi.useFakeTimers()
    const now = new Date('2026-05-13T12:00:00Z')
    vi.setSystemTime(now)
    // 6 minutes ago — beyond 5-minute default threshold
    const sixMinutesAgo = new Date(now.getTime() - 6 * 60_000).toISOString()
    expect(isStateStale(sixMinutesAgo)).toBe(true)
  })

  it('returns false exactly at the threshold boundary', () => {
    vi.useFakeTimers()
    const now = new Date('2026-05-13T12:00:00Z')
    vi.setSystemTime(now)
    // Exactly 5 minutes ago — NOT stale (> not >=)
    const exactlyFiveMinutesAgo = new Date(now.getTime() - 5 * 60_000).toISOString()
    expect(isStateStale(exactlyFiveMinutesAgo)).toBe(false)
  })

  it('respects a custom threshold', () => {
    vi.useFakeTimers()
    const now = new Date('2026-05-13T12:00:00Z')
    vi.setSystemTime(now)
    // 2 minutes ago with a 1-minute custom threshold → stale
    const twoMinutesAgo = new Date(now.getTime() - 2 * 60_000).toISOString()
    expect(isStateStale(twoMinutesAgo, 60_000)).toBe(true)
    // 30 seconds ago with a 1-minute custom threshold → fresh
    const thirtySecondsAgo = new Date(now.getTime() - 30_000).toISOString()
    expect(isStateStale(thirtySecondsAgo, 60_000)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// shouldPrepondRolloutEvent (AC-2)
// ---------------------------------------------------------------------------

describe('shouldPrepondRolloutEvent', () => {
  it('returns true when event rolloutId matches current rolloutId', () => {
    expect(shouldPrepondRolloutEvent('rollout-123', 'rollout-123')).toBe(true)
  })

  it('returns false when event rolloutId differs from current rolloutId', () => {
    expect(shouldPrepondRolloutEvent('rollout-new', 'rollout-old')).toBe(false)
  })

  it('returns false when currentRolloutId is null (no active rollout)', () => {
    expect(shouldPrepondRolloutEvent('rollout-123', null)).toBe(false)
  })

  it('returns false when currentRolloutId is undefined', () => {
    expect(shouldPrepondRolloutEvent('rollout-123', undefined)).toBe(false)
  })

  it('returns false when currentRolloutId is empty string', () => {
    expect(shouldPrepondRolloutEvent('rollout-123', '')).toBe(false)
  })

  it('returns false when both IDs are empty string', () => {
    // Empty eventRolloutId should not match even against itself when current is empty
    expect(shouldPrepondRolloutEvent('', '')).toBe(false)
  })

  it('handles UUID-format IDs', () => {
    const id = 'c3d0d4cc-abec-4a84-915d-49c4273adf4d'
    expect(shouldPrepondRolloutEvent(id, id)).toBe(true)
    expect(shouldPrepondRolloutEvent(id, 'other-uuid')).toBe(false)
  })
})
